import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import logging
from dotenv import load_dotenv
from config import SharedResources
from utils import database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load the .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if TOKEN is None:
    logger.error("DISCORD_TOKEN not found in .env file.")
    exit()

# --- Default context/install tree -------------------------------------------
# Applies allowed_contexts and allowed_installs to ALL commands by default,
# enabling user-installed app support and group DM usage.
# Commands decorated with @app_commands.guild_only() still override this.
#
# NOTE: also enable "User Install" in Discord Developer Portal →
#       Your App → Installation → Installation Contexts
class DefaultContextTree(app_commands.CommandTree):
    def __init__(self, client, **kwargs):
        super().__init__(
            client,
            allowed_contexts=app_commands.AppCommandContext(
                guild=True,
                dm_channel=True,       # 1:1 DMs
                private_channel=True,  # Group DMs
            ),
            allowed_installs=app_commands.AppInstallationType(
                guild=True,  # Traditional server bot
                user=True,   # User-installable app
            ),
            **kwargs,
        )


# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None,
    tree_cls=DefaultContextTree,  # use our tree with default contexts
)


@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user.name}!')
    logger.info('--------------------------------')
    
    # Auto-sync slash commands on startup
    try:
        synced = await bot.tree.sync()
        logger.info(f'Auto-synced {len(synced)} slash command(s).')
    except Exception as e:
        logger.error(f'Failed to auto-sync commands: {e}')
    
    logger.info('Bot is ready.')


@bot.event
async def on_close():
    """Cleanup shared resources on bot shutdown."""
    logger.info("Bot shutting down, cleaning up resources...")
    await SharedResources.close_session()


# --- SYNC COMMAND ---
@bot.command()
async def sync(ctx):
    """Manually sync slash commands."""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Synced {len(synced)} command(s)!")
        logger.info(f"Synced {len(synced)} commands.")
    except Exception as e:
        await ctx.send(f"❌ Error syncing: {e}")
        logger.error(f"Sync error: {e}")


async def load_cogs():
    """Recursively finds and loads all cog files in the 'cogs' directory."""
    if not os.path.exists('./cogs'):
        logger.error("'cogs' directory not found.")
        return

    for root, dirs, files in os.walk('./cogs'):
        for filename in files:
            if filename.endswith('.py') and not filename.startswith('__'):
                # Convert path to module notation: cogs/voice/streaming.py -> cogs.voice.streaming
                relative_path = os.path.relpath(os.path.join(root, filename), '.')
                module_name = relative_path.replace(os.path.sep, '.')[:-3]
                
                try:
                    await bot.load_extension(module_name)
                    logger.info(f"Loaded extension: {module_name}")
                except Exception as e:
                    logger.error(f"Failed to load extension {module_name}: {e}")


async def main():
    async with bot:
        await database.init_db()
        await load_cogs()
        try:
            await bot.start(TOKEN)
        finally:
            await SharedResources.close_session()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")