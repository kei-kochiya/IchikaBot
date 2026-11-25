"""
Pillow renderer for Project Sekai Best 30 (B30) images.

Faithfully mirrors the layout and styling of auburnsummer/pjskb30 & auburnsummer/sbotgab30:
  - 1000 x 1500 canvas with pastel background and #b4ccfa header bar (title left, Ranking right).
  - 3 columns x 10 rows grid (gutter 30x35, cards ~293x108).
  - AP cards: white-to-#f2feff diagonal fill + 5px pink-to-cyan (#FF8EFF -> #00E3C7) gradient border.
  - FC cards: white fill + 2px #FE83FE border.
  - Difficulty pills overlapping top-left corner: Expert (#FF457A), Master (#781c94),
    Append (#7857ff -> #fcacf7 gradient + white border) displaying diffConstant (e.g. 32.5).
  - AP/FC diamond (or 4-point star for Append) overlapping bottom-right corner with AP/FC text.

Run `render_b30_image()` in an executor (`loop.run_in_executor` / `asyncio.to_thread`).
"""

from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from utils.pjsk.constants import B30Entry, B30Summary

logger = logging.getLogger(__name__)

# FreeType2 FT_Face objects cached by _get_font() are not thread-safe under concurrent
# ThreadPoolExecutor renders; serialize Pillow rendering across threads.
_RENDER_LOCK = threading.Lock()

# Canvas & grid geometry (matching pjskb30/src/draw/draw.ts)
WIDTH = 1000
HEIGHT = 1500
HEADER_HEIGHT = 38
GUTTER_WIDTH = 30
GUTTER_HEIGHT = 35
COLS = 3
ROWS = 10
CARD_WIDTH = (WIDTH - GUTTER_WIDTH * (COLS + 1)) // COLS  # 293
CARD_HEIGHT = (HEIGHT - HEADER_HEIGHT - GUTTER_HEIGHT * (ROWS + 1)) // ROWS  # 107
JACKET_PADDING = 14
JACKET_SIZE = CARD_HEIGHT - JACKET_PADDING * 2  # 79

BADGE_WIDTH = 42
BADGE_HEIGHT = 24
DIAMOND_SIZE = 38

# Palette
HEADER_BG = (180, 204, 250)  # #b4ccfa
FC_COLOR = (254, 131, 254)  # #FE83FE
AP_PINK = (255, 142, 255)  # #FF8EFF
AP_CYAN = (0, 227, 199)  # #00E3C7
AP_FILL_TOP = (255, 255, 255)
AP_FILL_BOT = (242, 254, 255)  # #f2feff
EXPERT_COLOR = (255, 69, 122)  # #FF457A
MASTER_COLOR = (120, 28, 148)  # #781c94
APPEND_START = (120, 87, 255)  # #7857ff
APPEND_END = (252, 172, 247)  # #fcacf7
TEXT_DARK = (24, 28, 40)
TEXT_MUTED = (95, 105, 128)
SHADOW_COLOR = (0, 25, 74)  # #00194a

# Cross-platform font candidates (prioritize fonts with Latin + CJK/Japanese glyphs)
_FONT_CANDIDATES = (
    # Windows (CJK + Latin)
    r"C:\Windows\Fonts\meiryob.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    # Linux / Docker (Debian/Ubuntu/Alpine Noto & DejaVu)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    # macOS
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
)

_REGULAR_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)


@lru_cache(maxsize=2)
def _find_font_path(bold: bool) -> str | None:
    candidates = _FONT_CANDIDATES if bold else _REGULAR_FONT_CANDIDATES
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


