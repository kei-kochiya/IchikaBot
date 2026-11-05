import random

from PIL import Image, ImageDraw, ImageFilter

from utils.media.card_focus import focus_crop_box

CHARACTER_BOX = (1500, 300, 2000, 800)  # where the "character" is drawn on the card


def _card_with_character() -> Image.Image:
    """A blurred, colourful background with one sharp, distinctly coloured character."""
    card = Image.new("RGB", (2520, 1440), (90, 160, 210))
    draw = ImageDraw.Draw(card)
    for i in range(12):  # soft background shapes in other colours
        x = 120 + i * 190
        draw.ellipse((x, 900, x + 260, 1300), fill=(240, 200, 120))
        draw.rectangle((x, 100, x + 90, 600), fill=(60, 120, 70))
    card = card.filter(ImageFilter.GaussianBlur(18))  # card backgrounds are blurred
    draw = ImageDraw.Draw(card)
    x0, y0, x1, y1 = CHARACTER_BOX
    for yy in range(y0, y1, 25):  # sharp "hair": magenta and white stripes
        draw.rectangle((x0, yy, x1, yy + 12), fill=(220, 40, 160))
        draw.rectangle((x0, yy + 12, x1, yy + 25), fill=(250, 245, 250))
    return card


def _cutout() -> Image.Image:
    """The close-up: the character's colours fill the head area."""
    cut = Image.new("RGB", (600, 576), (90, 160, 210))
    draw = ImageDraw.Draw(cut)
    for yy in range(0, 380, 20):
        draw.rectangle((110, yy, 490, yy + 10), fill=(220, 40, 160))
        draw.rectangle((110, yy + 10, 490, yy + 20), fill=(250, 245, 250))
    return cut


def _overlap(a, b) -> float:
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return w * h / ((a[2] - a[0]) * (a[3] - a[1]))


def test_crop_lands_on_the_character():
    card, cutout = _card_with_character(), _cutout()
    for seed in range(5):
        box = focus_crop_box(card, cutout, 300, random.Random(seed))
        assert box is not None
        assert box[2] - box[0] == 300 and box[3] - box[1] == 300
        assert _overlap(box, CHARACTER_BOX) > 0.6, box  # mostly character, not scenery


def test_box_stays_inside_the_card():
    card = Image.new("RGB", (2520, 1440), (200, 30, 30))  # edge-to-edge "character"
    ImageDraw.Draw(card).rectangle((0, 0, 400, 400), fill=(250, 250, 250))
    box = focus_crop_box(card, Image.new("RGB", (600, 576), (200, 30, 30)), 300)
    if box is not None:
        x0, y0, x1, y1 = box
        assert x0 >= 0 and y0 >= 0 and x1 <= 2520 and y1 <= 1440


def test_no_convincing_region_gives_none():
    flat = Image.new("RGB", (2520, 1440), (128, 128, 128))  # nothing sharp anywhere
    assert focus_crop_box(flat, _cutout(), 300) is None
    assert focus_crop_box(Image.new("RGB", (200, 200)), _cutout(), 300) is None  # too small


def test_character_at_the_card_edge_is_still_found():
    # The region's peak lies where no whole crop can be centred: it used to reject every
    # position and fall back to a random crop
    card = Image.new("RGB", (2520, 1440), (90, 160, 210)).filter(ImageFilter.GaussianBlur(4))
    draw = ImageDraw.Draw(card)
    for yy in range(400, 1100, 25):
        draw.rectangle((2120, yy, 2520, yy + 12), fill=(220, 40, 160))
        draw.rectangle((2120, yy + 12, 2520, yy + 25), fill=(250, 245, 250))

    box = focus_crop_box(card, _cutout(), 300, random.Random(1))

    assert box is not None
    assert _overlap(box, (2120, 400, 2520, 1100)) > 0.6
