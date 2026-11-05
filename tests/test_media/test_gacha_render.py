from PIL import Image

from utils.media import gacha_render

CARD_ART = (504, 288)  # same 1.75 ratio as the real 2520x1440 art, but small


def _png(path, size, color, mode="RGBA"):
    Image.new(mode, size, color).save(path)
    return str(path)


def _card(rarity="rarity_4", attr="cool", trained=False):
    return {
        "cardRarityType": rarity,
        "attr": attr,
        "initialSpecialTrainingStatus": "done" if trained else "not_done",
    }


def _assets(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    assets = {
        gacha_render.BG_ASSET: _png(ui / gacha_render.BG_ASSET, (630, 360), (90, 160, 230, 255)),
        gacha_render.STAR_NORMAL: _png(ui / gacha_render.STAR_NORMAL, (72, 70), (255, 0, 0, 255)),
        gacha_render.STAR_TRAINED: _png(ui / gacha_render.STAR_TRAINED, (72, 70), (0, 0, 255, 255)),
        gacha_render.STAR_BIRTHDAY: _png(
            ui / gacha_render.STAR_BIRTHDAY, (72, 70), (0, 255, 0, 255)
        ),
    }
    for attr in gacha_render.ATTRIBUTES:
        name = f"icon_attribute_{attr}.png"
        assets[name] = _png(ui / name, (88, 88), (255, 255, 255, 255))
    return assets


def _ten_pull_size(rows=2):
    tw, th = gacha_render.TEN_PULL_TILE
    cols = gacha_render.TEN_PULL_COLS
    (gap_x, gap_y), (margin_x, margin_y) = gacha_render.TEN_PULL_GAP, gacha_render.TEN_PULL_MARGIN
    return (
        cols * tw + (cols - 1) * gap_x + 2 * margin_x,
        rows * th + (rows - 1) * gap_y + 2 * margin_y,
    )


def test_ten_pull_renders_a_jpeg_grid_and_caches_tiles(tmp_path):
    art = _png(tmp_path / "res001_no001_normal.png", CARD_ART, (200, 120, 160, 255))
    cards = [_card(r) for r in ["rarity_2"] * 6 + ["rarity_3"] * 3 + ["rarity_4"]]

    out = gacha_render.render_ten_pull(cards, [art] * 10, _assets(tmp_path))

    with Image.open(out) as img:
        assert img.format == "JPEG"
        assert img.size == _ten_pull_size()
    # The resized tile is cached for later pulls, written atomically
    tiles = list((tmp_path / "tiles").iterdir())
    assert [t.name for t in tiles] == ["res001_no001_normal_288x165.jpg"]
    # ...and so is the cropped background
    assert len(list((tmp_path / "ui").glob("bg_gacha_result_*_v3.png"))) == 1


def test_ten_pull_works_without_ui_assets_or_card_art(tmp_path):
    empty = tmp_path / "broken_normal.png"
    empty.write_bytes(b"")  # unreadable art
    cards = [_card("rarity_birthday", attr=None)] + [_card("rarity_3", attr="weird")] * 9

    out = gacha_render.render_ten_pull(cards, [None, str(empty)] + [None] * 8, {})

    with Image.open(out) as img:
        assert img.size == _ten_pull_size()


def test_stars_and_attribute_are_overlaid(tmp_path):
    assets = _assets(tmp_path)
    overlays = gacha_render._Overlays(assets, 165)
    tile = Image.new("RGB", gacha_render.TEN_PULL_TILE, (0, 0, 0))

    decorated = gacha_render._decorate(tile, _card("rarity_4", "cool"), overlays, trained=False)

    # As on the in-game result screen: four (overlapping) red stars stacked up from the
    # bottom-left corner, the white attribute icon in the top-right corner
    x = overlays.pad + overlays.star_h // 2
    red = [decorated.getpixel((x, y))[:3] == (255, 0, 0) for y in range(decorated.height)]
    star_span = overlays.star_h + 3 * round(overlays.star_h * 0.82)
    assert sum(red) >= star_span - 2
    assert not any(red[: decorated.height - star_span - overlays.pad - 2])
    w = decorated.width
    assert decorated.getpixel((w - overlays.pad - 3, overlays.pad + 2))[:3] == (255, 255, 255)
    assert decorated.getpixel((overlays.pad + 2, overlays.pad + 2))[:3] == (0, 0, 0)


def test_star_kind_follows_rarity_and_training(tmp_path):
    overlays = gacha_render._Overlays(_assets(tmp_path), 165)

    assert overlays.star("rarity_2", trained=False)[1] == 2
    star, count = overlays.star("rarity_4", trained=True)
    assert count == 4 and star.getpixel((star.width // 2, star.height // 2))[:3] == (0, 0, 255)
    star, count = overlays.star("rarity_birthday", trained=False)
    assert count == 1 and star.getpixel((star.width // 2, star.height // 2))[:3] == (0, 255, 0)
    assert gacha_render._is_trained_art({}, "/c/res001_no001_after_training.png")
    assert not gacha_render._is_trained_art({}, "/c/res001_no001_normal.png")


def test_single_pull(tmp_path):
    art = _png(tmp_path / "res002_no001_normal.png", CARD_ART, (10, 200, 10, 255))

    out = gacha_render.render_single_pull(_card(), art, _assets(tmp_path))
    with Image.open(out) as img:
        tw, th = gacha_render.SINGLE_TILE
        m = gacha_render.SINGLE_MARGIN
        assert img.size == (tw + 2 * m, th + 2 * m)

    # Unreadable or missing art (not on the CDN yet): a placeholder, never no result
    empty = tmp_path / "bad_normal.png"
    empty.write_bytes(b"")
    for path in (str(empty), None):
        with Image.open(gacha_render.render_single_pull(_card(), path, {})) as img:
            assert img.size == (tw + 2 * m, th + 2 * m)


def _fake_ui_storage(monkeypatch, slow=(), fail=(), delay=0.01):
    """In-memory stand-in for the UI image cache: a download "writes" the file."""
    import asyncio

    on_disk: set[str] = set()
    requested: list[str] = []

    async def fake_download(name, url):
        requested.append(name)
        await asyncio.sleep(delay if name in slow else 0)
        if name in fail:
            return None
        on_disk.add(name)
        return f"/cache/ui/{name}"

    def fake_cached(name):
        return f"/cache/ui/{name}" if name in on_disk else None

    monkeypatch.setattr(gacha_render, "get_ui_asset_path", fake_download)
    monkeypatch.setattr(gacha_render, "cached_ui_asset_path", fake_cached)
    monkeypatch.setattr(gacha_render, "_hq_background_download", None)
    monkeypatch.setattr(gacha_render, "_ui_download", None)
    return on_disk, requested


async def test_get_ui_assets_leaves_out_unavailable_ones(monkeypatch):
    attrs = [n for n in gacha_render.UI_ASSETS if "attribute" in n]
    _fake_ui_storage(monkeypatch, fail=attrs)

    assets = await gacha_render.get_ui_assets()

    assert gacha_render.STAR_NORMAL in assets
    assert not any("attribute" in name for name in assets)


async def test_slow_ui_downloads_do_not_hold_up_a_pull(monkeypatch):
    import asyncio
    import time

    # e.g. GitHub unreachable: the downloads would only fail after the 30 s timeout
    monkeypatch.setattr(gacha_render, "UI_ASSET_WAIT_S", 0.05)
    _fake_ui_storage(monkeypatch, slow=list(gacha_render.UI_ASSETS), delay=0.5)

    start = time.perf_counter()
    assets = await gacha_render.get_ui_assets()
    assert time.perf_counter() - start < 0.3
    assert assets == {}  # drawn with the fallbacks this time

    await asyncio.wait_for(gacha_render._ui_download, 2)  # keeps going in the background
    assert gacha_render.STAR_NORMAL in await gacha_render.get_ui_assets()


async def test_full_quality_background_is_fetched_in_the_background(monkeypatch):
    on_disk, requested = _fake_ui_storage(monkeypatch, slow=[gacha_render.BG_ASSET])

    # First pull: the small WebP stands in, nobody waits for the PNG
    first = await gacha_render.get_ui_assets()
    assert gacha_render.BG_PREVIEW_ASSET in first and gacha_render.BG_ASSET not in first
    assert gacha_render.BG_ASSET not in on_disk

    # A second pull meanwhile does not start a second download
    await gacha_render.get_ui_assets()
    assert requested.count(gacha_render.BG_ASSET) == 1

    # Once the PNG is on disk it is used, and nothing more is downloaded
    await gacha_render._hq_background_download
    requested.clear()
    later = await gacha_render.get_ui_assets()
    assert later[gacha_render.BG_ASSET] == f"/cache/ui/{gacha_render.BG_ASSET}"
    assert gacha_render.BG_PREVIEW_ASSET not in later
    assert requested == []
