import json
from discord.ext import commands


class JsonDB:
    def __init__(self, db_name):
        self.db_name = db_name
        self.db = []
        self.filename = f'{self.db_name}.json'
        try:
            with open(self.filename, 'x') as db:
                json.dump(self.db, db, default=self._encoder)
        except FileExistsError:
            with open(self.filename, 'r+') as db:
                self.db = json.load(db, object_hook=self._decoder)

    def save(self):
        with open(self.filename, 'w') as db:
            json.dump(self.db, db, default=self._encoder)

    def find_first(self, attr, value):
        try:
            return next((p for p in self.db if vars(p)[attr] == value))
        except StopIteration:
            raise KeyError(f'Theres no such object in the database.') from None

    @staticmethod
    def _decoder(dct):
        if 'captain' in dct.keys():
            return Team(dct['name'], dct['captain'], *dct['players'])
        elif 'discord_id' in dct.keys():
            player = Player(dct['name'])
            player.ingame_name = dct['ingame_name']
            player.team = dct['team']
            player.discord_id = dct['discord_id']
            player.achievements = dct['achievements']
            return player
        return dct

    @staticmethod
    def _encoder(o):
        if isinstance(o, Player):
            return {'name': o.name,
                    'ingame_name': o.ingame_name,
                    'team': o.team,
                    'discord_id': o.discord_id,
                    'achievements': o.achievements
                    }
        elif isinstance(o, Team):
            return {'name': o.name,
                    'captain': o.captain,
                    'players': list(o.players)
                    }
        return json.JSONEncoder().default(o)


