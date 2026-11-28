"""Image cropping/effects and multilingual answer builders for song jacket and chart guessing games."""

from __future__ import annotations

import logging
import random
from io import BytesIO

from PIL import Image, ImageFilter, ImageOps

from utils.core.romaji import to_romaji
from utils.data.music_quiz_db import MusicQuizDB, is_correct_guess, normalize
from utils.data.song_data import song_data

logger = logging.getLogger(__name__)

# sekai-music-charts (pjsekai-scores-rs) places a horizontal divider at h - 256 with the
# song jacket & title below it; keeping crops strictly above this band guarantees zero spoilers.
_CHART_FOOTER_DEFAULT = 288
_CHART_TOP_MARGIN = 36
_CHART_CROP_SPEC: dict[str, tuple[int, int]] = {
    "easy": (2, 920),  # 2 adjacent columns, tall slice (~4-8 measures)
    "normal": (1, 820),  # 1 column, medium slice (~2-4 measures)
    "hard": (1, 480),  # 1 column, short slice (~1-2 measures)
}
_JACKET_CROP_RATIO: dict[str, float] = {
    "easy": 0.55,
    "normal": 0.36,
    "hard": 0.36,
}


def build_song_answers(song: dict) -> tuple[str, list[str], list[str]]:
    """Build `(display_title, norm_targets, raw_jp_targets)` covering JP, EN, kana, and romaji."""
    song_id = int(song["id"])
    jp_title = str(song.get("title") or "").strip()
    pron = str(song.get("pronunciation") or "").strip()
    en_meta = song_data.songs_en_meta.get(song_id) or {}
    en_title = str(en_meta.get("title") or "").strip()

    raw_candidates = [jp_title, en_title, pron, to_romaji(pron), to_romaji(jp_title)]
    db = MusicQuizDB.get_instance()
    if db._db:
        info = db._db.get(str(song_id))
        if info:
            for key in ("title_en", "title_jp", "romaji_title"):
                val = str(info.get(key) or "").strip()
                if val:
                    raw_candidates.append(val)
            if not en_title and info.get("title_en"):
                en_title = str(info["title_en"]).strip()

    if en_title and jp_title and en_title.lower() != jp_title.lower():
        display = f"{en_title} ({jp_title})"
    else:
        display = en_title or jp_title or f"Song #{song_id}"

    norm_targets = list(dict.fromkeys(nt for c in raw_candidates if c and (nt := normalize(c))))
    raw_jp_targets = list(
        dict.fromkeys(
            "".join(c.split()).lower() for c in (jp_title, pron) if c and not normalize(c)
        )
    )
    return display, norm_targets, raw_jp_targets


def is_song_guess_correct(
    raw_guess: str, norm_targets: list[str], raw_jp_targets: list[str] = ()
) -> bool:
    """Match a player's song guess across ASCII/romaji, kana-to-romaji, and exact Japanese title."""
    if is_correct_guess(raw_guess, norm_targets):
        return True
    romaji_guess = to_romaji(raw_guess)
    if romaji_guess != raw_guess and is_correct_guess(romaji_guess, norm_targets):
        return True
    compact = "".join(raw_guess.split()).lower()
    return bool(compact and compact in raw_jp_targets)


