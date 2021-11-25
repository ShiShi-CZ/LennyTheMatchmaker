import discord
import logging
from os import environ

logging.basicConfig(level=logging.DEBUG)
REACTION_EMOJI = "✅"    # :white_check_mark:
MATCHMAKING_ROLE_ID = int(environ['MATCHMAKING_ROLE_ID'])   # @matchmaking
GUILD_ID = int(environ['GUILD_ID'])   # Wizard Wars Reborn discord server
CHANNEL_ID = int(environ['CHANNEL_ID'])     # Channel where the message to react to is located
REACTION_MESSAGE = int(environ['REACTION_MESSAGE'])    # Message where the reacts should be
BOT_TOKEN = environ['LENNYTOKEN']


class Lenny(discord.Client):
    async def on_ready(self):
        print('Ready!')
        self.guild = self.get_guild(GUILD_ID)
        self.message = await self.guild.get_channel(CHANNEL_ID).fetch_message(REACTION_MESSAGE)
        self.matchmaking_role = self.guild.get_role(MATCHMAKING_ROLE_ID)
        self.matchmaking_users = set()

        # Read reactions on the message at startup
        for reaction in self.message.reactions:
            if reaction.emoji == REACTION_EMOJI:
                print('Done')
                users = await reaction.users().flatten()
                self.matchmaking_users = {user.id for user in users}


intents = discord.Intents.all()
lenny = Lenny(intents=intents, activity=discord.Game('Magicka: Wizard Wars'))


@lenny.event
async def on_raw_reaction_add(data):
    if data.message_id == REACTION_MESSAGE and data.emoji.name == REACTION_EMOJI:
        lenny.matchmaking_users.add(data.user_id)


@lenny.event
async def on_raw_reaction_remove(data):
    if data.message_id == REACTION_MESSAGE and data.emoji == REACTION_EMOJI:
        lenny.matchmaking_users.discard(data.user_id)      # discard doesn't raise an error if by any chance the user isn't in set


@lenny.event
async def on_member_update(_, member):
    if (member.id in lenny.matchmaking_users) and member.activity.name == 'Magicka: Wizard Wars' and lenny.matchmaking_role not in member.roles:
        await member.add_roles(lenny.matchmaking_role, reason='( ͡° ل͜ ͡°)')

    if member.id in lenny.matchmaking_users and member.activity.name != 'Magicka: Wizard Wars' and lenny.matchmaking_role in member.roles:
        await member.remove_roles(lenny.matchmaking_role, reason='( ͠° ͟ʖ ͡°)')

lenny.run(BOT_TOKEN)
