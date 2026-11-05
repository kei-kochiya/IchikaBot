"""
Gacha result images in the style of the in-game result screen: the game's gacha result
background, the cached card art on top, and the rarity stars + attribute icon overlaid on
each card.

The UI images are game assets fetched once (gacha background from sekai.best, rarity
stars and attribute icons from the sekai-viewer repository) and cached in CACHE_DIR/ui.
Every one of them is optional: without them the render falls back to a dark background,
drawn stars and no attribute icon, so a CDN outage never breaks /gacha.

Decoding full-size card art and shrinking it costs ~60-90 ms, so each card's resized tile
is cached next to the card art (CACHE_DIR/tiles) and re-used in later pulls (~0.4 ms).

The render_* functions are synchronous (Pillow): run them in an executor.
"""

import asyncio
import contextlib
import logging
import math
import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from utils.core.tasks import spawn
from utils.media.image_helper import cached_ui_asset_path, get_ui_asset_path

logger = logging.getLogger(__name__)

ATTRIBUTES = ("cute", "cool", "pure", "happy", "mysterious")

_SEKAI_VIEWER_ASSETS = "https://raw.githubusercontent.com/Sekai-World/sekai-viewer/main/src/assets"
_SEKAI_JP_ASSETS = "https://storage.sekai.best/sekai-jp-assets"
# The result background in full quality (PNG, 1.8 MB: ~20 s from sekai.best when it is
# slow) is kept on disk once downloaded. Until then the 50 KB WebP stands in, and the PNG
# is fetched in the background so no /gacha ever waits for it.
BG_ASSET = "bg_gacha_result.png"
BG_PREVIEW_ASSET = "bg_gacha_result.webp"
STAR_NORMAL = "rarity_star_normal.png"
STAR_TRAINED = "rarity_star_afterTraining.png"
STAR_BIRTHDAY = "rarity_birthday.png"

UI_ASSETS: dict[str, str] = {
    BG_ASSET: f"{_SEKAI_JP_ASSETS}/gacha/bg/{BG_ASSET}",
    BG_PREVIEW_ASSET: f"{_SEKAI_JP_ASSETS}/gacha/bg/{BG_PREVIEW_ASSET}",
    STAR_NORMAL: f"{_SEKAI_VIEWER_ASSETS}/{STAR_NORMAL}",
    STAR_TRAINED: f"{_SEKAI_VIEWER_ASSETS}/{STAR_TRAINED}",
    STAR_BIRTHDAY: f"{_SEKAI_VIEWER_ASSETS}/{STAR_BIRTHDAY}",
    **{
        f"icon_attribute_{attr}.png": f"{_SEKAI_VIEWER_ASSETS}/icon_attribute_{attr}.png"
        for attr in ATTRIBUTES
    },
}

# Card art is 2520x1440 (1.75:1); tiles keep that ratio. Spacing follows the in-game
# result screen: cards close together side by side, rows further apart.
TEN_PULL_TILE = (288, 165)
TEN_PULL_COLS = 5
TEN_PULL_GAP = (16, 40)  # (between columns, between rows)
TEN_PULL_MARGIN = (64, 56)  # (left/right, top/bottom)
SINGLE_TILE = (1120, 640)
SINGLE_MARGIN = 56

BG_FOCUS_Y = 0.58  # vertical centre of the crop: the stage railing of the result screen
BG_WASH = 0.3  # the result screen shows the stage behind a white haze
FALLBACK_BG = (44, 47, 51)
CORNER_RADIUS = 0.025  # of tile height: in-game cards are nearly square-cornered
BORDER = 0.012  # thin light edge around each card, of tile height
JPEG_QUALITY = 90


UI_ASSET_WAIT_S = 3.0  # longest a pull waits for UI images that are not on disk yet

_hq_background_download: asyncio.Task | None = None
_ui_download: asyncio.Task | None = None


async def _download(names: list[str]) -> None:
    await asyncio.gather(*(get_ui_asset_path(name, UI_ASSETS[name]) for name in names))


