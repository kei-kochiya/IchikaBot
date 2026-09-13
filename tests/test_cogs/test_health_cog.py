import discord
import pytest

from cogs.system.health import HealthCog, format_uptime, get_memory_usage_mb


def test_format_uptime():
    assert format_uptime(45) == "45s"
    assert format_uptime(125) == "2m 5s"
    assert format_uptime(3665) == "1h 1m 5s"
    assert format_uptime(90065) == "1d 1h 1m 5s"


def test_memory_usage():
    mem = get_memory_usage_mb()
    assert isinstance(mem, float)
    assert mem >= 0.0


@pytest.mark.asyncio
async def test_health_cog_embed(mock_bot, temp_db):
    cog = HealthCog(mock_bot)
    db_latency = await cog._check_database_latency()
    assert db_latency >= 0.0

    embed = cog.create_health_embed(db_latency)
    assert isinstance(embed, discord.Embed)
    assert "IchikaBot System Health" in embed.title
    assert len(embed.fields) >= 5