class Tournament(commands.Cog):
    def __init__(self):
        self.teams_db = JsonDB('teamsDB')
        self.players_db = JsonDB('playersDB')
        self.member_converter = commands.MemberConverter()
        self.matches = []
        """Match: {
        'team1': team1,
        'team2': team2,
        'winner': winner (is None before winner is set)
        'score': (team1_score, team2_score) <- tuple
        }"""
        self.registration_open = True
        self.registration_date = None
        self.betting = Betting(self)
        self.bets_open = False
        self.date = None
        self.info = f"""Next tournament date: Unknown
Registration status: -
"""

    @commands.group(invoke_without_command=True, aliases=['t'], ignore_extra=False, brief='See info and register to a tournament')
    async def tournament(self, ctx):
        """Shows tournament info if used without any subcommands.
        To leave the team, use the `tournament leave` command. Note that if captain leaves the team, the whole team is disbanded.
        You can also use short version of the command: '>t'.
        To see help for subcommands, do >help t <sub-command>."""
        await ctx.send(self.info)
        return True

    @tournament.command()
    async def register(self, ctx, team_name, *players):
        """Registers a team and it's players. Usage: `>tournament register <team-name> <player1> <player2>...` (`>tournament` can be shortened to `>t`). You can @mention the player, or write his name as plain text (if he's not on Discord). If the name has spaces, use "double quotes".
        
        Preferably register as a full 3-player team. If there will be teams registered with only two or one player, we will try to put them into single team before start; if there will not be enough players to do this, the registration is voided.

        To see details about any team, do `>t team <tesm-name>`
        To see details about a player, do `>t player <player-name>` (again, you can @mention)
        To leave your team, do `>t leave`. If you are a captain, doing this will disband the whole team!

        Example: Max wants to join the tournament, and persuades Fanta and one other friend, Bob the Inquisitor, to join with him. They decide to name their team 'SpanishInquisition'. Fanta is on Discord (@Fantasifoster), but Bob doesn't have a Discord account. To register them, Max sends the following command in #lenny: `>tournament register SpanishInquisition @Fantasifoster "Bob the Inquisitor"`. He then checks that they have been registered correctly by sending command `>tournament team SpanishInquisition`. Since he sees the team has been registered correctly, they start training for the tournament to win - they have only 10 days!
        """
        if not self.registration_open:
            await ctx.send(f'The registration hasn\'t been opened yet!')
            return True
        try:
            self.teams_db.find_first('name', team_name)
            await ctx.send(f'Error in team registration: Team with name {team_name} already exists.')
            return True
        except KeyError:
            pass
        team_players = []
        for name in players:
            try:
                _p = await self.member_converter.convert(ctx, name)
                team_players.append(_p.nick)
            except commands.MemberNotFound:
                team_players.append(name)
        _team = Team(team_name, ctx.author.nick, *team_players)
        print(team_players)

        # Update / create Players
        for _player_name in _team.players:
            try:
                member = await commands.MemberConverter().convert(ctx, _player_name)
                try:
                    _player = self.players_db.find_first('discord_id', member.id)
                    if _player.team is not None:
                        await ctx.send(
                            f'Error in team registration: {member.mention} is already registered with {_player.team}!')
                        # load the DB state from before we started parsing players, reverting all changes
                        self.players_db = JsonDB('playersDB')
                        self.teams_db = JsonDB('teamsDB')
                        return False
                    else:
                        _player.team = _team.name
                        continue
                except KeyError:
                    _player = Player(member.nick)
                    _player.discord_id = member.id
                    _player.team = team_name
                    self.players_db.db.append(_player)
                    continue
            except commands.MemberNotFound:
                pass
            try:
                _player = self.players_db.find_first('name', _player_name)
                _player.team = team_name
            except KeyError:
                _player = Player(_player_name)
                _player.team = team_name
                self.players_db.db.append(_player)
        self.players_db.save()
        self.teams_db.db.append(_team)
        self.teams_db.save()

    @tournament.command(name='leave')
    async def unregister(self, ctx):
        """Unregisters the command caller from his team. If he's a captain, also deletes the whole team."""
        try:
            _player = self.players_db.find_first('discord_id', ctx.author.id)
        except KeyError:
            await ctx.send(f'{ctx.author.mention}, you have not registered yet!')
            return True
        if _player.team is not None:
            _team = self.teams_db.find_first('name', _player.team)
            # Remove whole team if the guy is captain
            if _player.name == _team.captain:
                for name in _team.players:
                    print(name)
                    p = self.players_db.find_first('name', name)
                    p.team = None
                self.teams_db.db.remove(_team)
                await ctx.send(
                    f'{ctx.author.mention}, you have successfully left team {_team.name}. As you were the captain, the whole team has been disbanded.')
            else:
                _team.players.remove(_player.name)
                await ctx.send(f'{ctx.author.mention}, you have successfully left team {_team.name}!')
            _player.team = None
            self.players_db.save()
            self.teams_db.save()
            return True
        await ctx.send(f'{ctx.author.mention}, you are not registered with any team at the moment.')

    @tournament.command(name='team')
    async def _team_info(self, ctx, team_name):
        """Shows all players registered in a team.
        """
        try:
            _team = self.teams_db.find_first('name', team_name)
            await ctx.send(_team.team_info())
        except KeyError:
            await ctx.send(f'{team_name} has not been found.')

    @tournament.command(name='player')
    async def _player_info(self, ctx, player_name):
        """Shows tournament details about any player. You can use @mention or write name in plain text."""
        try:
            member = await commands.MemberConverter().convert(ctx, player_name)
            _player = self.players_db.find_first('discord_id', member.id)
            await ctx.send(_player.player_info())
            return True
        except commands.MemberNotFound:
            try:
                _player = self.players_db.find_first('name', player_name)
            except KeyError:
                await ctx.send(f'{player_name} has not been found.')
                return False
        except KeyError:
            await ctx.send(f'{player_name} has not been found.')
            return False
        await ctx.send(_player.player_info())
        return True

    @tournament.group(invoke_without_command=True, ignore_extra=False)
    @commands.is_owner()
    async def match(self, ctx, team1, team2):
        """Sets up the next match. Only admin can use this."""
        self.matches.append({'team1': team1, 'team2': team2, 'winner': None})
        team1 = self.teams_db.find_first('name', team1)
        team2 = self.teams_db.find_first('name', team2)
        send_string = f'**Next up is team {team1.name} vs. team {team2.name}!**\nPlayers, please ready up into the lobby:'
        for team in (team1, team2):
            for player_name in team.players:
                player = self.players_db.find_first('name', player_name)
                if player.discord_id:
                    member = await self.member_converter.convert(ctx, str(player.discord_id))
                    send_string += f' {member.mention}'
                    continue
                send_string += f' {player.name}'
            if team is not team2:
                send_string += f' vs. '
        send_string += f'\nGood luck and have fun! May the best wizard win :mage:'
        await ctx.send(send_string)
        await self.betting.start_betting(ctx)

    @match.command(name='result', aliases=['winner'])
    async def set_match_result(self, ctx, winner):
        """Sets the winner and resolves all bets of a match. Only admin can use this."""
        try:
            winner = self.teams_db.find_first('name', winner)
        except KeyError:
            await ctx.send(f'{winner.name} has not been found in the database.')
        self.matches[-1]['winner'] = winner.name
        send_string = f'Congratulations to winners of this match, team {winner.name}!\n' \
                      f'Folowing betters have won some bananas:'
        # sum all the bets and get the proportions
        team1_bets_sum = sum([bet[1] for bet in self.betting.team1_bets])
        if team1_bets_sum < 100:
            team1_bets_sum = 100
        team2_bets_sum = sum([bet[1] for bet in self.betting.team2_bets])
        if team2_bets_sum < 100:
            team2_bets_sum = 100
        if winner.name == self.matches[-1]['team1']:
            winning_bets = self.betting.team1_bets
            odds = team2_bets_sum / team1_bets_sum
        else:
            winning_bets = self.betting.team2_bets
            odds = team1_bets_sum / team2_bets_sum
        for bet in winning_bets:
            win = int(bet[1] * odds)
            self.betting.betters[bet[0]] += win
            member = await self.member_converter.convert(ctx, str(bet[0]))
            send_string += f'\n{member.mention}: {win} bananas'
        await ctx.send(send_string)