async def get_ui_assets() -> dict[str, str]:
    """{asset name: local path} of the gacha UI images on disk; missing ones are left out.

    Images not on disk yet are downloaded (once), but a pull waits for them at most
    UI_ASSET_WAIT_S: when sekai.best or GitHub is slow or down, the result is drawn with
    the fallbacks instead of every /gacha waiting out a 30 s timeout. The full-quality
    background is never waited for: the small WebP stands in until the PNG is on disk."""
    global _hq_background_download, _ui_download
    hq_background = cached_ui_asset_path(BG_ASSET)
    if hq_background is None and (
        _hq_background_download is None or _hq_background_download.done()
    ):
        _hq_background_download = spawn(get_ui_asset_path(BG_ASSET, UI_ASSETS[BG_ASSET]))

    names = [
        n for n in UI_ASSETS if n != BG_ASSET and not (hq_background and n == BG_PREVIEW_ASSET)
    ]
    missing = [n for n in names if cached_ui_asset_path(n) is None]
    if missing:
        if _ui_download is None or _ui_download.done():
            _ui_download = spawn(_download(missing))
        with contextlib.suppress(TimeoutError, OSError):
            await asyncio.wait_for(asyncio.shield(_ui_download), UI_ASSET_WAIT_S)

    assets = {name: path for name in names if (path := cached_ui_asset_path(name))}
    if hq_background:
        assets[BG_ASSET] = hq_background
    return assets


# ── Image helpers ─────────────────────────────────────────────────────────────


def _save_atomic(img: Image.Image, dest: Path, fmt: str, **kwargs) -> None:
    """Write a derived cache file so readers never see a half-written image."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        img.save(tmp, fmt, **kwargs)
        os.replace(tmp, dest)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def _cover(img: Image.Image, size: tuple[int, int], focus_y: float = 0.5) -> Image.Image:
    """Scale img to cover size (like CSS background-size: cover) and crop it."""
    w, h = size
    scale = max(w / img.width, h / img.height)
    rw, rh = math.ceil(img.width * scale), math.ceil(img.height * scale)
    resized = img.resize((rw, rh), Image.LANCZOS, reducing_gap=3.0)
    left = (rw - w) // 2
    top = min(max(round(focus_y * rh - h / 2), 0), rh - h)
    return resized.crop((left, top, left + w, top + h))


def _washed(bg: Image.Image, band: tuple[int, int] | None) -> Image.Image:
    """White haze over the stage, a little stronger in the band behind the cards."""
    haze = Image.new("L", bg.size, round(255 * BG_WASH))
    if band is not None:
        top, bottom = band
        draw = ImageDraw.Draw(haze)
        draw.rectangle((0, top, bg.width, bottom), fill=round(255 * (BG_WASH + 0.2)))
        haze = haze.filter(ImageFilter.GaussianBlur(max(4, (bottom - top) // 10)))
    return Image.composite(Image.new("RGB", bg.size, (255, 255, 255)), bg, haze)


def _background(
    assets: dict[str, str], size: tuple[int, int], band: tuple[int, int] | None = None
) -> Image.Image:
    """The washed result-screen background cropped to size (cached per layout), or a
    plain fill. band: (top, bottom) of the lighter strip behind the cards."""
    src = assets.get(BG_ASSET) or assets.get(BG_PREVIEW_ASSET)
    if src:
        key = f"{size[0]}x{size[1]}" + (f"_{band[0]}-{band[1]}" if band else "")
        # e.g. bg_gacha_result_png_1632x482_28-454_v3.png: one per source quality, so the
        # renders switch to the full-quality one as soon as it has been downloaded
        source = Path(src)
        derived = source.with_name(f"{source.stem}_{source.suffix[1:]}_{key}_v3.png")
        try:
            if derived.exists():
                with Image.open(derived) as im:
                    return im.convert("RGB")
            with Image.open(src) as im:
                bg = _washed(_cover(im.convert("RGB"), size, BG_FOCUS_Y), band)
            _save_atomic(bg, derived, "PNG")
            return bg
        except OSError as e:
            logger.warning("Gacha render: background unusable (%s), using a plain one", e)
    return Image.new("RGB", size, FALLBACK_BG)


def _card_tile(path: str | None, size: tuple[int, int]) -> Image.Image | None:
    """The card art resized to size, from the per-card tile cache when possible."""
    if not path:
        return None
    src = Path(path)
    derived = src.parent / "tiles" / f"{src.stem}_{size[0]}x{size[1]}.jpg"
    try:
        if derived.exists():
            with Image.open(derived) as im:
                return im.convert("RGB")
        with Image.open(src) as im:
            # Halve first with reduce() (cheap box filter), then a quality resize
            factor = max(1, min(im.width // size[0], im.height // size[1]) // 2)
            base = im.reduce(factor) if factor > 1 else im
            # Cover-crop: card art is not always exactly 1.75:1 (e.g. 2338x1440)
            tile = _cover(base, size).convert("RGB")
        _save_atomic(tile, derived, "JPEG", quality=92)
        return tile
    except OSError as e:
        logger.warning("Gacha render: could not open card art %s: %s", path, e)
        return None


def _load_icon(assets: dict[str, str], name: str, height: int) -> Image.Image | None:
    path = assets.get(name)
    if not path:
        return None
    try:
        with Image.open(path) as im:
            icon = im.convert("RGBA")
        width = max(1, round(icon.width * height / icon.height))
        return icon.resize((width, height), Image.LANCZOS)
    except OSError as e:
        logger.warning("Gacha render: icon %s unusable: %s", name, e)
        return None


def _drawn_star(height: int) -> Image.Image:
    """Fallback rarity star when the game's star image is unavailable."""
    scale = 4  # draw big and shrink for smooth edges
    s = height * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    cx = cy = s / 2
    outer, inner = s * 0.48, s * 0.2
    points = [
        (
            cx + (outer if i % 2 == 0 else inner) * math.sin(math.pi * i / 5),
            cy - (outer if i % 2 == 0 else inner) * math.cos(math.pi * i / 5),
        )
        for i in range(10)
    ]
    ImageDraw.Draw(img).polygon(points, fill=(255, 214, 64, 255), outline=(150, 90, 0, 255))
    return img.resize((height, height), Image.LANCZOS)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


