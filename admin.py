from discord.ext import commands


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


def setup(bot):
    bot.add_cog(Admin(bot))
