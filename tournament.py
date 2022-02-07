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
        self.registration_open = False
        self.registration_date = None
        self.date = '<t:1645981200:f> (<t:1645981200:R>)'
        self.info = f"""Next tournament date: {self.date}
Registration status: Closed
Registration open date: Unknown

Once more details and format will be known, the registration open date will be set as well.
If you have questions/ideas/whatever, message <@132912730649788416>."""

    @commands.group(invoke_without_command=True, aliases=['t'], ignore_extra=False)
    async def tournament(self, ctx):
        """A command group, grouping all other subcommands. If used without subcommands, sends tournament info."""
        await ctx.send(self.info)
        return True

    @tournament.command()
    async def register(self, ctx, team_name, *args):
        """Registers a team and it's players.

        :param ctx: Command context
        :param team_name: Name of the team
        :param args: Variable amount of persons to register in the team
        :return: True
        """
        # if not REGISTRATION_ON:
        #     await ctx.send(f'The registration hasn\'t been opened yet!')
        #     return True
        try:
            self.teams_db.find_first('name', team_name)
            await ctx.send(f'Error in team registration: Team with name {team_name} already exists.')
            return True
        except KeyError:
            pass
        players = []
        for name in args:
            try:
                _p = await commands.MemberConverter().convert(ctx, name)
                players.append(_p.name)
            except commands.MemberNotFound:
                players.append(name)
        _team = Team(team_name, ctx.author.name, *players)
        print(players)

        # Update / create Players
        for _player_name in _team.players:
            try:
                member = await commands.MemberConverter().convert(ctx, _player_name)
                try:
                    _player = next((p for p in self.players_db.db if p.discord_id == member.id))
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
                except StopIteration:
                    _player = Player(member.name)
                    _player.discord_id = member.id
                    _player.team = team_name
                    self.players_db.db.append(_player)
                    continue
            except commands.MemberNotFound:
                pass
            try:
                _player = next((p for p in self.players_db.db if p.name == _player_name))
                _player.team = team_name
            except StopIteration:
                _player = Player(_player_name)
                _player.team = team_name
                self.players_db.db.append(_player)
        self.players_db.save()
        self.teams_db.db.append(_team)
        self.teams_db.save()

    @tournament.command(name='leave')
    async def unregister(self, ctx):
        """Unregisters the command caller from his team."""
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
        try:
            _team = self.teams_db.find_first('name', team_name)
            await ctx.send(_team.team_info())
        except KeyError:
            await ctx.send(f'{team_name} has not been found.')

    @tournament.command(name='player')
    async def player(self, ctx, player_name):
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
        send_string += f'Previous achievements:'
        for achiev in self.achievements:
            send_string += f'\n{achiev}'
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
    bot.add_cog(Tournament())
