import asyncio
import contextlib
import gc
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from config import SharedResources
from utils.core import database

# Load the .env file first: it can set LOG_LEVEL
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configure logging (LOG_LEVEL: DEBUG, INFO, WARNING or ERROR; INFO if unset or unknown)
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").strip().upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


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
                dm_channel=True,  # 1:1 DMs
                private_channel=True,  # Group DMs
            ),
            allowed_installs=app_commands.AppInstallationType(
                guild=True,  # Traditional server bot
                user=True,  # User-installable app
            ),
            **kwargs,
        )

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Last-resort handler for every slash command.

        Most commands defer() first, so an unhandled exception would otherwise leave the
        user looking at "is thinking..." forever. Per-command handlers run before this one
        and answer the failures they expect (permissions, cooldowns), so a check failure is
        only answered here if nobody has replied yet.
        """
        if isinstance(error, app_commands.CheckFailure):
            if not interaction.response.is_done():
                await send_ephemeral(interaction, _check_failure_message(error))
            return

        name = interaction.command.qualified_name if interaction.command else "unknown"
        original = getattr(error, "original", error)
        logger.error("Error in slash command /%s", name, exc_info=original)
        await send_ephemeral(interaction, GENERIC_ERROR_MESSAGE)


GENERIC_ERROR_MESSAGE = "Lệnh này gặp lỗi. Bạn thử lại sau ít phút nhé."


def _check_failure_message(error: app_commands.CheckFailure) -> str:
    if isinstance(error, app_commands.CommandOnCooldown):
        return f"Bạn thao tác nhanh quá. Thử lại sau **{error.retry_after:.0f} giây** nhé."
    if isinstance(error, app_commands.NoPrivateMessage):
        return "Lệnh này chỉ dùng được trong server."
    if isinstance(error, app_commands.BotMissingPermissions):
        return "Bot chưa có đủ quyền trong kênh này. Nhờ admin cấp quyền rồi thử lại nhé."
    return "Bạn không có quyền dùng lệnh này."


async def send_ephemeral(interaction: discord.Interaction, content: str) -> None:
    """Reply privately whether or not the interaction was already answered or deferred."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)
    except discord.HTTPException:
        pass  # interaction expired (15 min) or channel gone: nothing more we can do


# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!", "-"),
    intents=intents,
    help_command=None,
    max_messages=100,
    tree_cls=DefaultContextTree,  # use our tree with default contexts
)


_commands_synced = False


@bot.event
async def on_ready():
    global _commands_synced
    logger.info(f"Logged in as {bot.user.name}!")
    logger.info("--------------------------------")

    # Auto-sync slash commands once per process. on_ready fires again after every gateway
    # reconnect, and re-syncing each time wastes API calls (and rate limit) for no change.
    if not _commands_synced:
        try:
            synced = await bot.tree.sync()
            _commands_synced = True
            logger.info(f"Auto-synced {len(synced)} slash command(s).")
        except Exception as e:
            logger.error(f"Failed to auto-sync commands: {e}")

    logger.info("Bot is ready.")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Skip command processing for game guesses so discord.py doesn't look for command 'g'
    content_lower = message.content.lower()
    if content_lower == "-g" or content_lower.startswith("-g "):
        return

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Global error handler for prefix commands."""
    if isinstance(error, commands.CommandNotFound):
        return  # Silently ignore invalid or unrecognized commands

    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("Lệnh này chỉ dùng được trong server.")
        return

    if isinstance(error, commands.CheckFailure):
        return  # e.g. owner-only commands used by someone else: ignore quietly

    if isinstance(error, commands.CommandInvokeError):
        # A real bug inside the command: keep the traceback and tell the user it failed
        logger.error("Error in command %s", ctx.command, exc_info=error.original)
        with contextlib.suppress(discord.HTTPException):
            await ctx.send(GENERIC_ERROR_MESSAGE)
        return

    logger.error("Command error in %s: %s", ctx.command, error)


# --- SYNC COMMAND ---
@bot.command()
@commands.is_owner()  # a global sync is rate limited by Discord: never let anyone trigger it
async def sync(ctx):
    """Manually sync slash commands."""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Đã đồng bộ {len(synced)} lệnh slash.")
        logger.info(f"Synced {len(synced)} commands.")
    except Exception as e:
        await ctx.send(f"Đồng bộ thất bại: {e}")
        logger.error(f"Sync error: {e}")


async def load_cogs():
    """Recursively finds and loads all cog files in the 'cogs' directory."""
    if not os.path.exists("./cogs"):
        logger.error("'cogs' directory not found.")
        return

    for root, _dirs, files in os.walk("./cogs"):
        for filename in files:
            if filename.endswith(".py") and not filename.startswith("__"):
                # Convert path to module notation: cogs/voice/music_guess.py -> cogs.voice.music_guess
                relative_path = os.path.relpath(os.path.join(root, filename), ".")
                module_name = relative_path.replace(os.path.sep, ".")[:-3]

                try:
                    await bot.load_extension(module_name)
                    logger.info(f"Loaded extension: {module_name}")
                except Exception as e:
                    logger.error(f"Failed to load extension {module_name}: {e}")


async def main():
    if not TOKEN:
        logger.error("DISCORD_TOKEN not found in .env file.")
        return

    async with bot:
        await database.init_db()
        await load_cogs()
        gc.collect()
        try:
            await bot.start(TOKEN)
        finally:
            await SharedResources.close_session()
            await database.close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
