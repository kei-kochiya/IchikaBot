import discord
from discord.ext import commands
import os
import asyncio
import logging
from dotenv import load_dotenv
from config import SharedResources

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

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)


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
    """Finds and loads all cog files in the 'cogs' directory."""
    if not os.path.exists('./cogs'):
        logger.error("'cogs' directory not found.")
        return

    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                logger.info(f"Loaded extension: {filename}")
            except Exception as e:
                logger.error(f"Failed to load extension {filename}: {e}")


async def main():
    async with bot:
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