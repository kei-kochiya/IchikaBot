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

user_settings  (per-user preferences, e.g. setting='guess_mode')
    user_id  INTEGER
    setting  TEXT
    value    TEXT
    PRIMARY KEY (user_id, setting)

Migration
---------
On first init, if the legacy JSON files exist their data is imported
and a migration-complete marker is written to guild_settings so the
import never runs again.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path

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

        CREATE TABLE IF NOT EXISTS user_settings (
            user_id  INTEGER NOT NULL,
            setting  TEXT    NOT NULL,
            value    TEXT    NOT NULL,
            PRIMARY KEY (user_id, setting)
        );

        CREATE TABLE IF NOT EXISTS pjsk_links (
            discord_id   INTEGER NOT NULL,
            region       TEXT    NOT NULL,
            pjsk_user_id INTEGER NOT NULL,
            pjsk_name    TEXT    NOT NULL DEFAULT '',
            linked_at    REAL    NOT NULL,
            synced_at    REAL    NOT NULL DEFAULT 0,
            PRIMARY KEY (discord_id, region),
            UNIQUE (region, pjsk_user_id)
        );

        CREATE TABLE IF NOT EXISTS pjsk_clears (
            discord_id  INTEGER NOT NULL,
            region      TEXT    NOT NULL,
            music_id    INTEGER NOT NULL,
            difficulty  TEXT    NOT NULL,
            clear_state TEXT    NOT NULL,
            PRIMARY KEY (discord_id, region, music_id, difficulty)
        );

        CREATE TABLE IF NOT EXISTS pjsk_recovery (
            discord_id   INTEGER NOT NULL,
            region       TEXT    NOT NULL,
            pjsk_user_id INTEGER NOT NULL,
            credential   TEXT    NOT NULL,
            created_at   REAL    NOT NULL,
            PRIMARY KEY (discord_id, region)
        );

        CREATE TABLE IF NOT EXISTS pjsk_bot_accounts (
            region     TEXT    PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            credential TEXT    NOT NULL,
            updated_at REAL    NOT NULL
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

    all_ok = True

    # ── Pity migration ─────────────────────────────────────────────────────
    if PITY_FILE.exists():
        try:
            data: dict = json.loads(PITY_FILE.read_text(encoding="utf-8"))
            if data:
                await conn.executemany(
                    "INSERT OR REPLACE INTO pity (user_id, count) VALUES (?, ?)",
                    ((int(uid), int(count)) for uid, count in data.items()),
                )
                await conn.commit()
                logger.info("DB migration: imported %d pity entries from %s", len(data), PITY_FILE)
        except Exception as exc:
            all_ok = False
            await conn.rollback()
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
            await conn.commit()
            logger.info("DB migration: imported %d birthday settings", len(data))
        except Exception as exc:
            all_ok = False
            await conn.rollback()
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
            await conn.commit()
            logger.info("DB migration: imported %d cotd guild configs", len(data))
        except Exception as exc:
            all_ok = False
            await conn.rollback()
            logger.warning("DB migration: cotd settings import failed: %s", exc)

    if all_ok:
        await conn.execute(
            "INSERT OR REPLACE INTO guild_settings (guild_id, setting, value) VALUES (0, '_migrated', '1')"
        )
        await conn.commit()
        logger.info("DB migration: complete.")
    else:
        logger.warning("DB migration: skipped _migrated marker due to import errors; will retry.")


# ── Connection management ──────────────────────────────────────────────────────
#
# A single long-lived connection is reused for every query.  Opening a fresh
# aiosqlite connection per call spawns a worker thread and re-opens the file each
# time (~1-4 ms of pure overhead per query); aiosqlite already serialises work on
# the connection's own thread, so sharing one connection is safe.  Writes are
# serialized through _write_lock so multi-statement transactions never interleave
# and errors/cancellations roll back cleanly.

_conn: aiosqlite.Connection | None = None
_conn_path: Path | None = None
_conn_lock = asyncio.Lock()
_write_lock = asyncio.Lock()

PJSK_RECOVERY_TTL_SECONDS = 72 * 3600  # auto-prune orphaned recovery credentials after 72h


async def _connect() -> aiosqlite.Connection:
    pending = aiosqlite.connect(DB_FILE)
    # The worker thread is non-daemon by default; make sure a missed close_db()
    # (crash, KeyboardInterrupt) can never keep the interpreter from exiting.
    worker = getattr(pending, "_thread", pending)
    if hasattr(worker, "daemon"):
        worker.daemon = True
    conn = await pending
    try:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        # Safe with WAL: a crash can lose the last transaction but never corrupts the file.
        await conn.execute("PRAGMA synchronous=NORMAL")
    except BaseException:
        await conn.close()
        raise
    return conn


async def _close_unlocked() -> None:
    global _conn, _conn_path
    conn, _conn, _conn_path = _conn, None, None
    if conn is not None:
        await conn.close()


async def _get_conn() -> aiosqlite.Connection:
    """Return the shared connection, (re)opening it if it is missing or DB_FILE changed."""
    global _conn, _conn_path
    target = Path(DB_FILE)
    if _conn is not None and _conn_path == target:
        return _conn
    async with _conn_lock:
        if _conn is not None and _conn_path != target:
            await _close_unlocked()
        if _conn is None:
            _conn = await _connect()
            _conn_path = target
        return _conn


async def close_db() -> None:
    """Close the shared connection.  Call on bot shutdown."""
    async with _write_lock, _conn_lock:
        await _close_unlocked()


@asynccontextmanager
async def _write_tx() -> AsyncIterator[aiosqlite.Connection]:
    """Serialize writes on the shared connection with atomic commit/rollback."""
    async with _write_lock:
        conn = await _get_conn()
        try:
            yield conn
            await conn.commit()
        except BaseException:
            with contextlib.suppress(Exception):
                await conn.rollback()
            raise


# ── Public API — lifecycle ─────────────────────────────────────────────────────


async def init_db() -> None:
    """Create tables, run one-time JSON migration, and prune stale recovery rows."""
    import time

    async with _write_lock:
        conn = await _get_conn()
        await _create_tables(conn)
        await _migrate_json(conn)
        cutoff = time.time() - PJSK_RECOVERY_TTL_SECONDS
        await conn.execute("DELETE FROM pjsk_recovery WHERE created_at < ?", (cutoff,))
        await conn.commit()
    logger.info("DB: initialised at %s", DB_FILE)


# ── Public API — pity ──────────────────────────────────────────────────────────


async def get_pity(user_id: int) -> int:
    """Return the user's current pity count (0 if not found)."""
    conn = await _get_conn()
    async with conn.execute("SELECT count FROM pity WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
        return int(row["count"]) if row else 0


async def set_pity(user_id: int, count: int) -> None:
    """Upsert the user's pity count."""
    async with _write_tx() as conn:
        await conn.execute(
            "INSERT INTO pity (user_id, count) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET count=excluded.count",
            (user_id, count),
        )


# ── Public API — guild settings ────────────────────────────────────────────────


async def get_setting(guild_id: int, setting: str) -> str | None:
    """Return the value for (guild_id, setting), or None if absent."""
    conn = await _get_conn()
    async with conn.execute(
        "SELECT value FROM guild_settings WHERE guild_id=? AND setting=?",
        (guild_id, setting),
    ) as cur:
        row = await cur.fetchone()
        return row["value"] if row else None


async def set_setting(guild_id: int, setting: str, value: str) -> None:
    """Upsert a guild setting."""
    async with _write_tx() as conn:
        await conn.execute(
            "INSERT INTO guild_settings (guild_id, setting, value) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, setting) DO UPDATE SET value=excluded.value",
            (guild_id, setting, value),
        )


async def set_settings(guild_id: int, values: dict[str, str]) -> None:
    """Upsert several settings for one guild in a single transaction."""
    if not values:
        return
    async with _write_tx() as conn:
        await conn.executemany(
            "INSERT INTO guild_settings (guild_id, setting, value) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, setting) DO UPDATE SET value=excluded.value",
            [(guild_id, setting, value) for setting, value in values.items()],
        )


async def delete_setting(guild_id: int, setting: str) -> None:
    """Delete a guild setting (no-op if not found)."""
    async with _write_tx() as conn:
        await conn.execute(
            "DELETE FROM guild_settings WHERE guild_id=? AND setting=?",
            (guild_id, setting),
        )


async def delete_settings(guild_id: int, settings: Iterable[str]) -> None:
    """Delete several settings for one guild in a single atomic transaction."""
    keys = list(settings)
    if not keys:
        return
    async with _write_tx() as conn:
        await conn.executemany(
            "DELETE FROM guild_settings WHERE guild_id=? AND setting=?",
            [(guild_id, setting) for setting in keys],
        )


async def get_all_settings(setting: str) -> dict[int, str]:
    """Return {guild_id: value} for all guilds that have the given setting key."""
    conn = await _get_conn()
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
    conn = await _get_conn()
    async with conn.execute(
        "SELECT guild_id, setting, value FROM guild_settings "
        "WHERE substr(setting, 1, ?) = ? AND guild_id != 0",
        (len(prefix), prefix),
    ) as cur:
        rows = await cur.fetchall()

    result: dict[int, dict[str, str]] = {}
    p_len = len(prefix)
    for row in rows:
        gid = int(row["guild_id"])
        key = row["setting"][p_len:]  # strip prefix: "cotd_channel_id" → "channel_id"
        result.setdefault(gid, {})[key] = row["value"]
    return result


# ── Public API — user settings ─────────────────────────────────────────────────


async def get_user_setting(user_id: int, setting: str) -> str | None:
    """Return a user's preference value, or None if they never set it."""
    conn = await _get_conn()
    async with conn.execute(
        "SELECT value FROM user_settings WHERE user_id=? AND setting=?",
        (user_id, setting),
    ) as cur:
        row = await cur.fetchone()
        return row["value"] if row else None


async def set_user_setting(user_id: int, setting: str, value: str) -> None:
    """Upsert a user's preference."""
    async with _write_tx() as conn:
        await conn.execute(
            "INSERT INTO user_settings (user_id, setting, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, setting) DO UPDATE SET value=excluded.value",
            (user_id, setting, value),
        )


# ── Public API — PJSK account linking, clears & transfer recovery ──────────────


async def get_pjsk_link(discord_id: int, region: str) -> dict | None:
    """Return the linked PJSK account row for (discord_id, region), or None."""
    conn = await _get_conn()
    async with conn.execute(
        "SELECT discord_id, region, pjsk_user_id, pjsk_name, linked_at, synced_at "
        "FROM pjsk_links WHERE discord_id=? AND region=?",
        (discord_id, region.lower()),
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_pjsk_link_by_game_id(region: str, pjsk_user_id: int) -> dict | None:
    """Return the link row owning *pjsk_user_id* on *region*, or None."""
    conn = await _get_conn()
    async with conn.execute(
        "SELECT discord_id, region, pjsk_user_id, pjsk_name, linked_at, synced_at "
        "FROM pjsk_links WHERE region=? AND pjsk_user_id=?",
        (region.lower(), pjsk_user_id),
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def set_pjsk_link(
    discord_id: int,
    region: str,
    pjsk_user_id: int,
    pjsk_name: str,
    linked_at: float,
) -> None:
    """Link or update a user's PJSK account for *region*.

    If the user re-links to a different PJSK user ID, stale clears and synced_at are wiped.
    """
    reg = region.lower()
    safe_name = " ".join((pjsk_name or "").split())[:32]
    async with _write_tx() as conn:
        async with conn.execute(
            "SELECT pjsk_user_id FROM pjsk_links WHERE discord_id=? AND region=?",
            (discord_id, reg),
        ) as cur:
            prev = await cur.fetchone()

        changed_account = prev is None or int(prev["pjsk_user_id"]) != int(pjsk_user_id)
        if changed_account:
            await conn.execute(
                "DELETE FROM pjsk_clears WHERE discord_id=? AND region=?",
                (discord_id, reg),
            )
        await conn.execute(
            "INSERT INTO pjsk_links (discord_id, region, pjsk_user_id, pjsk_name, linked_at, synced_at) "
            "VALUES (?, ?, ?, ?, ?, 0) "
            "ON CONFLICT(discord_id, region) DO UPDATE SET "
            "pjsk_user_id=excluded.pjsk_user_id, pjsk_name=excluded.pjsk_name, "
            "linked_at=excluded.linked_at, "
            "synced_at=CASE WHEN pjsk_links.pjsk_user_id != excluded.pjsk_user_id "
            "THEN 0 ELSE pjsk_links.synced_at END",
            (discord_id, reg, pjsk_user_id, safe_name, linked_at),
        )


async def delete_pjsk_link(discord_id: int, region: str) -> bool:
    """Unlink a user's PJSK account and wipe their saved clears & recovery credentials."""
    reg = region.lower()
    async with _write_tx() as conn:
        cur = await conn.execute(
            "DELETE FROM pjsk_links WHERE discord_id=? AND region=?",
            (discord_id, reg),
        )
        await conn.execute(
            "DELETE FROM pjsk_clears WHERE discord_id=? AND region=?",
            (discord_id, reg),
        )
        await conn.execute(
            "DELETE FROM pjsk_recovery WHERE discord_id=? AND region=?",
            (discord_id, reg),
        )
        return cur.rowcount > 0


async def replace_pjsk_clears(
    discord_id: int,
    region: str,
    clears: dict[tuple[int, str], str],
    *,
    pjsk_name: str | None = None,
    synced_at: float = 0.0,
    expected_pjsk_user_id: int | None = None,
) -> bool:
    """Atomically replace a user's saved PJSK music clear states for *region*.

    When *expected_pjsk_user_id* is provided, verifies the link row still exists and
    matches that game ID before writing (preventing cross-account corruption if the user
    unlinked or re-linked while a sync/import was in flight). Returns True if saved.
    """
    reg = region.lower()
    safe_name = " ".join(pjsk_name.split())[:32] if pjsk_name is not None else None
    async with _write_tx() as conn:
        if expected_pjsk_user_id is not None:
            async with conn.execute(
                "SELECT pjsk_user_id FROM pjsk_links WHERE discord_id=? AND region=?",
                (discord_id, reg),
            ) as cur:
                row = await cur.fetchone()
            if row is None or int(row["pjsk_user_id"]) != int(expected_pjsk_user_id):
                return False

        await conn.execute(
            "DELETE FROM pjsk_clears WHERE discord_id=? AND region=?",
            (discord_id, reg),
        )
        if clears:
            await conn.executemany(
                "INSERT INTO pjsk_clears (discord_id, region, music_id, difficulty, clear_state) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    (discord_id, reg, int(mid), diff.lower(), state.lower())
                    for (mid, diff), state in clears.items()
                ),
            )
        if safe_name is not None:
            await conn.execute(
                "UPDATE pjsk_links SET pjsk_name=?, synced_at=? WHERE discord_id=? AND region=?",
                (safe_name, synced_at, discord_id, reg),
            )
        elif synced_at:
            await conn.execute(
                "UPDATE pjsk_links SET synced_at=? WHERE discord_id=? AND region=?",
                (synced_at, discord_id, reg),
            )
        return True


async def get_pjsk_clears(discord_id: int, region: str) -> dict[tuple[int, str], str]:
    """Return {(music_id, difficulty): clear_state} saved for (discord_id, region)."""
    conn = await _get_conn()
    async with conn.execute(
        "SELECT music_id, difficulty, clear_state FROM pjsk_clears WHERE discord_id=? AND region=?",
        (discord_id, region.lower()),
    ) as cur:
        rows = await cur.fetchall()
    return {(int(r["music_id"]), str(r["difficulty"])): str(r["clear_state"]) for r in rows}


async def prune_expired_pjsk_recovery(max_age_seconds: float = PJSK_RECOVERY_TTL_SECONDS) -> int:
    """Delete orphaned crash-recovery credentials older than *max_age_seconds*."""
    import time

    cutoff = time.time() - max_age_seconds
    async with _write_tx() as conn:
        cur = await conn.execute("DELETE FROM pjsk_recovery WHERE created_at < ?", (cutoff,))
        return cur.rowcount


async def save_pjsk_recovery(
    discord_id: int, region: str, pjsk_user_id: int, credential: str, created_at: float
) -> None:
    """Temporarily persist an in-flight transfer credential until the new Transfer ID is sent."""
    import time

    cutoff = time.time() - PJSK_RECOVERY_TTL_SECONDS
    async with _write_tx() as conn:
        await conn.execute("DELETE FROM pjsk_recovery WHERE created_at < ?", (cutoff,))
        await conn.execute(
            "INSERT INTO pjsk_recovery (discord_id, region, pjsk_user_id, credential, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(discord_id, region) DO UPDATE SET "
            "pjsk_user_id=excluded.pjsk_user_id, credential=excluded.credential, "
            "created_at=excluded.created_at",
            (discord_id, region.lower(), pjsk_user_id, credential, created_at),
        )


async def get_pjsk_recovery(discord_id: int, region: str) -> dict | None:
    """Fetch a non-expired crash-recovery credential for (discord_id, region), if any."""
    import time

    conn = await _get_conn()
    async with conn.execute(
        "SELECT discord_id, region, pjsk_user_id, credential, created_at "
        "FROM pjsk_recovery WHERE discord_id=? AND region=?",
        (discord_id, region.lower()),
    ) as cur:
        row = await cur.fetchone()
        if not row:
            return None
        if (time.time() - float(row["created_at"])) > PJSK_RECOVERY_TTL_SECONDS:
            return None
        return dict(row)


async def delete_pjsk_recovery(discord_id: int, region: str) -> None:
    """Wipe a temporary crash-recovery credential once the new Transfer ID is delivered."""
    async with _write_tx() as conn:
        await conn.execute(
            "DELETE FROM pjsk_recovery WHERE discord_id=? AND region=?",
            (discord_id, region.lower()),
        )


async def get_pjsk_bot_account(region: str) -> dict | None:
    """Return the bot's persisted anonymous PJSK account for *region*, or None."""
    conn = await _get_conn()
    async with conn.execute(
        "SELECT region, user_id, credential, updated_at FROM pjsk_bot_accounts WHERE region=?",
        (region.lower(),),
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def set_pjsk_bot_account(
    region: str, user_id: int, credential: str, updated_at: float | None = None
) -> None:
    """Persist the bot's anonymous PJSK account credential for *region*."""
    import time

    ts = time.time() if updated_at is None else updated_at
    async with _write_tx() as conn:
        await conn.execute(
            "INSERT INTO pjsk_bot_accounts (region, user_id, credential, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(region) DO UPDATE SET "
            "user_id=excluded.user_id, credential=excluded.credential, updated_at=excluded.updated_at",
            (region.lower(), user_id, credential, ts),
        )


async def delete_pjsk_bot_account(region: str) -> None:
    """Delete a stale anonymous bot account so the client can register a fresh one."""
    async with _write_tx() as conn:
        await conn.execute("DELETE FROM pjsk_bot_accounts WHERE region=?", (region.lower(),))
