"""Helpers for fire-and-forget asyncio tasks that hold strong references and log failures."""

import asyncio
import contextlib
import logging
from collections.abc import Coroutine
from typing import Any

import discord

logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task] = set()


def _on_task_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Unhandled exception in background task %s", task.get_name(), exc_info=exc)


def spawn(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """Run *coro* in the background, keeping it alive until it completes."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_on_task_done)
    return task


async def _react(message: discord.Message, emoji: str) -> None:
    # Reactions are cosmetic: a deleted message or missing permission must not raise
    # "Task exception was never retrieved" noise.
    with contextlib.suppress(discord.HTTPException):
        await message.add_reaction(emoji)


def react_in_background(message: discord.Message, emoji: str) -> asyncio.Task:
    """Add a reaction without blocking the caller or surfacing HTTP errors."""
    return spawn(_react(message, emoji))
