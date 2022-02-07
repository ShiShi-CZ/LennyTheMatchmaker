from discord.ext import commands


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(aliases=['a'])
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


def setup(bot):
    bot.add_cog(Admin(bot))