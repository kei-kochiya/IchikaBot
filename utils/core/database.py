"""
database.py — Async SQLite layer for IchikaBot.

Replaces flat JSON files:
  - pityData.json          → table: pity
  - birthdaySettings.json  → table: guild_settings (setting='birthday_channel')
  - cardOfDaySettings.json → table: guild_settings (setting='cotd_*')

Tables
------
pity
    user_id  INTEGER PRIMARY KEY
    count    INTEGER NOT NULL DEFAULT 0

guild_settings
    guild_id INTEGER
    setting  TEXT
    value    TEXT
    PRIMARY KEY (guild_id, setting)

Migration
---------
On first init, if the legacy JSON files exist their data is imported
and a migration-complete marker is written to guild_settings so the
import never runs again.
"""

import json
import logging

import aiosqlite

from config import BIRTHDAY_SETTINGS_FILE, CARD_OF_DAY_SETTINGS_FILE, DB_FILE, PITY_FILE

logger = logging.getLogger(__name__)


# ── Internal: table creation ───────────────────────────────────────────────────


async def _create_tables(conn: aiosqlite.Connection) -> None:
    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS pity (
            user_id  INTEGER PRIMARY KEY,
            count    INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER NOT NULL,
            setting  TEXT    NOT NULL,
            value    TEXT    NOT NULL,
            PRIMARY KEY (guild_id, setting)
        );
    """)
    await conn.commit()


async def _migrate_json(conn: aiosqlite.Connection) -> None:
    """Import legacy JSON files once, then mark migration as done."""

    # Check if already migrated
    async with conn.execute(
        "SELECT 1 FROM guild_settings WHERE guild_id=0 AND setting='_migrated'"
    ) as cur:
        if await cur.fetchone():
            return  # Already done

    # ── Pity migration ─────────────────────────────────────────────────────
    if PITY_FILE.exists():
        try:
            data: dict = json.loads(PITY_FILE.read_text(encoding="utf-8"))
            if data:
                await conn.executemany(
                    "INSERT OR REPLACE INTO pity (user_id, count) VALUES (?, ?)",
                    ((int(uid), int(count)) for uid, count in data.items()),
                )
                logger.info("DB migration: imported %d pity entries from %s", len(data), PITY_FILE)
        except Exception as exc:
            logger.warning("DB migration: pity import failed: %s", exc)

    # ── Birthday settings migration ────────────────────────────────────────
    if BIRTHDAY_SETTINGS_FILE.exists():
        try:
            data = json.loads(BIRTHDAY_SETTINGS_FILE.read_text(encoding="utf-8"))
            for guild_id_str, channel_id in data.items():
                await conn.execute(
                    "INSERT OR REPLACE INTO guild_settings (guild_id, setting, value) VALUES (?, ?, ?)",
                    (int(guild_id_str), "birthday_channel", str(channel_id)),
                )
            logger.info("DB migration: imported %d birthday settings", len(data))
        except Exception as exc:
            logger.warning("DB migration: birthday settings import failed: %s", exc)

    # ── Card-of-Day settings migration ────────────────────────────────────
    if CARD_OF_DAY_SETTINGS_FILE.exists():
        try:
            data = json.loads(CARD_OF_DAY_SETTINGS_FILE.read_text(encoding="utf-8"))
            for guild_id_str, cfg in data.items():
                gid = int(guild_id_str)
                for key in ("channel_id", "interval_hours", "last_post_ts"):
                    if key in cfg:
                        await conn.execute(
                            "INSERT OR REPLACE INTO guild_settings (guild_id, setting, value) VALUES (?, ?, ?)",
                            (gid, f"cotd_{key}", str(cfg[key])),
                        )
            logger.info("DB migration: imported %d cotd guild configs", len(data))
        except Exception as exc:
            logger.warning("DB migration: cotd settings import failed: %s", exc)

    # Mark migration complete
    await conn.execute(
        "INSERT OR REPLACE INTO guild_settings (guild_id, setting, value) VALUES (0, '_migrated', '1')"
    )
    await conn.commit()
    logger.info("DB migration: complete.")


# ── Public API — lifecycle ─────────────────────────────────────────────────────


async def init_db() -> None:
    """Create tables and run one-time JSON migration.  Call before loading cogs."""
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await _create_tables(conn)
        await _migrate_json(conn)
    logger.info("DB: initialised at %s", DB_FILE)


# ── Public API — pity ──────────────────────────────────────────────────────────


async def get_pity(user_id: int) -> int:
    """Return the user's current pity count (0 if not found)."""
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT count FROM pity WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return int(row["count"]) if row else 0


async def set_pity(user_id: int, count: int) -> None:
    """Upsert the user's pity count."""
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "INSERT INTO pity (user_id, count) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET count=excluded.count",
            (user_id, count),
        )
        await conn.commit()


# ── Public API — guild settings ────────────────────────────────────────────────


async def get_setting(guild_id: int, setting: str) -> str | None:
    """Return the value for (guild_id, setting), or None if absent."""
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT value FROM guild_settings WHERE guild_id=? AND setting=?",
            (guild_id, setting),
        ) as cur:
            row = await cur.fetchone()
            return row["value"] if row else None


async def set_setting(guild_id: int, setting: str, value: str) -> None:
    """Upsert a guild setting."""
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "INSERT INTO guild_settings (guild_id, setting, value) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, setting) DO UPDATE SET value=excluded.value",
            (guild_id, setting, value),
        )
        await conn.commit()


async def delete_setting(guild_id: int, setting: str) -> None:
    """Delete a guild setting (no-op if not found)."""
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "DELETE FROM guild_settings WHERE guild_id=? AND setting=?",
            (guild_id, setting),
        )
        await conn.commit()


async def get_all_settings(setting: str) -> dict[int, str]:
    """Return {guild_id: value} for all guilds that have the given setting key."""
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT guild_id, value FROM guild_settings WHERE setting=? AND guild_id != 0",
            (setting,),
        ) as cur:
            rows = await cur.fetchall()
            return {int(row["guild_id"]): row["value"] for row in rows}


async def get_all_settings_prefix(prefix: str) -> dict[int, dict[str, str]]:
    """
    Return {guild_id: {key_suffix: value}} for all settings whose key
    starts with *prefix*.  Used by CardOfDay which stores multiple keys
    per guild (cotd_channel_id, cotd_interval_hours, cotd_last_post_ts).
    """
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT guild_id, setting, value FROM guild_settings "
            "WHERE setting LIKE ? AND guild_id != 0",
            (f"{prefix}%",),
        ) as cur:
            rows = await cur.fetchall()

    result: dict[int, dict[str, str]] = {}
    p_len = len(prefix)
    for row in rows:
        gid = int(row["guild_id"])
        key = row["setting"][p_len:]  # strip prefix: "cotd_channel_id" → "channel_id"
        result.setdefault(gid, {})[key] = row["value"]
    return result
