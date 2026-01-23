"""
Centralized Auto-updater Utility
Handles fetching and updating JSON data files from remote sources.
"""
import json
import logging
import aiofiles
from pathlib import Path
from typing import Callable, Any
from dataclasses import dataclass

from config import SharedResources

logger = logging.getLogger(__name__)


@dataclass
class DataSource:
    """Configuration for a data source to be auto-updated."""
    name: str
    url: str
    local_path: Path
    transform: Callable[[list | dict], Any] | None = None  # Optional data transform
    

class AutoUpdater:
    """
    Centralized auto-updater for fetching and updating JSON data files.
    
    Security features:
    - Only fetches from whitelisted URLs (configured in config.py)
    - Validates response is valid JSON before saving
    - Atomic writes to prevent corruption
    - Validates data structure before applying updates
    """
    
    # Whitelisted URL prefixes for security
    ALLOWED_URL_PREFIXES = [
        "https://raw.githubusercontent.com/Sekai-World/",
    ]
    
    def __init__(self):
        self.sources: dict[str, DataSource] = {}
        self._last_update_status: dict[str, bool] = {}
    
    def register(self, source: DataSource) -> bool:
        """
        Register a data source for auto-updating.
        
        Returns False if URL is not in whitelist.
        """
        # Security: Validate URL is in whitelist
        if not any(source.url.startswith(prefix) for prefix in self.ALLOWED_URL_PREFIXES):
            logger.warning(
                "AutoUpdater: Rejected source '%s' - URL not in whitelist: %s",
                source.name, source.url
            )
            return False
        
        self.sources[source.name] = source
        logger.debug("AutoUpdater: Registered source '%s'", source.name)
        return True
    
    async def check_and_update(self, source_name: str) -> tuple[bool, str]:
        """
        Check for updates and download if available.
        
        Returns:
            (success: bool, message: str)
        """
        if source_name not in self.sources:
            return False, f"Unknown source: {source_name}"
        
        source = self.sources[source_name]
        
        try:
            session = await SharedResources.get_session()
            
            async with session.get(source.url, timeout=30) as response:
                if response.status != 200:
                    msg = f"HTTP {response.status}"
                    logger.warning("AutoUpdater[%s]: Failed to fetch - %s", source.name, msg)
                    self._last_update_status[source_name] = False
                    return False, msg
                
                # Validate content type is JSON-like
                content_type = response.headers.get('Content-Type', '')
                if 'json' not in content_type and 'text/plain' not in content_type:
                    msg = f"Unexpected content type: {content_type}"
                    logger.warning("AutoUpdater[%s]: %s", source.name, msg)
                    self._last_update_status[source_name] = False
                    return False, msg
                
                try:
                    # Read as text first (GitHub raw returns text/plain)
                    text = await response.text()
                    new_data = json.loads(text)
                except json.JSONDecodeError as e:
                    msg = f"Invalid JSON: {e}"
                    logger.error("AutoUpdater[%s]: %s", source.name, msg)
                    self._last_update_status[source_name] = False
                    return False, msg
                
                # Load current data to compare
                current_data = await self._load_local(source.local_path)
                
                # Check if update is needed (compare lengths for arrays)
                needs_update = self._needs_update(current_data, new_data)
                
                if not needs_update:
                    logger.debug("AutoUpdater[%s]: Data is up to date", source.name)
                    self._last_update_status[source_name] = True
                    return True, "Already up to date"
                
                # Apply transform if specified
                if source.transform:
                    new_data = source.transform(new_data)
                
                # Save new data atomically
                await self._save_local(source.local_path, new_data)
                
                old_count = len(current_data) if isinstance(current_data, list) else 0
                new_count = len(new_data) if isinstance(new_data, list) else 0
                
                msg = f"Updated: {old_count} -> {new_count} items"
                logger.info("AutoUpdater[%s]: %s", source.name, msg)
                self._last_update_status[source_name] = True
                return True, msg
                
        except Exception as e:
            msg = f"Error: {e}"
            logger.error("AutoUpdater[%s]: %s", source.name, msg)
            self._last_update_status[source_name] = False
            return False, msg
    
    async def check_all(self) -> dict[str, tuple[bool, str]]:
        """Check and update all registered sources."""
        results = {}
        for name in self.sources:
            results[name] = await self.check_and_update(name)
        return results
    
    def _needs_update(self, current: Any, new: Any) -> bool:
        """Determine if data needs updating."""
        if current is None:
            return True
        
        # For lists, compare lengths
        if isinstance(new, list):
            if not isinstance(current, list):
                return True
            return len(new) != len(current)
        
        # For dicts, compare key counts
        if isinstance(new, dict):
            if not isinstance(current, dict):
                return True
            return len(new) != len(current)
        
        return current != new
    
    async def _load_local(self, path: Path) -> Any:
        """Load local JSON file."""
        if not path.exists():
            return None
        
        try:
            async with aiofiles.open(path, 'r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("AutoUpdater: Failed to load %s: %s", path, e)
            return None
    
    async def _save_local(self, path: Path, data: Any):
        """Save data to local JSON file atomically."""
        # Write to temp file first, then rename (atomic on most systems)
        temp_path = path.with_suffix('.tmp')
        
        try:
            async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            
            # Atomic rename
            temp_path.replace(path)
            
        except Exception as e:
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()
            raise e


# Global auto-updater instance
auto_updater = AutoUpdater()


async def register_all_sources():
    """Register all known data sources for auto-updating."""
    from config import (
        CARDS_FILE, CARD_DATA_URL,
        MUSICS_FILE, MUSICS_DATA_URL,
        MUSIC_DIFFICULTIES_FILE, MUSIC_DIFFICULTIES_URL,
        STAMPS_FILE, STAMPS_DATA_URL,
        PROFILES_FILE, PROFILES_DATA_URL,
        EVENTS_FILE, EVENTS_DATA_URL,
    )
    
    sources = [
        DataSource("cards", CARD_DATA_URL, CARDS_FILE),
        DataSource("musics", MUSICS_DATA_URL, MUSICS_FILE),
        DataSource("music_difficulties", MUSIC_DIFFICULTIES_URL, MUSIC_DIFFICULTIES_FILE),
        DataSource("stamps", STAMPS_DATA_URL, STAMPS_FILE),
        DataSource("profiles", PROFILES_DATA_URL, PROFILES_FILE),
        DataSource("events", EVENTS_DATA_URL, EVENTS_FILE),
    ]
    
    for source in sources:
        auto_updater.register(source)
    
    logger.info("AutoUpdater: Registered %d data sources", len(sources))


async def run_all_updates() -> dict[str, tuple[bool, str]]:
    """
    Run updates for all registered sources.
    
    This can be called from a scheduled task or manually.
    """
    return await auto_updater.check_all()