class Betting(commands.Cog):
    def __init__(self, tournament):
        self.bets_open = False
        self.tournament = tournament
        self.betters = {}
        self.team1_bets = []
        self.team2_bets = []
        self.starting_amount = 500

    @commands.group(invoke_without_command=True, brief='Bet some bananas on one of the teams in the match!')
    async def bet(self, ctx, amount: int, team: int):
        """Bet some bananas on one of the teams in the match! Note that the win is calculated based on how much bananas was bet on the opposite team. This means you won't win much by betting on a favourite, but can win a lot by betting on the underdog.

        """
        if not self.bets_open:
            await ctx.send(f'Betting for next match has not been opened yet!')
            return True
        discord_id = ctx.author.id
        bananas = self._get_bananas(discord_id)
        # check the amount of bananas player has
        if bananas < amount:
            await ctx.send(f'{ctx.author.mention}, you don\'t have enough bananas!')
            return True
        # if the player has a previous bet, cancel it
        await self.cancel(ctx, no_output=True)
        # place the bet
        if team == 1:
            self.team1_bets.append((discord_id, amount))
        elif team == 2:
            self.team2_bets.append((discord_id, amount))
        else:
            await ctx.send(f'{ctx.author.mention}, you didn\'t choose a valid team.')
            return True
        # deduct bananas
        self.betters[discord_id] -= amount
        await ctx.send(f'{ctx.author.mention}, your bet has been successfully placed!')
        return True

    async def start_betting(self, ctx):
        self.bets_open = True
        team1_name = self.tournament.matches[-1]['team1']
        team2_name = self.tournament.matches[-1]['team2']
        send_string = f'\nTo bet on the match, do the following (in #lenny):\n' \
                      f'`>bet <amount-to-bet> 1` to bet on {team1_name}\n' \
                      f'`>bet <amount-to-bet> 2` to bet on {team2_name}\n' \
                      f'To find out how much bananas you have, do `>bet balance`'
        await ctx.send(send_string)

    @bet.command()
    async def cancel(self, ctx, no_output=False):
        """Cancel your bet."""
        for bet_list in (self.team1_bets, self.team2_bets):
            for x in bet_list:
                if x[0] == ctx.author.id:
                    self.betters[ctx.author.id] += x[1]
                    bet_list.remove(x)
                    if not no_output:
                        await ctx.send(f'{ctx.author.mention}, your bet has been canceled.')
                        return True
        if not no_output:
            await ctx.send(f'{ctx.author.mention}, no previous bet to cancel has been found.')

    @bet.command()
    async def balance(self, ctx):
        """Shows you how many bananas you have. At the start of the tournament, everyone gets 500 bananas."""
        bananas = self._get_bananas(ctx.author.id)
        await ctx.send(f'{ctx.author.mention}, you currently have {bananas} bananas available.')

    @bet.command(aliases=['close'])
    @commands.is_owner()
    async def stop(self, ctx):
        """Closes all the bets for current match. Only admin can use this."""
        self.bets_open = False
        await ctx.send('The bets for the current match have been closed.')

    def _get_bananas(self, _id):
        if _id not in self.betters:
            self.betters[_id] = self.starting_amount
        return self.betters[_id]


class Player:
    def __init__(self, name):
        self.name = name
        self.ingame_name = None
        self.team = None
        self.discord_id = None
        self.achievements = []

    def player_info(self):
        send_string = f'Tournament info for {self.name}:\n'
        if self.ingame_name is not None:
            send_string += f'In-game nick: {self.ingame_name}\n'
        if self.team is None:
            send_string += 'Not registered in any team\n'
        else:
            send_string += f'Team: {self.team}\n'
        return send_string


class Team:
    def __init__(self, name, captain, *args):
        self.name = name
        self.captain = captain
        self.players = set()
        for person in args:
            self.players.add(person)
        self.players.add(captain)

    def team_info(self):
        send_string = f'Team {self.name}:\n'
        send_string += f'Players: '
        for player in self.players:
            send_string += f'\n -> {player}'
        send_string += f'\nCaptain: {self.captain}'
        return send_string


# Extension thingie
def setup(bot):
    tournament = Tournament()
    bot.add_cog(tournament)
    bot.add_cog(tournament.betting)
