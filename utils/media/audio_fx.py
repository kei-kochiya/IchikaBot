import logging
import random
import subprocess
import uuid

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


def _probe_duration_ms(file_path: str) -> int | None:
    """Return the track length in ms via ffprobe, or None if it can't be determined."""
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
        return duration_ms if duration_ms > 0 else None
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

    if len(proc.stdout) < _PCM_RATE * _PCM_CHANNELS * _PCM_WIDTH:  # < 1 second of audio
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

    # Fallback: decode the whole track (slow and memory hungry, but always works)
    try:
        song = AudioSegment.from_file(file_path)
    except Exception as e:
        logger.error("Failed to load audio file: %s", e)
        return None
    start_time = _pick_start(len(song))
    return song[start_time : start_time + SONG_CLIP_DURATION]


def prepare_clip(file_path: str, variant: str | None = None) -> tuple[str | None, str | None]:
    """Prepare audio clip with optional effects."""
    clip = _load_clip(file_path)
    if clip is None:
        return None, None

    effect_name = "Bình thường"
    if variant == "fast":
        clip = speedup(clip, playback_speed=1.5)
        effect_name = "Tua nhanh 1.5x ⏩"
    elif variant == "slow":
        clip = clip._spawn(clip.raw_data, overrides={"frame_rate": int(clip.frame_rate * 0.75)})
        effect_name = "Tua chậm 0.75x ⏪"
    elif variant == "reverse":
        clip = clip.reverse()
        effect_name = "Phát ngược 🔄"

    # WAV is written directly by Python (no second ffmpeg encode pass) and is cheaper for
    # ffmpeg to decode again when streaming to Discord; the file only lives for one round.
    temp_filename = TEMP_DIR / f"{TEMP_CLIP_PREFIX}{uuid.uuid4().hex}.wav"
    clip.export(str(temp_filename), format="wav").close()
    return str(temp_filename), effect_name
