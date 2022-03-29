import json
from discord.ext import commands, tasks
import challonge
import requests


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
    CHALLONGE_SUBDOMAIN = "9d7a92ca1e0988a11ef9d7ab"
    TESTING = True

    def __init__(self, tourney_url, challonge_api_token):
        if Tournament.TESTING:
            self.full_url = f"{tourney_url}"
        else:
            self.full_url = f"{Tournament.CHALLONGE_SUBDOMAIN}-{tourney_url}"
        challonge.set_credentials('theshishi', challonge_api_token)
        self.challonge_tournament = challonge.tournaments.show(self.full_url, include_participants=1, include_matches=1)
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

        To see details about any team, do `>t team <team-name>`
        To see details about a player, do `>t player <player-name>` (again, you can @mention)
        To leave your team, do `>t leave`. If you are a captain, doing this will disband the whole team!
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
                if _p.nick:
                    team_players.append(_p.nick)
                else:
                    team_players.append(_p.name)
            except commands.MemberNotFound:
                team_players.append(name)
        if ctx.author.nick:
            captain = ctx.author.nick
        else:
            captain = ctx.author.name
        _team = Team(team_name, captain, *team_players)
        print(team_players)

        # Update / create Players
        for _player_name in _team.players:
            try:
                print(_player_name)
                member = await self.member_converter.convert(ctx, _player_name)
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

        # Register the team on Challonge
        participant = challonge.participants.create(self.full_url,  _team.name)
        _team.challonge_id = participant["id"]

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
                # Remove the team from challonge
                challonge.participants.destroy(self.full_url, _team.challonge_id)
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

    #TODO needs to be adjusted to just pull next match from challonge and start it. Also this won't be needed for the league.
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

    #TODO Needs to be adjusted to be usable automatically after get_played_matches parses the RaT API
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

    @tasks.loop(hours=1)
    async def get_played_matches(self):
        # what matches are we looking for (with in-game nicknames)
        _participants_ids_to_names = {p['participant']['id']: p['participant']['name'] for p in self.challonge_tournament['participants']}
        _scheduled_matches_as_ids = [(match['match']['player1_id'], match['match']['player2_id']) for match in self.challonge_tournament['matches']]
        # [((team1_name, team1_challonge_id), (team2_name, team2_challonge_id)), (different two teams), ...]
        _scheduled_matches = [((_participants_ids_to_names[p1_id], p1_id), (_participants_ids_to_names[p2_id], p2_id)) for p1_id, p2_id in _scheduled_matches_as_ids]
        # get in-game nicks of registered teams
        # frozenset is set, but can't be changed (immutable) and thus can be used as a dict key (a.k.a is hashable - list isn't)
        ingame_nicks = {frozenset([self.players_db.find_first("name", name).ingame_name for name in team.players]): team.name for team in self.teams_db.db}
        # load played matches
        _matches = json.loads(requests.get("http://mww.sonicrat.org/api/").text)
        # dict {[frozenset of tuples of player (nicks, teamID) that have played]: match}
        player_nicks = {frozenset([(player['Name'], player['TeamID']) for player in match['players']]): match for match in _matches}
        # MATCH PARSING
        # take one match
        print(f'parsing matches.')
        team1, team2 = None, None
        for players_in_a_match, match in player_nicks.items():
            # go through each player in the match (MWW)
            for nick, teamID in players_in_a_match:
                # if it's the first one, find out if they're registered for the tournament
                if (team1 and team2) is None:
                    for nick_list in ingame_nicks:
                        if nick in nick_list:
                            # if we find the team player is registered with, all other nick in the match have to belong either to that team
                            #   or to the one they are playing against (pulled from challonge).
                            # Try and get the nick list for the second team in the scheduled match
                            for _team1, _team2 in _scheduled_matches:
                                if _team1[0] == ingame_nicks[nick_list]:
                                    print(f'found team 1: ', _team1[0])
                                    for nick_list_2, _team in ingame_nicks.items():
                                        if _team == _team2[0]:
                                            print('found team 2: ', _team2[0])
                                            # We found the scheduled match and have lists of nicks in both teams
                                            # (team_name, team_challonge_id, MWW_match_team_ID, {set of player nicks})
                                            team1 = (_team1[0], _team1[1], teamID, nick_list)
                                            if team1[2] == 1:       # pokud v MWW je team1 == 1, tak team2 = 2; jinak 1
                                                team2 = (_team2[0], _team2[1], 2, nick_list_2)
                                            elif team1[2] == 2:
                                                team2 = (_team2[0], _team2[1], 1, nick_list_2)
                                            break
                                    break
                            break
                    # if it was the first one and we already did not get any results from the parsing above (e.g. player not registered), we are done
                    if (team1 and team2) is None:
                        team1, team2 = None, None
                        break
                # if they are not the first player that's being parsed, then they have to belong to one of the teams.
                else:
                    if teamID == team1[2]:
                        if nick in team1[3]:
                            continue
                    elif nick in team2[3]:
                        continue
                    # if not, we move on to the next team
                    else:
                        team1, team2 = None, None
                        break
            # if at some point the asserts were broken, then go to next team
            if (team1 and team2) is None:
                continue

            # If we get here, then the match is the one played for the league
            # Check the winner
            if match['winner'] == team1[2]:
                winner = team1
            elif match['winner'] == team2[2]:
                winner = team2
            # Set the challonge match
            # We need a challonge match ID for that!
            # use _participant_names_to_IDs to code team names back to their challonge IDs then find the match with both of them.
            _team1_id, _team2_id = None, None
            for _id, _team_name in _participants_ids_to_names.items():
                if _team_name == team1[0]:
                    _team1_id = _id
                elif _team_name == team2[0]:
                    _team2_id = _id
            for _challonge_match in self.challonge_tournament['matches']:
                if (_challonge_match['match']['player1_id'] == _team1_id or _challonge_match['match']['player1_id'] == _team2_id) and \
                    (_challonge_match['match']['player2_id'] == _team1_id or _challonge_match['match']['player2_id'] == _team2_id):
                    challonge.matches.update(self.full_url, _challonge_match['match']['id'], scores_csv='1-1', winner_id=str(winner[1]))



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
        self.challonge_id = None

    def team_info(self):
        send_string = f'Team {self.name}:\n'
        send_string += f'Players: '
        for player in self.players:
            send_string += f'\n -> {player}'
        send_string += f'\nCaptain: {self.captain}'
        return send_string


class Match:
    def __init__(self, match_id):
        self.id = match_id
        self.team1 = None
        self.team1_players = None
        self.team2 = None
        self.team2_players = None
        self.winner = None



# Extension thingie
def setup(bot):
    tournament = Tournament(bot.tournament_id, bot.challonge_api_token)
    bot.add_cog(tournament)
    bot.add_cog(tournament.betting)
