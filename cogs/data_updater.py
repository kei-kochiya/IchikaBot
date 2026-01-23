"""
Data Updater Cog - Centralized scheduled updates for all game data files.
This replaces the individual check_updates tasks in each cog.
"""
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging

from utils.autoupdater import auto_updater, register_all_sources, run_all_updates
from config import CARD_UPDATE_INTERVAL_HOURS

logger = logging.getLogger(__name__)


class DataUpdaterCog(commands.Cog):
    """Centralized cog for scheduled data updates."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.initialized = False
    
    async def cog_load(self):
        """Initialize and start the update task."""
        # Register all data sources
        await register_all_sources()
        self.initialized = True
        
        # Start the scheduled task
        self.scheduled_update.start()
        logger.info("DataUpdater: Started with %d registered sources", len(auto_updater.sources))
    
    async def cog_unload(self):
        """Stop the update task."""
        self.scheduled_update.cancel()
    
    @tasks.loop(hours=CARD_UPDATE_INTERVAL_HOURS)
    async def scheduled_update(self):
        """Run updates for all registered data sources."""
        logger.info("DataUpdater: Running scheduled update check...")
        
        results = await run_all_updates()
        
        # Log summary
        updated = sum(1 for success, msg in results.values() if success and "Updated" in msg)
        failed = sum(1 for success, _ in results.values() if not success)
        
        if updated > 0:
            logger.info("DataUpdater: %d sources updated, %d failed", updated, failed)
        else:
            logger.debug("DataUpdater: All sources up to date")
        
        # Notify cogs to reload data if there were updates
        if updated > 0:
            await self._notify_cogs_to_reload(results)
    
    @scheduled_update.before_loop
    async def before_scheduled_update(self):
        """Wait for bot to be ready."""
        await self.bot.wait_until_ready()
    
    async def _notify_cogs_to_reload(self, results: dict):
        """Notify relevant cogs to reload their data after updates."""
        # Map source names to cog names
        source_to_cog = {
            'cards': 'CardCog',
            'musics': 'SongsCog',
            'music_difficulties': 'SongsCog',
            'stamps': 'StampsCog',
            'profiles': 'ProfileCog',
            'events': 'EventsCog',
        }
        
        cogs_to_reload = set()
        for source_name, (success, msg) in results.items():
            if success and "Updated" in msg:
                cog_name = source_to_cog.get(source_name)
                if cog_name:
                    cogs_to_reload.add(cog_name)
        
        for cog_name in cogs_to_reload:
            cog = self.bot.get_cog(cog_name)
            if cog and hasattr(cog, 'load_data'):
                try:
                    # Call synchronous load_data
                    cog.load_data()
                    logger.info("DataUpdater: Reloaded data for %s", cog_name)
                except Exception as e:
                    logger.error("DataUpdater: Failed to reload %s: %s", cog_name, e)
    
    @app_commands.command(name="update_data", description="Kiểm tra và cập nhật dữ liệu game (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def manual_update(self, interaction: discord.Interaction):
        """Manually trigger data update check."""
        await interaction.response.defer(ephemeral=True)
        
        results = await run_all_updates()
        
        # Build response
        lines = []
        for source_name, (success, msg) in results.items():
            status = "✅" if success else "❌"
            lines.append(f"{status} **{source_name}**: {msg}")
        
        embed = discord.Embed(
            title="📊 Data Update Results",
            description="\n".join(lines),
            color=discord.Color.green() if all(s for s, _ in results.values()) else discord.Color.orange()
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @manual_update.error
    async def update_error(self, interaction: discord.Interaction, error):
        """Handle permission errors."""
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Bạn cần quyền **Administrator** để sử dụng lệnh này.",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(DataUpdaterCog(bot))
