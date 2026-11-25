import contextlib
import logging
import os
import random
import subprocess
import uuid
from pathlib import Path

from pydub import AudioSegment
from pydub.effects import speedup
from pydub.utils import get_prober_name

from config import SONG_CLIP_DURATION, SONG_SAFE_ZONE, TEMP_DIR

logger = logging.getLogger(__name__)

TEMP_CLIP_PREFIX = "temp_guess_clip_"

# Raw PCM format requested from ffmpeg for the extracted clip
_PCM_RATE = 44100
_PCM_CHANNELS = 2
_PCM_WIDTH = 2  # bytes per sample (s16le)
_MIN_AUDIO_BYTES = _PCM_RATE * _PCM_CHANNELS * _PCM_WIDTH  # 1 second

# Bounded in-memory cache of track durations: (path, size, mtime_ns) -> duration_ms
_DURATION_CACHE: dict[tuple[str, int, int], int] = {}
_DURATION_CACHE_LIMIT = 1024

_VARIANT_INFO = {
    "fast": ("Tua nhanh 1.5x", "atempo=1.5"),
    "slow": ("Tua chậm 0.75x", f"aresample={_PCM_RATE},asetrate={int(_PCM_RATE * 0.75)}"),
    "reverse": ("Phát ngược", "areverse"),
}


def _probe_duration_ms(file_path: str) -> int | None:
    """Return the track length in ms via ffprobe, or None if it can't be determined."""
    try:
        st = os.stat(file_path)
    except OSError:
        return None

    cache_key = (file_path, st.st_size, st.st_mtime_ns)
    cached = _DURATION_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        proc = subprocess.run(
            [
                get_prober_name(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
        duration_ms = int(float(proc.stdout.decode().strip()) * 1000)
        if duration_ms <= 0:
            return None
        if len(_DURATION_CACHE) >= _DURATION_CACHE_LIMIT:
            _DURATION_CACHE.clear()
        _DURATION_CACHE[cache_key] = duration_ms
        return duration_ms
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _extract_clip(file_path: str, start_ms: int, length_ms: int) -> AudioSegment | None:
    """
    Decode only [start, start + length) of the track.

    Seeking before decoding means a ~5 minute song costs one short ffmpeg run and a
    few MB of RAM instead of fully decoding the whole file into ~50 MB of PCM.
    """
    try:
        proc = subprocess.run(
            [
                AudioSegment.converter,
                "-v",
                "error",
                "-nostdin",
                "-ss",
                f"{start_ms / 1000:.3f}",
                "-t",
                f"{length_ms / 1000:.3f}",
                "-i",
                file_path,
                "-vn",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ar",
                str(_PCM_RATE),
                "-ac",
                str(_PCM_CHANNELS),
                "-",
            ],
            capture_output=True,
            timeout=60,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Fast clip extraction failed for %s: %s", file_path, e)
        return None

    if len(proc.stdout) < _MIN_AUDIO_BYTES:  # < 1 second of audio
        return None
    return AudioSegment(
        data=proc.stdout,
        sample_width=_PCM_WIDTH,
        frame_rate=_PCM_RATE,
        channels=_PCM_CHANNELS,
    )


def _pick_start(duration_ms: int) -> int:
    min_start = SONG_SAFE_ZONE
    max_start = duration_ms - SONG_SAFE_ZONE - SONG_CLIP_DURATION
    return random.randint(min_start, max_start) if min_start < max_start else 0


def _load_clip(file_path: str) -> AudioSegment | None:
    """Pick a random clip from the track, decoding as little audio as possible."""
    duration_ms = _probe_duration_ms(file_path)
    if duration_ms:
        clip = _extract_clip(file_path, _pick_start(duration_ms), SONG_CLIP_DURATION)
        if clip is not None:
            return clip

    # Bounded fallback when ffprobe fails: decode at most the first safe-zone + clip window
    # directly via ffmpeg with -nostdin and a strict timeout so bad files can never hang or
    # allocate ~50+ MB of full-track PCM. Take the tail so the intro safe zone is skipped.
    fallback_window_ms = SONG_SAFE_ZONE + SONG_CLIP_DURATION
    clip = _extract_clip(file_path, 0, fallback_window_ms)
    if clip is None:
        return None
    if len(clip) > SONG_CLIP_DURATION:
        clip = clip[len(clip) - SONG_CLIP_DURATION :]
    return clip if len(clip.raw_data) >= _MIN_AUDIO_BYTES else None


def _extract_variant_wav(
    file_path: str, start_ms: int, length_ms: int, audio_filter: str, dest: Path
) -> bool:
    """Extract and transform a clip directly to WAV in a single ffmpeg pass (C-speed)."""
    try:
        subprocess.run(
            [
                AudioSegment.converter,
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-ss",
                f"{start_ms / 1000:.3f}",
                "-t",
                f"{length_ms / 1000:.3f}",
                "-i",
                file_path,
                "-vn",
                "-af",
                audio_filter,
                "-acodec",
                "pcm_s16le",
                "-ar",
                str(_PCM_RATE),
                "-ac",
                str(_PCM_CHANNELS),
                str(dest),
            ],
            capture_output=True,
            timeout=60,
            check=True,
        )
        # Ensure at least ~1s of valid audio was written (44-byte WAV header + PCM)
        if dest.stat().st_size >= 44 + _MIN_AUDIO_BYTES:
            return True
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Direct variant extraction failed for %s: %s", file_path, e)

    with contextlib.suppress(OSError):
        dest.unlink(missing_ok=True)
    return False


def prepare_clip(file_path: str, variant: str | None = None) -> tuple[str | None, str | None]:
    """Prepare audio clip with optional effects."""
    temp_filename = TEMP_DIR / f"{TEMP_CLIP_PREFIX}{uuid.uuid4().hex}.wav"

    # Fast path for audio effects: let ffmpeg apply atempo/asetrate/areverse in C directly to WAV
    if variant in _VARIANT_INFO:
        effect_name, audio_filter = _VARIANT_INFO[variant]
        duration_ms = _probe_duration_ms(file_path)
        if duration_ms and _extract_variant_wav(
            file_path, _pick_start(duration_ms), SONG_CLIP_DURATION, audio_filter, temp_filename
        ):
            return str(temp_filename), effect_name

    clip = _load_clip(file_path)
    if clip is None:
        return None, None

    effect_name = "Bình thường"
    try:
        if variant == "fast":
            clip = speedup(clip, playback_speed=1.5)
            effect_name = "Tua nhanh 1.5x"
        elif variant == "slow":
            clip = clip._spawn(
                clip.raw_data, overrides={"frame_rate": int(clip.frame_rate * 0.75)}
            )
            effect_name = "Tua chậm 0.75x"
        elif variant == "reverse":
            clip = clip.reverse()
            effect_name = "Phát ngược"

        # WAV is written directly by Python (no second ffmpeg encode pass) and is cheaper for
        # ffmpeg to decode again when streaming to Discord; the file only lives for one round.
        clip.export(str(temp_filename), format="wav").close()
        return str(temp_filename), effect_name
    except Exception as e:
        logger.warning("Failed to process/export audio clip for %s: %s", file_path, e)
        with contextlib.suppress(OSError):
            temp_filename.unlink(missing_ok=True)
        return None, None