@lru_cache(maxsize=16)
def _get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = _find_font_path(bold)
    if font_path:
        try:
            return ImageFont.truetype(font_path, size=size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except (TypeError, OSError):
        return ImageFont.load_default()


def _lerp_rgb(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        round(c1[0] + (c2[0] - c1[0]) * t),
        round(c1[1] + (c2[1] - c1[1]) * t),
        round(c1[2] + (c2[2] - c1[2]) * t),
    )


def _vertical_gradient(
    size: tuple[int, int],
    stops: list[tuple[float, tuple[int, int, int]]],
) -> Image.Image:
    """Create a smooth vertical RGB linear gradient from normalized (pos, rgb) stops."""
    w, h = size
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    for y in range(h):
        t = y / max(1, h - 1)
        color = stops[-1][1]
        for i in range(len(stops) - 1):
            p0, c0 = stops[i]
            p1, c1 = stops[i + 1]
            if p0 <= t <= p1:
                local_t = (t - p0) / max(1e-6, p1 - p0)
                color = _lerp_rgb(c0, c1, local_t)
                break
        px[0, y] = color
    return strip.resize((w, h), Image.NEAREST)


def _diagonal_gradient(
    size: tuple[int, int], c_start: tuple[int, int, int], c_end: tuple[int, int, int]
) -> Image.Image:
    """Create a diagonal (top-left to bottom-right) RGB gradient."""
    w, h = size
    img = Image.new("RGB", (w, h))
    px = img.load()
    denom = max(1, (w - 1) + (h - 1))
    for y in range(h):
        for x in range(w):
            px[x, y] = _lerp_rgb(c_start, c_end, (x + y) / denom)
    return img


def _build_pastel_background() -> Image.Image:
    """Soft SEKAI-inspired pastel gradient background with subtle geometric accents.

    Renders the bokeh overlay at quarter resolution and is not cached globally so idle RAM
    returns to 0 MB immediately after each render.
    """
    grad_rgb = _vertical_gradient(
        (WIDTH, HEIGHT),
        [
            (0.0, (226, 238, 255)),
            (0.48, (238, 234, 255)),
            (1.0, (252, 232, 248)),
        ],
    )
    bg = grad_rgb.convert("RGBA")
    grad_rgb.close()

    sw, sh = WIDTH // 4, HEIGHT // 4
    small_overlay = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(small_overlay)
    # Soft translucent bokeh circles reminiscent of pjskb30 backgrounds
    accents = [
        (140, 210, 170, (255, 255, 255, 55)),
        (860, 340, 220, (195, 222, 255, 60)),
        (220, 920, 250, (255, 210, 245, 50)),
        (790, 1260, 210, (185, 245, 240, 55)),
    ]
    for cx, cy, r, fill in accents:
        draw.ellipse(((cx - r) // 4, (cy - r) // 4, (cx + r) // 4, (cy + r) // 4), fill=fill)
    blurred = small_overlay.filter(ImageFilter.GaussianBlur(7))
    small_overlay.close()
    overlay = blurred.resize((WIDTH, HEIGHT), Image.BILINEAR)
    blurred.close()
    try:
        composited = Image.alpha_composite(bg, overlay)
        try:
            return composited.convert("RGB")
        finally:
            composited.close()
    finally:
        bg.close()
        overlay.close()


@lru_cache(maxsize=2)
def _build_card_base(is_ap: bool) -> Image.Image:
    """Pre-render a single AP or FC card frame (RGBA) with border and subtle fill."""
    w, h = CARD_WIDTH, CARD_HEIGHT
    radius = 6
    border = 5 if is_ap else 2

    outer_mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(outer_mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)

    inner_mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(inner_mask).rounded_rectangle(
        (border, border, w - 1 - border, h - 1 - border),
        radius=max(2, radius - 2),
        fill=255,
    )

    if is_ap:
        border_img = _vertical_gradient((w, h), [(0.0, AP_PINK), (1.0, AP_CYAN)])
        fill_img = _vertical_gradient((w, h), [(0.0, AP_FILL_TOP), (1.0, AP_FILL_BOT)])
    else:
        border_img = Image.new("RGB", (w, h), FC_COLOR)
        fill_img = Image.new("RGB", (w, h), (255, 255, 255))

    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    card.paste(border_img, (0, 0), outer_mask)
    card.paste(fill_img, (0, 0), inner_mask)
    return card


@lru_cache(maxsize=3)
def _build_diff_badge(difficulty: str) -> Image.Image:
    """Pre-render the rounded difficulty badge background (RGBA)."""
    w, h = BADGE_WIDTH, BADGE_HEIGHT
    radius = 10
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)

    badge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if difficulty == "append":
        grad = _diagonal_gradient((w, h), APPEND_START, APPEND_END)
        # White 2px outer border
        badge.paste((255, 255, 255, 255), (0, 0), mask)
        inner = Image.new("L", (w, h), 0)
        ImageDraw.Draw(inner).rounded_rectangle((2, 2, w - 3, h - 3), radius=radius - 2, fill=255)
        badge.paste(grad, (0, 0), inner)
    else:
        color = EXPERT_COLOR if difficulty == "expert" else MASTER_COLOR
        badge.paste((*color, 255), (0, 0), mask)
    return badge


@lru_cache(maxsize=4)
def _build_clear_indicator(is_ap: bool, is_append: bool) -> Image.Image:
    """Pre-render the AP/FC diamond (or 4-point Append star) with 4x supersampling."""
    scale = 4
    s = DIAMOND_SIZE * scale
    pad = 4 * scale
    box = s + pad * 2
    d = float(s)

    if is_append:
        # Matches pjskb30 appendShape
        raw_pts = [
            (0.0, 0.0),
            (d / 2, d / 7),
            (d, 0.0),
            (d - d / 7, d / 2),
            (d, d),
            (d / 2, d - d / 7),
            (0.0, d),
            (d / 7, d / 2),
        ]
    else:
        raw_pts = [
            (d / 2, 0.0),
            (d, d / 2),
            (d / 2, d),
            (0.0, d / 2),
        ]
    pts = [(x + pad, y + pad) for x, y in raw_pts]

    shape_mask = Image.new("L", (box, box), 0)
    ImageDraw.Draw(shape_mask).polygon(pts, fill=255)

    if is_ap:
        fill_src = _vertical_gradient(
            (box, box),
            [(0.0, AP_PINK), (0.3, AP_PINK), (0.7, AP_CYAN), (1.0, AP_CYAN)],
        )
    else:
        fill_src = Image.new("RGB", (box, box), FC_COLOR)

    big = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    big.paste(fill_src, (0, 0), shape_mask)

    # Crisp dark outline
    draw = ImageDraw.Draw(big)
    outline_pts = [*pts, pts[0]]
    draw.line(outline_pts, fill=(20, 20, 28, 255), width=2 * scale, joint="curve")

    out_size = DIAMOND_SIZE + 8
    img = big.resize((out_size, out_size), Image.LANCZOS)

    # Draw crisp AP / FC label in center
    label = "AP" if is_ap else "FC"
    font = _get_font(12, bold=True)
    td = ImageDraw.Draw(img)
    cx, cy = out_size // 2, out_size // 2
    # Subtle text shadow for readability on bright gradient
    _draw_text_aligned(td, (cx + 1, cy + 1), label, font=font, fill=(0, 0, 0, 140), anchor="mm")
    _draw_text_aligned(td, (cx, cy), label, font=font, fill=(255, 255, 255, 255), anchor="mm")
    return img


def _draw_text_aligned(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    fill: tuple[int, ...],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    anchor: str,
) -> None:
    """Draw text with *anchor*, falling back gracefully if *font* is a legacy bitmap font."""
    if isinstance(font, ImageFont.FreeTypeFont):
        draw.text(xy, text, fill=fill, font=font, anchor=anchor)
        return
    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = xy
    if anchor[0] == "m":
        x -= tw // 2
    elif anchor[0] == "r":
        x -= tw
    if anchor[1] == "m":
        y -= th // 2
    draw.text((x, y), text, fill=fill, font=font)


def _load_jacket(path: str | None) -> Image.Image:
    """Load and resize a song jacket to JACKET_SIZE x JACKET_SIZE, or return a placeholder."""
    if path and Path(path).is_file():
        try:
            with Image.open(path) as im:
                rgb = im.convert("RGB")
                try:
                    return rgb.resize((JACKET_SIZE, JACKET_SIZE), Image.LANCZOS)
                finally:
                    rgb.close()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            logger.debug("B30 render: could not open jacket %s: %s", path, exc)

    placeholder = Image.new("RGB", (JACKET_SIZE, JACKET_SIZE), (210, 220, 238))
    draw = ImageDraw.Draw(placeholder)
    _draw_text_aligned(
        draw,
        (JACKET_SIZE // 2, JACKET_SIZE // 2),
        "♪",
        fill=(110, 125, 160),
        font=_get_font(28, bold=True),
        anchor="mm",
    )
    return placeholder


def _wrap_title(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 3,
) -> list[str]:
    """Wrap *text* (supporting both space-delimited Latin and continuous Japanese) into lines."""
    text = " ".join(text.split())
    if not text:
        return ["Unknown"]

    def text_w(s: str) -> float:
        bbox = font.getbbox(s)
        return float(bbox[2] - bbox[0])

    # Tokenize: keep words together when spaces exist, split long tokens by character
    words = text.split(" ")
    lines: list[str] = []
    current = ""

    def flush_word(word: str) -> None:
        nonlocal current
        if not current:
            if text_w(word) <= max_width:
                current = word
                return
            # Character-wrap long unbroken word / Japanese string
            chunk = ""
            for ch in word:
                if chunk and text_w(chunk + ch) > max_width:
                    lines.append(chunk)
                    chunk = ch
                else:
                    chunk += ch
            current = chunk
        else:
            candidate = f"{current} {word}"
            if text_w(candidate) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = ""
                flush_word(word)

    for w in words:
        flush_word(w)
    if current:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and text_w(last + "…") > max_width:
            last = last[:-1]
        lines[-1] = (last.rstrip() + "…") if last else "…"
    return lines


def render_b30_image(
    summary: B30Summary,
    jacket_paths: dict[int, str | None],
    *,
    player_name: str,
    region: str,
) -> BytesIO:
    """Render the full 1000x1500 Project Sekai B30 card grid and return a JPEG BytesIO."""
    with _RENDER_LOCK:
        return _render_b30_unlocked(summary, jacket_paths, player_name=player_name, region=region)


def _render_b30_unlocked(
    summary: B30Summary,
    jacket_paths: dict[int, str | None],
    *,
    player_name: str,
    region: str,
) -> BytesIO:
    canvas = _build_pastel_background()
    jacket_cache: dict[int, Image.Image] = {}
    j_mask: Image.Image | None = None
    try:
        # Soft shadow layer for header bar + all populated cards
        shadow_layer = Image.new("L", (WIDTH // 2, HEIGHT // 2), 0)
        sdraw = ImageDraw.Draw(shadow_layer)
        sdraw.rectangle((0, 0, WIDTH // 2, (HEADER_HEIGHT + 3) // 2), fill=110)

        card_positions: list[tuple[int, int, B30Entry]] = []
        for idx, entry in enumerate(summary.entries[: COLS * ROWS]):
            row, col = divmod(idx, COLS)
            x = GUTTER_WIDTH + col * (CARD_WIDTH + GUTTER_WIDTH)
            y = HEADER_HEIGHT + GUTTER_HEIGHT + row * (CARD_HEIGHT + GUTTER_HEIGHT)
            card_positions.append((x, y, entry))
            sdraw.rectangle(
                (x // 2, (y + 3) // 2, (x + CARD_WIDTH) // 2, (y + CARD_HEIGHT + 3) // 2),
                fill=85,
            )

        blurred_shadow = shadow_layer.filter(ImageFilter.GaussianBlur(3.0))
        shadow_layer.close()
        shadow = blurred_shadow.resize((WIDTH, HEIGHT), Image.BILINEAR)
        blurred_shadow.close()
        canvas.paste(SHADOW_COLOR, (0, 0), shadow)
        shadow.close()

        # Top header bar (#b4ccfa)
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, WIDTH, HEADER_HEIGHT), fill=HEADER_BG)

        header_font = _get_font(21, bold=True)
        safe_name = (" ".join((player_name or "Player").split()) or "Player")[:28]
        left_label = f"{safe_name}'s Best 30  [{region.upper()}]"
        right_label = f"Ranking: {summary.ranking:.2f}"
        _draw_text_aligned(
            draw,
            (14, HEADER_HEIGHT // 2),
            left_label,
            fill=TEXT_DARK,
            font=header_font,
            anchor="lm",
        )
        _draw_text_aligned(
            draw,
            (WIDTH - 14, HEADER_HEIGHT // 2),
            right_label,
            fill=TEXT_DARK,
            font=header_font,
            anchor="rm",
        )

        title_font = _get_font(16, bold=True)
        sub_font = _get_font(12, bold=False)
        badge_font = _get_font(13, bold=True)

        # Rounded mask for song jackets
        j_mask = Image.new("L", (JACKET_SIZE, JACKET_SIZE), 0)
        ImageDraw.Draw(j_mask).rounded_rectangle(
            (0, 0, JACKET_SIZE - 1, JACKET_SIZE - 1), radius=4, fill=255
        )

        for idx, (x, y, entry) in enumerate(card_positions, start=1):
            is_ap = entry.clear_state == "ap"
            is_append = entry.difficulty == "append"

            # 1. Card body (AP or FC frame)
            base_card = _build_card_base(is_ap)
            canvas.paste(base_card, (x, y), base_card)

            # 2. Song jacket on left
            if entry.song_id not in jacket_cache:
                jacket_cache[entry.song_id] = _load_jacket(jacket_paths.get(entry.song_id))
            canvas.paste(
                jacket_cache[entry.song_id],
                (x + JACKET_PADDING, y + JACKET_PADDING),
                j_mask,
            )

            # 3. Song title + rank/rating subline on right
            text_x = x + JACKET_PADDING * 2 + JACKET_SIZE
            text_w = CARD_WIDTH - (JACKET_PADDING * 3 + JACKET_SIZE)
            lines = _wrap_title(entry.title, title_font, text_w, max_lines=3)
            line_h = 20
            block_h = len(lines) * line_h
            # Reserve small space at bottom of text column for "#rank · rating"
            text_area_top = y + 12
            text_area_h = CARD_HEIGHT - 32
            start_y = text_area_top + max(0, (text_area_h - block_h) // 2)
            for li, line in enumerate(lines):
                draw.text((text_x, start_y + li * line_h), line, fill=TEXT_DARK, font=title_font)

            meta_label = f"#{idx}  ·  {entry.rating:.1f}"
            draw.text((text_x, y + CARD_HEIGHT - 20), meta_label, fill=TEXT_MUTED, font=sub_font)

            # 4. Difficulty constant badge overlapping top-left corner
            bx = x - BADGE_WIDTH // 2 + 4
            by = y - BADGE_HEIGHT // 2 + 2
            badge_img = _build_diff_badge(entry.difficulty)
            canvas.paste(badge_img, (bx, by), badge_img)
            _draw_text_aligned(
                draw,
                (bx + BADGE_WIDTH // 2, by + BADGE_HEIGHT // 2),
                f"{entry.constant:.1f}",
                fill=(255, 255, 255),
                font=badge_font,
                anchor="mm",
            )

            # 5. AP / FC diamond or Append star overlapping bottom-right corner
            ind_img = _build_clear_indicator(is_ap, is_append)
            ix = x + CARD_WIDTH - ind_img.width // 2 - 2
            iy = y + CARD_HEIGHT - ind_img.height // 2 - 2
            canvas.paste(ind_img, (ix, iy), ind_img)

        # Empty state hint if player has 0 FC/AP charts
        if not card_positions:
            empty_font = _get_font(26, bold=True)
            _draw_text_aligned(
                draw,
                (WIDTH // 2, HEIGHT // 2),
                "Chưa có bài FC/AP nào trong bảng B30",
                fill=TEXT_MUTED,
                font=empty_font,
                anchor="mm",
            )

        out = BytesIO()
        canvas.save(out, "JPEG", quality=92, subsampling=0)
        out.seek(0)
        return out
    finally:
        canvas.close()
        if j_mask is not None:
            j_mask.close()
        for j_img in jacket_cache.values():
            j_img.close()
