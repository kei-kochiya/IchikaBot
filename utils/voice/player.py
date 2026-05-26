import asyncio
from collections import deque
from typing import Optional
import discord
from utils.voice.models import QueueEntry

class GuildPlayer:
    LOOP_OFF   = 0
    LOOP_TRACK = 1
    LOOP_QUEUE = 2
    LOOP_LABEL = {0: "Off", 1: "🔂 Track", 2: "🔁 Queue"}

    def __init__(self):
        self.queue:           deque  = deque()
        self.current:         Optional[QueueEntry]       = None
        self.vc:              Optional[discord.VoiceClient] = None
        self.text_channel:    Optional[discord.abc.Messageable] = None
        self.loop:            int   = self.LOOP_OFF
        self.volume:          float = 1.0          # 0.0–2.0
        self.play_task:       Optional[asyncio.Task] = None
        self.inactivity_task: Optional[asyncio.Task] = None
        self._skip_flag:      bool = False
        self._stop_flag:      bool = False
        # Persistent Now-Playing embed
        self.np_message:      Optional[discord.Message] = None
        self.np_view          = None

    @property
    def is_active(self) -> bool:
        return self.vc is not None and (
            self.vc.is_playing() or self.vc.is_paused()
        )

    def cancel_tasks(self):
        for t in (self.play_task, self.inactivity_task):
            if t and not t.done():
                t.cancel()

    def restart_inactivity(self, coro):
        if self.inactivity_task and not self.inactivity_task.done():
            self.inactivity_task.cancel()
        self.inactivity_task = asyncio.create_task(coro)
