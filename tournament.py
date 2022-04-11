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
            return Team(dct['name'], dct['captain'], *dct['players'], challonge_id=dct['challonge_id'])
        elif 'discord_id' in dct.keys():
            player = Player(dct['name'])
            player.ingame_name = dct['ingame_name']
            player.team = dct['team']
            player.discord_id = dct['discord_id']
            return player
        return dct

    @staticmethod
    def _encoder(o):
        if isinstance(o, Player):
            return {'name': o.name,
                    'ingame_name': o.ingame_name,
                    'team': o.team,
                    'discord_id': o.discord_id
                    }
        elif isinstance(o, Team):
            return {'name': o.name,
                    'captain': o.captain,
                    'players': list(o.players),
                    'challonge_id': o.challonge_id
                    }
        return json.JSONEncoder().default(o)


class Tournament(commands.Cog):
    CHALLONGE_SUBDOMAIN = "9d7a92ca1e0988a11ef9d7ab"
    TESTING = False

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
        self.registration_open = False
        self.registration_date = None
        # Betting disabled for now
        # self.betting = Betting(self)
        self.bets_open = False
        self.date = None
        self.info = f"""Next tournament date: Unknown
Registration status: -
"""

    @staticmethod
    # small method to make sure we don't have issues with nicks vs. names on discord
    def _get_discord_nick(ctx):
        if not ctx.author.nick:
            return ctx.author.name
        else:
            return ctx.author.nick

    @commands.command()
    async def register(self, ctx, ingame_name):
        """
        Register a player.

        :param ctx:
        :param ingame_name:
        :return:
        """
        # Check if the user is already registered
        try:
            self.players_db.find_first("discord_id", ctx.author.id)
            self.players_db.find_first("name", self._get_discord_nick(ctx))
            self.players_db.find_first("ingame_name", ingame_name)
            await ctx.send(f'{ctx.author.mention}, you are already registered!')
            return
        except KeyError:
            pass

        # create the player and save him into the database.
        self.players_db.db.append(Player(self._get_discord_nick(ctx), ingame_name=ingame_name, discord_id=ctx.author.id))
        self.players_db.save()
        await ctx.send(f"{ctx.author.mention}, you have been registered successfully.")

    @commands.group(aliases=['t'], invoke_without_command=True, ignore_extra=False)
    async def team(self, ctx, team_name):
        """
        Command group for calling team-related commands. Can be called by itself to show info about a team.

        :param ctx:
        :param team_name:
        :return:
        """
        try:
            _team = self.teams_db.find_first("name", team_name)
            player_names = []
            for player_id in _team.players:
                _p = self.players_db.find_first("discord_id", player_id)
                player_names.append((_p.name, _p.ingame_name))
            captain = self.players_db.find_first("discord_id", _team.captain)
            send_string = f"Team {_team.name}:\n" \
                          f"Players:\n"
            for player in player_names:
                send_string += f"-> {player[0]} ({player[1]})\n"
            send_string += f'Captain: {captain.name} ({captain.ingame_name})'
            await ctx.send(send_string)
        except KeyError:
            await ctx.send(f"Team {team_name} has not been found.")

    @team.command(name='register')
    async def team_register(self, ctx, team_name, *players):
        """
        Register a team for the tournament.

        :param team_name:
        :param players:
        :return:
        """
        try:
            self.teams_db.find_first('name', team_name)
            await ctx.send(f'Error in team registration: Team with name {team_name} already exists.')
            return True
        except KeyError:
            pass
        team_players = []
        players = list(players)
        players.append(self._get_discord_nick(ctx))
        for name in players:
            try:
                _p = await self.member_converter.convert(ctx, name)
                _player = self.players_db.find_first("discord_id", _p.id)
                team_players.append(_p.id)
                _player.team = team_name
            except commands.MemberNotFound:
                await ctx.send(f"Error while parsing player names for team registration.")
            except KeyError:
                await ctx.send(f"Cannot register the team. {_p.mention} is not registered yet as a player.")
        # Register the team on challonge
        _team = Team(team_name, ctx.author.id, *team_players)
        participant = challonge.participants.create(self.full_url, _team.name)
        _team.challonge_id = participant["id"]

        self.teams_db.db.append(_team)
        self.teams_db.save()
        self.players_db.save()
        await ctx.send(f'Team {team_name} has been registered successfully.')

    @team.command(name='leave')
    async def team_leave(self, ctx):
        """
        Leave the team you're currently registered with. If you are a captain, the team will be disbanded.
        :param ctx:
        :return:
        """
        try:
            _player = self.players_db.find_first("discord_id", ctx.author.id)
            _team = self.teams_db.find_first("name", _player.team)
        except KeyError:
            await ctx.send("Error while trying to leave a team.")
            return True

        _player.team = None
        _team.players.remove(_player.discord_id)
        if _team.captain == _player.discord_id:
            self.teams_db.db.remove(_team)
            # Remove the team from challonge
            challonge.participants.destroy(self.full_url, _team.challonge_id)
            await ctx.send(f"{ctx.author.mention}, as you were the captain of the team, the whole team {_team.name} has been disbanded.")
        else:
            await ctx.send(f"{ctx.author.mention}, you have left team {_team.name} successfully.")
        self.players_db.save()
        self.teams_db.save()

    @tasks.loop(hours=1)
    async def get_played_matches(self):
        # what matches are we looking for (with in-game nicknames)
        _participants_ids_to_names = {p['participant']['id']: p['participant']['name'] for p in self.challonge_tournament['participants']}
        _scheduled_matches_as_ids = [(match['match']['player1_id'], match['match']['player2_id']) for match in self.challonge_tournament['matches']]
        # [((team1_name, team1_challonge_id), (team2_name, team2_challonge_id)), (different two teams), ...]
        _scheduled_matches = [((_participants_ids_to_names[p1_id], p1_id), (_participants_ids_to_names[p2_id], p2_id)) for p1_id, p2_id in _scheduled_matches_as_ids]
        # get in-game nicks of registered teams
        # frozenset is set, but can't be changed (immutable) and thus can be used as a dict key (a.k.a is hashable - list isn't)
        ingame_nicks = {frozenset([self.players_db.find_first("discord_id", discord_id).ingame_name for discord_id in team.players]): team.name for team in self.teams_db.db}
        # load played matches
        _matches = json.loads(requests.get("http://mww.sonicrat.org/api/").text)
        # dict {[frozenset of tuples of player (nicks, teamID) that have played]: match}
        player_nicks = {frozenset([(player['Name'], player['TeamID']) for player in match['players']]): match for match in _matches}
        # MATCH PARSING
        # take one match
        print(f'Parsing matches.')
        team1, team2 = None, None
        for players_in_a_match, match in player_nicks.items():
            # go through each player in the match (MWW)
            for nick, teamID in players_in_a_match:
                # if it's the first one, find out if they're registered for the tournament
                if (team1 and team2) is None:
                    print(f'Parsing first team')
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
                    print(f'Parsing another player.')
                    if teamID == team1[2]:
                        if nick in team1[3]:
                            continue
                    elif nick in team2[3]:
                        continue
                    # if not, we move on to the next team
                    elif not (nick in team1[3] or nick in team2[3]):
                        print(f'Failed!')
                        team1, team2 = None, None
                        break
            # if at some point the asserts were broken, then go to next team
            if (team1 and team2) is None:
                continue

            # If we get here, then the match is the one played for the league
            # Check the winner
            print('Found the match!')
            if match['winner'] == team1[2]:
                winner = team1
                print(f'Winner: {team1[0]}')
            elif match['winner'] == team2[2]:
                winner = team2
                print(f'Winner: {team2[0]}')
            # Set the challonge match
            # We need a challonge match ID for that!
            # use _participant_names_to_IDs to code team names back to their challonge IDs then find the match with both of them.
            _team1_id, _team2_id = None, None
            for _id, _team_name in _participants_ids_to_names.items():
                if _team_name == team1[0]:
                    _team1_id = _id
                elif _team_name == team2[0]:
                    _team2_id = _id
            print(f'Challonge IDs of teams: {_team1_id}, {_team2_id}')
            for _challonge_match in self.challonge_tournament['matches']:
                print(f'Looking for the match between those.')
                if (_challonge_match['match']['player1_id'] == _team1_id or _challonge_match['match']['player1_id'] == _team2_id) and \
                    (_challonge_match['match']['player2_id'] == _team1_id or _challonge_match['match']['player2_id'] == _team2_id):
                    print(f'Found the match, trying to update...')
                    challonge.matches.update(self.full_url, _challonge_match['match']['id'], scores_csv='1-1', winner_id=str(winner[1]))


# BETTING IS NOT UPDATED, DONT USE
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
    def __init__(self, name, ingame_name=None, team=None, discord_id=None):
        self.name = name
        self.ingame_name = ingame_name
        self.team = team
        self.discord_id = discord_id


class Team:
    def __init__(self, name, captain, *args, challonge_id=None):
        self.name = name
        self.captain = captain
        self.players = set()
        for person in args:
            self.players.add(person)
        self.players.add(captain)
        self.challonge_id = challonge_id


# Extension thingie
def setup(bot):
    tournament = Tournament(bot.tournament_id, bot.challonge_api_token)
    bot.add_cog(tournament)
    # Betting not used at the moment
    # bot.add_cog(tournament.betting)
