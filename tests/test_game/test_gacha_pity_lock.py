import asyncio
import gc

import pytest

from cogs.game.gacha import GachaCog


@pytest.fixture
def slow_pity_store(mock_bot, monkeypatch):
    """A GachaCog whose pity storage yields to the event loop, like a real database."""
    cog = GachaCog(mock_bot)
    store = {1: 0, 2: 0}

    async def get_pity(user_id):
        value = store[user_id]
        await asyncio.sleep(0.01)
        return value

    async def set_pity(user_id, count):
        await asyncio.sleep(0.01)
        store[user_id] = count

    monkeypatch.setattr(cog, "get_user_pity", get_pity)
    monkeypatch.setattr(cog, "update_user_pity", set_pity)
    # Never a 4-star: every pull simply adds one pity
    monkeypatch.setattr(cog, "_simulate_single_pull", lambda pity, guaranteed=False: ({}, pity + 1))
    return cog, store


@pytest.mark.asyncio
async def test_concurrent_pulls_by_one_user_all_count(slow_pity_store):
    cog, store = slow_pity_store

    await asyncio.gather(*(cog.pull_one_card(1) for _ in range(5)))

    assert store[1] == 5  # without the per-user lock every task reads 0 and writes 1


@pytest.mark.asyncio
async def test_different_users_do_not_block_each_other(slow_pity_store):
    cog, store = slow_pity_store

    await asyncio.gather(cog.pull_one_card(1), cog.pull_one_card(2))

    assert store == {1: 1, 2: 1}
    assert cog._pity_lock(1) is not cog._pity_lock(2)


@pytest.mark.asyncio
async def test_locks_are_released_when_unused(slow_pity_store):
    cog, _ = slow_pity_store

    await asyncio.gather(*(cog.pull_one_card(uid) for uid in (1, 2)))
    gc.collect()

    assert len(cog._pity_locks) == 0  # no per-user lock is kept alive forever
