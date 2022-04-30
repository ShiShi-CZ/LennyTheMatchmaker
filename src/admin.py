from discord.ext import commands
import challonge


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(aliases=['a'], hidden=True)
    @commands.is_owner()
    async def admin(self, ctx):
        pass

    @admin.command()
    async def reload(self, ctx):
        self.bot.reload_extension('tournament')
        self.bot.reload_extension('admin')
        await ctx.send(f'Extensions successfully reloaded.')

    @admin.command()
    async def delete(self, ctx):
        t = self.bot.get_cog('Tournament')
        t.teams_db.db = []
        t.teams_db.save()
        t.players_db.db = []
        t.players_db.save()
        await ctx.send('Database deleted.')

    @admin.command(name='load')
    async def load_extension(self, ctx, name):
        try:
            self.bot.load_extension(name)
            await ctx.send('Extension loaded successfully.')
        except commands.ExtensionError as e:
            await ctx.send(f'Extension loading error: {e}')

    @admin.command(name='parse')
    async def force_match_parsing(self, _):
        for cog_name, cog in self.bot.cogs.items():
            if cog_name == 'Tournament':
                await cog.get_played_matches.__call__()

    @admin.command(name='killteam')
    async def kill_team(self, ctx, team_name):
        t = self.bot.get_cog('Tournament')
        try:
            team = t.teams_db.find_first('name', team_name)
        except KeyError:
            await ctx.send(f"{ctx.author.mention}, team {team_name} doesn't exist.")
            return False

        t.teams_db.db.remove(team)
        # destroy the team in challonge - we need to log in for that
        challonge.set_credentials('theshishi', self.bot.challonge_api_token)
        challonge.participants.destroy(t.full_url, team.challonge_id)

        # delete the team from everyone's profiles
        team_players = [t.players_db.find_first("discord_id", _id) for _id in team.players]
        for player in team_players:
            player.team = None
            d_user = await commands.MemberConverter().convert(ctx, str(player.discord_id))
            # destroy the role
            for role in d_user.roles:
                if role.id == team.discord_role:
                    await role.delete(reason="Team unregistered.")
        t.teams_db.save()
        t.players_db.save()
        await ctx.send(f"The team {team_name} has been unregistered.")



def setup(bot):
    bot.add_cog(Admin(bot))
