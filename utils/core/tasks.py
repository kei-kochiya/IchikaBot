"""
tasks.py — Small helpers for fire-and-forget asyncio work.

``asyncio.create_task`` only keeps a *weak* reference to the task, so a task that nobody
awaits can be garbage collected before it finishes.  ``spawn`` keeps a strong reference
until the task is done.
"""

import asyncio
import contextlib
from collections.abc import Coroutine
from typing import Any

import discord

_background_tasks: set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """Run *coro* in the background, keeping it alive until it completes."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _react(message: discord.Message, emoji: str) -> None:
    # Reactions are cosmetic: a deleted message or missing permission must not raise
    # "Task exception was never retrieved" noise.
    with contextlib.suppress(discord.HTTPException):
        await message.add_reaction(emoji)


def react_in_background(message: discord.Message, emoji: str) -> asyncio.Task:
    """Add a reaction without blocking the caller or surfacing HTTP errors."""
    return spawn(_react(message, emoji))