def process_jacket_image_sync(local_path: str, mode: str = "normal") -> tuple[BytesIO | None, str]:
    """Create a cropped/effected puzzle JPEG from a song jacket off the event loop."""
    try:
        with Image.open(local_path) as raw:
            img = raw.convert("RGB")
        try:
            w, h = img.size
            if w < 300 or h < 300:
                resized = img.resize((max(w, 300), max(h, 300)), Image.LANCZOS)
                img.close()
                img = resized
                w, h = img.size

            if mode == "hard":
                effect = random.choice(["crop_bw", "pixelate", "blur", "negative"])
            elif mode == "easy":
                effect = "crop_large"
            else:
                effect = "crop"

            if effect in ("crop_large", "crop", "crop_bw"):
                ratio = _JACKET_CROP_RATIO.get(mode, 0.36)
                cw = max(120, int(w * ratio))
                ch = max(120, int(h * ratio))
                x = random.randint(0, max(0, w - cw))
                y = random.randint(0, max(0, h - ch))
                out_img = img.crop((x, y, x + cw, y + ch))
                if effect == "crop_bw":
                    gray = ImageOps.grayscale(out_img)
                    out_img.close()
                    out_img = gray
                    effect_label = "Trắng đen"
                else:
                    effect_label = "Crop rộng" if effect == "crop_large" else "Crop"
            elif effect == "pixelate":
                tiny = img.resize((28, 28), Image.NEAREST)
                out_img = tiny.resize((w, h), Image.NEAREST)
                tiny.close()
                effect_label = "Pixelate"
            elif effect == "blur":
                small = img.resize((max(1, w // 4), max(1, h // 4)), Image.BILINEAR)
                blurred = small.filter(ImageFilter.GaussianBlur(radius=6))
                small.close()
                out_img = blurred.resize((w, h), Image.BILINEAR)
                blurred.close()
                effect_label = "Blur"
            else:
                out_img = ImageOps.invert(img)
                effect_label = "Âm bản"

            try:
                buf = BytesIO()
                if out_img.mode not in ("RGB", "L"):
                    conv = out_img.convert("RGB")
                    conv.save(buf, format="JPEG", quality=90)
                    conv.close()
                else:
                    out_img.save(buf, format="JPEG", quality=90)
                buf.seek(0)
                return buf, effect_label
            finally:
                out_img.close()
        finally:
            img.close()
    except OSError as exc:
        logger.error("Failed to process jacket image %s: %s", local_path, exc)
        return None, ""


def _color_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _find_chart_bottom(px, w: int, h: int, bg: tuple[int, int, int]) -> int:
    """Locate the bottom of the playable chart region strictly above the title/jacket footer."""
    search_start = max(_CHART_TOP_MARGIN + 100, h - 360)
    search_end = max(search_start + 1, h - 160)
    step_x = max(1, w // 128)
    samples = len(range(0, w, step_x))
    for y in range(search_start, search_end):
        non_bg = sum(1 for x in range(0, w, step_x) if _color_dist(px[x, y], bg) > 20)
        # Full-width horizontal divider line above the jacket/title banner
        if non_bg >= int(samples * 0.9):
            return max(_CHART_TOP_MARGIN + 100, y - 32)
    return max(_CHART_TOP_MARGIN + 100, h - _CHART_FOOTER_DEFAULT)


def _find_lane_columns(
    px, w: int, play_top: int, play_bottom: int, bg: tuple[int, int, int]
) -> list[tuple[int, int]]:
    """Detect `(x0, x1)` bounds of vertical lane columns in a pre-rendered chart sheet."""
    y_probe = play_top + int((play_bottom - play_top) * 0.7)
    runs: list[tuple[int, int]] = []
    in_run = False
    start = 0
    for x in range(w):
        is_lane = _color_dist(px[x, y_probe], bg) > 12
        if is_lane and not in_run:
            start = x
            in_run = True
        elif not is_lane and in_run:
            if x - start >= 100:
                runs.append((start, x))
            in_run = False
    if in_run and w - start >= 100:
        runs.append((start, w))
    return runs


def _score_window_notes(
    px,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    bg: tuple[int, int, int],
    lane_color: tuple[int, int, int],
) -> tuple[int, int]:
    """Return `(note_pixels, lane_pixels)` sampled on a coarse grid inside `(x0, y0, x1, y1)`."""
    note_px = 0
    lane_px = 0
    for y in range(y0, y1, 8):
        for x in range(x0, x1, 6):
            c = px[x, y]
            if _color_dist(c, bg) <= 18:
                continue
            lane_px += 1
            if _color_dist(c, lane_color) > 36:
                note_px += 1
    return note_px, lane_px


def crop_chart_image_sync(local_path: str, mode: str = "normal") -> BytesIO | None:
    """Crop a note-dense, spoiler-free slice from a pre-rendered sekai-music-charts PNG."""
    try:
        with Image.open(local_path) as raw:
            img = raw.convert("RGB")
        try:
            w, h = img.size
            if w < 200 or h < 450:
                return None

            px = img.load()
            bg = px[0, 0]
            play_top = min(_CHART_TOP_MARGIN, h // 10)
            play_bottom = _find_chart_bottom(px, w, h, bg)
            play_h = play_bottom - play_top
            if play_h < 200:
                return None

            col_count, target_h = _CHART_CROP_SPEC.get(mode, _CHART_CROP_SPEC["normal"])
            crop_h = min(target_h, play_h)
            cols = _find_lane_columns(px, w, play_top, play_bottom, bg)

            candidates: list[tuple[int, tuple[int, int, int, int]]] = []
            if cols:
                # Sample representative empty lane fill color from the first full column
                lane_cx = (cols[0][0] + cols[0][1]) // 2
                lane_color = px[lane_cx, play_top + play_h // 2]
                # Skip the last column when multiple columns exist (often short/empty at top)
                usable_cols = cols[:-1] if len(cols) > max(2, col_count) else cols
                max_start_idx = max(0, len(usable_cols) - col_count)

                for _ in range(16):
                    ci = random.randint(0, max_start_idx)
                    c_left = usable_cols[ci][0]
                    c_right = usable_cols[min(ci + col_count - 1, len(usable_cols) - 1)][1]
                    # Include left gutter for measure ticks/labels without touching previous column
                    x0 = max(0, c_left - 44)
                    x1 = min(w, c_right + 16)
                    y0 = random.randint(play_top, play_bottom - crop_h)
                    y1 = y0 + crop_h
                    note_px, lane_px = _score_window_notes(
                        px, c_left, y0, c_right, y1, bg, lane_color
                    )
                    if lane_px > 0:
                        candidates.append((note_px, (x0, y0, x1, y1)))

            if candidates:
                candidates.sort(key=lambda item: item[0], reverse=True)
                # Pick randomly among the top note-dense slices so rounds stay varied yet readable
                top_k = candidates[: min(4, len(candidates))]
                box = random.choice(top_k)[1]
            else:
                cw = min(w, 420)
                x0 = random.randint(0, w - cw)
                y0 = random.randint(play_top, play_bottom - crop_h)
                box = (x0, y0, x0 + cw, y0 + crop_h)

            cropped = img.crop(box)
            try:
                # Upscale narrow 1-column slices slightly so notes read crisply on Discord mobile
                cw_out, ch_out = cropped.size
                if cw_out < 360:
                    scale = 360 / cw_out
                    up = cropped.resize(
                        (round(cw_out * scale), round(ch_out * scale)), Image.LANCZOS
                    )
                    cropped.close()
                    cropped = up
                buf = BytesIO()
                cropped.save(buf, format="JPEG", quality=92)
                buf.seek(0)
                return buf
            finally:
                cropped.close()
        finally:
            img.close()
    except OSError as exc:
        logger.error("Failed to crop chart image %s: %s", local_path, exc)
        return None
