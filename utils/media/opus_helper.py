"""
Helper module to ensure the Opus audio codec (libopus) is loaded for Discord voice.
Supports Windows DLLs, Linux system libraries, and auto-download fallback for containers without root.
"""

import logging
import os
import sys
from pathlib import Path

import discord.opus

logger = logging.getLogger(__name__)


def ensure_opus_loaded() -> bool:
    """
    Ensure libopus is loaded into discord.opus.
    Returns True if loaded, False otherwise.
    """
    if discord.opus.is_loaded():
        return True

    # 1. Try discord.py default loader
    try:
        if discord.opus._load_default():
            logger.info("Opus loaded via discord default loader.")
            return True
    except Exception as e:
        logger.debug("Discord default opus loader failed: %s", e)

    # 2. Try candidate paths (Linux / Containers)
    if sys.platform != "win32":
        base_dir = Path(__file__).resolve().parent.parent.parent
        candidates = [
            "libopus.so.0",
            "libopus.so",
            "/usr/lib/x86_64-linux-gnu/libopus.so.0",
            "/usr/lib/x86_64-linux-gnu/libopus.so",
            "/usr/lib/libopus.so.0",
            "/usr/lib/libopus.so",
            "/usr/lib64/libopus.so.0",
            "/usr/local/lib/libopus.so.0",
            "/usr/local/lib/libopus.so",
            "/home/container/.local/lib/libopus.so.0",
            "/home/container/.local/lib/libopus.so",
            os.path.expanduser("~/.local/lib/libopus.so.0"),
            os.path.expanduser("~/.local/lib/libopus.so"),
            str(base_dir / "libopus.so"),
            str(base_dir / "libopus.so.0"),
        ]

        for path in candidates:
            try:
                discord.opus.load_opus(path)
                if discord.opus.is_loaded():
                    logger.info("Opus loaded successfully from: %s", path)
                    return True
            except Exception:
                continue

        # 3. Auto-download precompiled standalone libopus.so for Linux x86_64 if still missing
        target_file = base_dir / "libopus.so"
        if not target_file.exists():
            logger.info("Opus library not found. Downloading precompiled libopus.so for Linux...")
            try:
                import urllib.request

                url = (
                    "https://raw.githubusercontent.com/discord-java/opus-java/master/"
                    "natives/src/main/resources/natives/linux-x86-64/libopus.so"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "IchikaBot/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                if len(data) > 100_000:
                    with open(target_file, "wb") as f:
                        f.write(data)
                    logger.info("Downloaded libopus.so (%d bytes).", len(data))
            except Exception as e:
                logger.error("Failed to auto-download libopus.so: %s", e)

        if target_file.exists():
            try:
                discord.opus.load_opus(str(target_file))
                if discord.opus.is_loaded():
                    logger.info("Opus loaded successfully from %s", target_file)
                    return True
            except Exception as e:
                logger.error("Failed to load downloaded libopus.so: %s", e)

    return discord.opus.is_loaded()
