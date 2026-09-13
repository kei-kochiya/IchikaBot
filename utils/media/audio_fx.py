import logging
import random
import uuid

from pydub import AudioSegment
from pydub.effects import speedup

from config import SONG_CLIP_DURATION, SONG_SAFE_ZONE, TEMP_DIR

logger = logging.getLogger(__name__)

TEMP_CLIP_PREFIX = "temp_guess_clip_"


def prepare_clip(file_path: str, variant: str | None = None) -> tuple[str | None, str | None]:
    """Prepare audio clip with optional effects."""
    try:
        song = AudioSegment.from_file(file_path)
    except Exception as e:
        logger.error("Failed to load audio file: %s", e)
        return None, None

    duration_ms = len(song)
    min_start = SONG_SAFE_ZONE
    max_start = duration_ms - SONG_SAFE_ZONE - SONG_CLIP_DURATION

    start_time = random.randint(min_start, max_start) if min_start < max_start else 0
    clip = song[start_time : start_time + SONG_CLIP_DURATION]

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

    temp_filename = TEMP_DIR / f"{TEMP_CLIP_PREFIX}{uuid.uuid4().hex}.mp3"
    clip.export(str(temp_filename), format="mp3")
    return str(temp_filename), effect_name
