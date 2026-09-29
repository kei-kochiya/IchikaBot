"""
Webstore Reminder Cog - Daily 10 PM VN time @everyone ping for the Pjsekai webstore.

DISCARDABLE: To remove this feature entirely, delete this file.
No database settings, no commands — it is self-contained.
"""

import logging
from datetime import time
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — edit these constants to change behaviour
# ---------------------------------------------------------------------------
_GUILD_ID: int = 1408094401280081933
_FIRE_TIME: time = time(hour=22, minute=0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
_MESSAGE: str = "Đến giờ vào web lấy roll\nhttps://pjsekai.sega.jp/webstore"
# ---------------------------------------------------------------------------


class WebstoreReminderCog(commands.Cog):
    """Sends a daily @everyone reminder to the first available text channel in the target guild."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.reminder_task.start()
        logger.info("WebstoreReminder: Scheduled daily reminder at %s VN time.", _FIRE_TIME)

    async def cog_unload(self) -> None:
        self.reminder_task.cancel()

    # ------------------------------------------------------------------
    # Scheduled task
    # ------------------------------------------------------------------

    @tasks.loop(time=_FIRE_TIME)
    async def reminder_task(self) -> None:
        guild = self.bot.get_guild(_GUILD_ID)
        if guild is None:
            logger.warning(
                "WebstoreReminder: Guild %d not found (bot may not be a member).", _GUILD_ID
            )
            return

        # Find the first text channel the bot can send messages to
        channel = next(
            (ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages),
            None,
        )
        if channel is None:
            logger.warning(
                "WebstoreReminder: No writable text channel found in guild %d.", _GUILD_ID
            )
            return

        try:
            await channel.send(f"@everyone {_MESSAGE}")
            logger.info("WebstoreReminder: Sent reminder to #%s (%d).", channel.name, channel.id)
        except discord.HTTPException as exc:
            logger.error("WebstoreReminder: Failed to send message: %s", exc)

    @reminder_task.before_loop
    async def before_reminder(self) -> None:
        await self.bot.wait_until_ready()

    @reminder_task.error
    async def on_reminder_error(self, error: Exception) -> None:
        logger.error("WebstoreReminder: Exception in background loop: %s", error, exc_info=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WebstoreReminderCog(bot))
