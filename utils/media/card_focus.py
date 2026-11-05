"""
Find a card's own character in its card art, for the easy /guess crops.

sekai.best's ``member_cutout`` is a close-up of the card's character for every card, but
it is recomposed artwork (often rotated, redrawn larger, background layers shifted), so it
cannot be lined up with the card art pixel for pixel. Its colours still identify the
character: colours of the close-up's head (hair, face) that are much more common there
than in the whole card mark the character in the card art. Card backgrounds are mostly
blurred, so sharpness separates the character from look-alike scenery, and the crop goes to
the strongest connected region of that score, so it keeps the card's own background.

Pillow only, ~0.1 s per card. On a random sample of 30 cards about 9 in 10 crops landed on
the right character, nearly always on hair or face.
"""

import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

WORK_WIDTH = 420  # the card art is analysed at this width
PALETTE_COLORS = 48
MAX_ENRICHMENT = 4.0  # colour ratios above this count as "certainly the character"
REGION_SHARE = 0.8  # crop centres must lie where the region score is >= 80% of its peak
# Below this the "region" is noise (a featureless card scores ~25 from border artifacts;
# real cards measured 67-143): use an ordinary crop instead
MIN_REGION_PEAK = 40
TOP_CANDIDATES = 12  # pick among the best few, so rounds of one card differ


def _character_score(small: Image.Image, cutout: Image.Image) -> Image.Image:
    """L image: character colours (from the close-up's head) times sharpness."""
    art_q = small.quantize(
        colors=PALETTE_COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    head_src = cutout.convert("RGB").resize((150, 144), Image.BILINEAR)
    head_q = head_src.quantize(palette=art_q, dither=Image.Dither.NONE)
    w, h = head_src.size
    head = Image.new("L", (w, h), 0)
    # hair and face sit in the upper middle of the close-up
    ImageDraw.Draw(head).ellipse((w * 0.18, -h * 0.05, w * 0.82, h * 0.62), fill=255)

    in_head = head_q.histogram(mask=head)[:PALETTE_COLORS]
    in_card = art_q.histogram()[:PALETTE_COLORS]
    n_head, n_card = max(1, sum(in_head)), max(1, sum(in_card))
    levels = []
    for i in range(PALETTE_COLORS):
        enrichment = (in_head[i] / n_head) / (in_card[i] / n_card + 1e-3)
        levels.append(round(255 * min(enrichment, MAX_ENRICHMENT) / MAX_ENRICHMENT))
    likelihood = art_q.copy()
    likelihood.putpalette(
        [v for level in levels for v in (level, level, level)] + [0] * (768 - 3 * len(levels))
    )
    sharpness = (
        small.convert("L")
        .filter(ImageFilter.FIND_EDGES)
        .point(lambda v: min(255, v * 4))
        .filter(ImageFilter.MaxFilter(5))
    )
    return ImageChops.multiply(likelihood.convert("L"), sharpness)


def focus_crop_box(
    card: Image.Image, cutout: Image.Image, crop: int, rng: random.Random | None = None
) -> tuple[int, int, int, int] | None:
    """A crop x crop box (in card coordinates) on the card's character, or None if no
    convincing region was found (then use an ordinary crop)."""
    rng = rng or random
    if card.width < crop or card.height < crop:
        return None
    scale = card.width / WORK_WIDTH
    small = card.convert("RGB").resize(
        (WORK_WIDTH, max(1, round(card.height / scale))), Image.BILINEAR
    )
    size = max(2, round(crop / scale))
    if small.width <= size or small.height <= size:
        return None

    score = _character_score(small, cutout)
    local = score.filter(ImageFilter.BoxBlur(size // 2))  # a whole crop's worth
    region = local.filter(ImageFilter.BoxBlur(size))  # the character as one area

    # Only centres where a whole crop fits count, peak included: a peak at the card's
    # very edge cannot be reached, and measuring against it rejected every position.
    half, step = size // 2, max(1, size // 4)
    centres = [
        (region.getpixel((cx, cy)), local.getpixel((cx, cy)), cx, cy)
        for cy in range(half, small.height - half, step)
        for cx in range(half, small.width - half, step)
    ]
    peak = max((r for r, _, _, _ in centres), default=0)
    if peak < MIN_REGION_PEAK:
        return None
    candidates = [(lv, cx, cy) for r, lv, cx, cy in centres if r >= REGION_SHARE * peak]
    candidates.sort(reverse=True)
    _, cx, cy = rng.choice(candidates[:TOP_CANDIDATES])

    x = min(max(0, round((cx - half) * scale)), card.width - crop)
    y = min(max(0, round((cy - half) * scale)), card.height - crop)
    return (x, y, x + crop, y + crop)
