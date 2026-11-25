"""Smoke tests & architectural invariants: cog lifecycle, permissions, help, and lazy imports."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord.ext import commands

from cogs.system.help import COMMAND_CATEGORIES, HelpCog
from cogs.voice.music_guess import MusicGuess


async def test_all_cogs_load_and_unload_cleanly(mock_bot, temp_db):
    cogs_dir = Path("cogs")
    assert cogs_dir.exists()

    loaded = []
    failed = []
    for root, _dirs, files in os.walk(cogs_dir):
        for filename in files:
            if filename.endswith(".py") and not filename.startswith("__"):
                rel = os.path.relpath(os.path.join(root, filename), ".")
                module = rel.replace(os.path.sep, ".")[:-3]
                try:
                    await mock_bot.load_extension(module)
                    loaded.append(module)
                except Exception as exc:
                    failed.append((module, str(exc)))

    assert not failed, f"Failed to load cogs: {failed}"
    assert len(loaded) >= 14

    for module in loaded:
        await mock_bot.unload_extension(module)


def test_startup_keeps_heavy_optional_modules_unloaded(tmp_path):
    """Guard the idle-RAM architecture: loading all cogs must not eagerly import heavy libs."""
    code = "\n".join(
        [
            "import asyncio, sys",
            "from pathlib import Path",
            "from utils.core import database",
            f"database.DB_FILE = Path({str(tmp_path / 'smoke.db')!r})",
            "import bot",
            "async def run():",
            "    await database.init_db()",
            "    await bot.load_cogs()",
            "    for ext in list(bot.bot.extensions):",
            "        await bot.bot.unload_extension(ext)",
            "    await database.close_db()",
            "asyncio.run(run())",
            "leaked = [m for m in ('openpyxl', 'httpx', 'mercapi', 'cryptography', 'msgpack', 'utils.pjsk.client', 'utils.pjsk.crypto', 'utils.pjsk.b30_render') if m in sys.modules]",
            "assert not leaked, f'Heavy modules loaded at startup: {leaked}'",
        ]
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


async def test_security_sensitive_commands_enforce_checks(mock_bot):
    from bot import bot

    # !sync must be owner-only
    sync_cmd = bot.get_command("sync")
    assert sync_cmd is not None and len(sync_cmd.checks) == 1
    ctx = MagicMock()
    ctx.bot.is_owner = AsyncMock(return_value=False)
    with pytest.raises(commands.NotOwner):
        await sync_cmd.checks[0](ctx)
    ctx.bot.is_owner = AsyncMock(return_value=True)
    assert await sync_cmd.checks[0](ctx) is True

    # Voice quiz commands must be guild-only (DMs have no voice channels)
    music = MusicGuess(mock_bot)
    assert music.slash_songguess.guild_only is True
    for cmd in (
        music.guess_music,
        music.guess_music_variant,
        music.guess_music_all,
        music.guess_music_all_variant,
    ):
        assert len(cmd.checks) == 1


async def test_help_command_flows_and_formatting(mock_bot, make_interaction, make_ctx):
    cog = HelpCog(mock_bot)

    # Category lookup ignores case/spaces; unknown falls back to overview
    assert cog.create_help_embed("card & gacha").title == "Card & Gacha"
    assert cog.create_help_embed("CardOfTheDay").title == "Card of the Day"
    assert cog.create_help_embed("no such thing").title == "Danh sách lệnh"

    # No dangling placeholders in any category
    for cat in COMMAND_CATEGORIES:
        for field in cog.create_help_embed(cat).fields:
            assert "`-`" not in field.value and " / " not in field.value

    # Slash & prefix invocations work end to end
    interaction = make_interaction()
    await cog.help_slash.callback(cog, interaction, category=None)
    overview = interaction.last_reply["embed"]
    values = " ".join(f.value for f in overview.fields)
    for expected in ("`/gacha pull`", "`/songguess`", "`!sgv`", "`/mercari`"):
        assert expected in values
    assert "!sync" not in values
    assert "`/mercarisearch`" not in values

    ctx = make_ctx()
    await cog.help_prefix.callback(cog, ctx, category="Mercari")
    assert ctx.last_reply["embed"].title == "Mercari"
