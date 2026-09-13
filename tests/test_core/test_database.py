import pytest
from utils.core import database


@pytest.mark.asyncio
async def test_pity_crud(temp_db):
    user_id = 123456789
    # Initial pity is 0
    initial_pity = await database.get_pity(user_id)
    assert initial_pity == 0

    # Set pity to 50
    await database.set_pity(user_id, 50)
    assert await database.get_pity(user_id) == 50

    # Update pity to 90 (upsert test)
    await database.set_pity(user_id, 90)
    assert await database.get_pity(user_id) == 90


@pytest.mark.asyncio
async def test_guild_settings_crud(temp_db):
    guild_id = 987654321
    setting = "birthday_channel"
    value = "1122334455"

    # Initial setting is None
    assert await database.get_setting(guild_id, setting) is None

    # Set setting
    await database.set_setting(guild_id, setting, value)
    assert await database.get_setting(guild_id, setting) == value

    # Update setting
    new_value = "9988776655"
    await database.set_setting(guild_id, setting, new_value)
    assert await database.get_setting(guild_id, setting) == new_value

    # Delete setting
    await database.delete_setting(guild_id, setting)
    assert await database.get_setting(guild_id, setting) is None


@pytest.mark.asyncio
async def test_get_all_settings(temp_db):
    setting = "birthday_channel"
    await database.set_setting(1001, setting, "ch_1")
    await database.set_setting(1002, setting, "ch_2")
    await database.set_setting(1003, "other_setting", "foo")

    all_bday = await database.get_all_settings(setting)
    assert len(all_bday) == 2
    assert all_bday[1001] == "ch_1"
    assert all_bday[1002] == "ch_2"
    assert 1003 not in all_bday


@pytest.mark.asyncio
async def test_get_all_settings_prefix(temp_db):
    prefix = "cotd_"
    guild_id = 2001

    await database.set_setting(guild_id, "cotd_channel_id", "ch_cotd")
    await database.set_setting(guild_id, "cotd_interval_hours", "24")
    await database.set_setting(guild_id, "cotd_last_post_ts", "1700000000")
    await database.set_setting(guild_id, "other_channel", "123")

    results = await database.get_all_settings_prefix(prefix)
    assert guild_id in results
    assert results[guild_id]["channel_id"] == "ch_cotd"
    assert results[guild_id]["interval_hours"] == "24"
    assert results[guild_id]["last_post_ts"] == "1700000000"
    assert "other_channel" not in results[guild_id]