class _Overlays:
    """Star / attribute icons sized for one tile height, loaded once per render."""

    def __init__(self, assets: dict[str, str], tile_h: int):
        self.star_h = max(12, round(tile_h * 0.14))
        self.attr_h = max(14, round(tile_h * 0.17))
        self.pad = max(3, round(tile_h * 0.035))
        self._assets = assets
        self._icons: dict[str, Image.Image | None] = {}

    def icon(self, name: str, height: int) -> Image.Image | None:
        if name not in self._icons:
            self._icons[name] = _load_icon(self._assets, name, height)
        return self._icons[name]

    def star(self, rarity: str, trained: bool) -> tuple[Image.Image, int]:
        """(star image, how many to draw) for a cardRarityType."""
        if rarity == "rarity_birthday":
            icon = self.icon(STAR_BIRTHDAY, self.star_h)
            return (icon or _drawn_star(self.star_h)), 1
        count = int(rarity[-1]) if rarity[-1:].isdigit() else 1
        icon = self.icon(STAR_TRAINED if trained else STAR_NORMAL, self.star_h)
        return (icon or _drawn_star(self.star_h)), count

    def attribute(self, attr: str | None) -> Image.Image | None:
        if attr not in ATTRIBUTES:
            return None
        return self.icon(f"icon_attribute_{attr}.png", self.attr_h)


def _decorate(tile: Image.Image, card: dict, overlays: _Overlays, trained: bool) -> Image.Image:
    """Overlay the attribute icon (top-right) and the rarity stars (stacked upwards from
    the bottom-left corner), as on the in-game gacha result screen."""
    out = tile.convert("RGBA")
    pad = overlays.pad

    attr = overlays.attribute(card.get("attr"))
    if attr is not None:
        out.alpha_composite(attr, (out.width - attr.width - pad, pad))

    star, count = overlays.star(card.get("cardRarityType", ""), trained)
    step = round(star.height * 0.82)  # stars overlap slightly
    y = out.height - star.height - pad
    for i in range(count):
        out.alpha_composite(star, (pad, y - i * step))
    return out


