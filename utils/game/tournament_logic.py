import asyncio
import logging
import random
from io import BytesIO

from PIL import Image, ImageOps

from utils.media.image_helper import get_card_image_path

logger = logging.getLogger(__name__)

CROP_BASE = 400  # base crop size (also phase 3)
CROP_P2 = 300  # phase 2 crop (colour, centred in base)
CROP_P1 = 250  # phase 1 crop (grayscale, centred in base)


def _create_phase_images_sync(path: str) -> tuple[BytesIO | None, BytesIO | None, BytesIO | None]:
    """Synchronous helper for generating progressive hint images."""
    try:
        with Image.open(path) as img:
            img = img.convert("RGBA")
            w, h = img.size

            # Scale up if needed
            if w < CROP_BASE or h < CROP_BASE:
                scale = max(CROP_BASE / w, CROP_BASE / h)
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
                w, h = img.size

            # Random base 400×400 region
            bx = random.randint(0, w - CROP_BASE)
            by = random.randint(0, h - CROP_BASE)
            base = img.crop((bx, by, bx + CROP_BASE, by + CROP_BASE))

            def centre_crop(src: Image.Image, size: int) -> Image.Image:
                off = (CROP_BASE - size) // 2
                return src.crop((off, off, off + size, off + size))

            p1_colour = centre_crop(base, CROP_P1)
            p1 = ImageOps.grayscale(p1_colour)
            p2 = centre_crop(base, CROP_P2)
            p3 = base.copy()

            def to_buf(image: Image.Image) -> BytesIO:
                buf = BytesIO()
                image.save(buf, format="PNG")
                buf.seek(0)
                return buf

            return to_buf(p1), to_buf(p2), to_buf(p3)

    except Exception as e:
        logger.error("Tournament: Image generation failed for %s: %s", path, e)
        return None, None, None


async def make_phase_images(
    asset_name: str,
) -> tuple[BytesIO | None, BytesIO | None, BytesIO | None]:
    """
    Generate the three progressive hint images for a card.

    Strategy:
      1. Pick a random 400×400 base crop from the card.
      2. Phase 1 (250×250): centre of base, grayscale.
      3. Phase 2 (300×300): centre of base, colour.
      4. Phase 3 (400×400): the full base crop, colour.

    All three share the same centre point so later phases always reveal
    more context around the same spot seen in phase 1.
    """
    # Try trained art first, fall back to normal
    path = await get_card_image_path(asset_name, is_trained=True)
    if not path:
        path = await get_card_image_path(asset_name, is_trained=False)
    if not path:
        return None, None, None

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _create_phase_images_sync, path)