def _placeholder(size: tuple[int, int]) -> Image.Image:
    """Shown for a card whose art could not be fetched (e.g. not on the CDN yet)."""
    img = Image.new("RGB", size, (60, 64, 72))
    try:
        font = ImageFont.load_default(size=max(12, size[1] // 3))
    except (TypeError, OSError):  # Pillow < 10.1: fixed-size bitmap font only
        font = ImageFont.load_default()
    ImageDraw.Draw(img).text(
        (size[0] // 2, size[1] // 2), "?", fill=(200, 200, 200), anchor="mm", font=font
    )
    return img


def _paste_tiles(
    canvas: Image.Image,
    tiles: list[tuple[Image.Image, tuple[int, int]]],
    radius: int,
) -> None:
    """Paste tiles with a thin light edge and a faint shadow onto canvas (in place)."""
    if not tiles:
        return
    tile_h = tiles[0][0].height
    border = max(1, round(tile_h * BORDER))
    shadow = Image.new("L", canvas.size, 0)
    draw = ImageDraw.Draw(shadow)
    offset = max(2, tile_h // 60)
    for tile, (x, y) in tiles:
        draw.rectangle((x, y + offset, x + tile.width, y + tile.height + offset), fill=70)
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(3, tile_h // 30)))
    canvas.paste((40, 60, 90), (0, 0), shadow)

    edge = ImageDraw.Draw(canvas)
    mask = _rounded_mask(tiles[0][0].size, radius)
    for tile, (x, y) in tiles:
        if tile.size != mask.size:
            mask = _rounded_mask(tile.size, radius)
        edge.rounded_rectangle(
            (x - border, y - border, x + tile.width + border - 1, y + tile.height + border - 1),
            radius + border,
            fill=(250, 252, 255),
        )
        canvas.paste(tile.convert("RGB"), (x, y), mask)


def _to_jpeg(img: Image.Image) -> BytesIO:
    out = BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=JPEG_QUALITY, subsampling=0)
    out.seek(0)
    return out


def _is_trained_art(card: dict, path: str | None) -> bool:
    return bool(path) and Path(path).stem.endswith("_after_training")


# ── Public renderers ──────────────────────────────────────────────────────────


def render_ten_pull(
    results: list[dict], image_paths: list[str | None], assets: dict[str, str]
) -> BytesIO:
    """Render up to 10 cards as a 5x2 grid on the result background. Returns a JPEG."""
    tw, th = TEN_PULL_TILE
    (gap_x, gap_y), (margin_x, margin_y) = TEN_PULL_GAP, TEN_PULL_MARGIN
    rows = max(1, math.ceil(len(results) / TEN_PULL_COLS))
    width = TEN_PULL_COLS * tw + (TEN_PULL_COLS - 1) * gap_x + 2 * margin_x
    height = rows * th + (rows - 1) * gap_y + 2 * margin_y
    canvas = _background(assets, (width, height), band=(margin_y // 2, height - margin_y // 2))
    overlays = _Overlays(assets, th)

    tiles = []
    for i, (card, path) in enumerate(zip(results, image_paths, strict=True)):
        tile = _card_tile(path, TEN_PULL_TILE) or _placeholder(TEN_PULL_TILE)
        tile = _decorate(tile, card, overlays, _is_trained_art(card, path))
        row, col = divmod(i, TEN_PULL_COLS)
        x = margin_x + col * (tw + gap_x)
        y = margin_y + row * (th + gap_y)
        tiles.append((tile, (x, y)))

    _paste_tiles(canvas, tiles, round(th * CORNER_RADIUS))
    return _to_jpeg(canvas)


def render_single_pull(card: dict, image_path: str | None, assets: dict[str, str]) -> BytesIO:
    """Render one card on the result background. Returns a JPEG. Without usable art (not
    on the CDN yet, a download error) a placeholder stands in, so the pull is never lost."""
    tile = _card_tile(image_path, SINGLE_TILE) or _placeholder(SINGLE_TILE)
    tw, th = SINGLE_TILE
    canvas = _background(assets, (tw + 2 * SINGLE_MARGIN, th + 2 * SINGLE_MARGIN))
    # In-game the icons are sized for a small thumbnail: scale them down on big art
    overlays = _Overlays(assets, round(th * 0.6))
    tile = _decorate(tile, card, overlays, _is_trained_art(card, image_path))
    _paste_tiles(canvas, [(tile, (SINGLE_MARGIN, SINGLE_MARGIN))], round(th * CORNER_RADIUS * 0.6))
    return _to_jpeg(canvas)
