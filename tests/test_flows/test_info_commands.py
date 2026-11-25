"""Command-flow integration tests for lookup cogs: /card, /song, /event, /profile."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import discord

from cogs.info.card import CardCog
from cogs.info.events import EventsCog
from cogs.info.profile import ProfileCog
from cogs.info.songs import SongsCog
from utils.data.card_data import card_data
from utils.data.event_data import event_data
from utils.data.game_data import character_autocomplete, game_data
from utils.data.song_data import song_data
from utils.game.cards import is_pre_trained_card, supports_trained_art


async def test_card_command_lookup_autocomplete_and_toggle(
    mock_bot, make_interaction, monkeypatch, tmp_path
):
    cog = CardCog(mock_bot)
    card_img = tmp_path / "card.webp"
    card_img.write_bytes(b"RIFFfakewebp")
    monkeypatch.setitem(
        CardCog.card_command.callback.__globals__,
        "get_card_image_path",
        AsyncMock(return_value=str(card_img)),
    )

    # Autocomplete finds EN-prefixed card
    choices = await cog.card_autocomplete(make_interaction(), "EN Test 4")
    assert any(c.value == "3" for c in choices)

    # Lookup by ID attaches cached WebP and interactive CardView
    inter = make_interaction()
    await cog.card_command.callback(cog, inter, card_name="3")
    reply = inter.last_reply
    assert isinstance(reply["embed"], discord.Embed)
    assert "EN Test 4*" in reply["embed"].title
    assert any(f.filename == "card.webp" for f in reply["files"])
    view = reply["view"]
    assert view.is_normal is True

    # Clicking Trained button toggles image & edits original response
    btn_inter = make_interaction()
    btn_inter.message = MagicMock(spec=discord.Message)
    btn_inter.message.embeds = [reply["embed"]]
    btn_inter.message.attachments = []
    await view.switch_callback(btn_inter)
    assert view.is_normal is False
    assert view.switch_button.label == "Normal"
    assert btn_inter.response.deferred is True
    assert len(btn_inter.edits) == 1

    # Lookup by text name and missing card
    inter_name = make_interaction()
    await cog.card_command.callback(cog, inter_name, card_name="Test 2*")
    assert isinstance(inter_name.last_reply["embed"], discord.Embed)

    inter_miss = make_interaction()
    await cog.card_command.callback(cog, inter_miss, card_name="does-not-exist-xyz")
    assert inter_miss.last_reply["ephemeral"] is True


async def test_song_commands_search_info_random_and_pagination(
    mock_bot, make_interaction, make_ctx, monkeypatch
):
    cog = SongsCog(mock_bot)

    # Single-result /song search returns detailed song embed
    inter = make_interaction()
    await cog.song_search.callback(cog, inter, query="Tell Your World")
    embed = inter.last_reply["embed"]
    assert embed.title == "Tell Your World"
    assert any("Master" in f.value for f in embed.fields)

    # /song info by ID and autocomplete
    choices = await cog.song_autocomplete(make_interaction(), "teru")
    assert len(choices) >= 1
    inter_info = make_interaction()
    await cog.song_info.callback(cog, inter_info, song_name="1")
    assert inter_info.last_reply["embed"].title == "Tell Your World"

    # /song random & !songr
    inter_rnd = make_interaction()
    await cog.song_random.callback(cog, inter_rnd, min_level=20, max_level=30)
    assert "Tell Your World" in inter_rnd.last_reply["embed"].title

    ctx = make_ctx()
    await cog.song_random_prefix.callback(cog, ctx)
    assert "Tell Your World" in ctx.last_reply["embed"].title

    # Multi-result search exercises SearchPaginationView next/prev buttons
    many_songs = [
        {"id": i, "title": f"Track {i}", "composer": "kz", "publishedAt": 1600000000000}
        for i in range(1, 13)
    ]
    monkeypatch.setattr(song_data, "search_songs", lambda q, limit=50: many_songs)
    ctx_search = make_ctx()
    await cog.song_prefix.callback(cog, ctx_search, query="Track")
    view = ctx_search.last_reply["view"]
    assert view.total_pages == 2 and view.current_page == 0

    nav = make_interaction()
    await view.next_callback(nav)
    assert view.current_page == 1 and len(nav.response.edits) == 1
    await view.prev_callback(make_interaction())
    assert view.current_page == 0


async def test_event_commands_current_history_and_search(
    mock_bot, make_interaction, make_ctx, monkeypatch
):
    now = int(datetime.now(UTC).timestamp() * 1000)
    day = 86_400_000
    events = [
        {
            "id": 4,
            "name": "Future Event",
            "eventType": "world_bloom",
            "startAt": now + 10 * day,
            "aggregateAt": now + 16 * day,
            "closedAt": now + 17 * day,
            "assetbundleName": "ev4",
        },
        {
            "id": 3,
            "name": "Next Event",
            "eventType": "marathon",
            "startAt": now + 2 * day,
            "aggregateAt": now + 8 * day,
            "closedAt": now + 9 * day,
            "assetbundleName": "ev3",
        },
        {
            "id": 2,
            "name": "Running Event",
            "eventType": "cheerful_carnival",
            "startAt": now - day,
            "aggregateAt": now + day,
            "closedAt": now + 2 * day,
            "assetbundleName": "ev2",
        },
        {
            "id": 1,
            "name": "Past Event",
            "eventType": "marathon",
            "startAt": now - 10 * day,
            "aggregateAt": now - 3 * day,
            "closedAt": now - 2 * day,
            "assetbundleName": "ev1",
        },
    ]
    monkeypatch.setattr(event_data, "events_jp", events)
    monkeypatch.setattr(event_data, "events_jp_by_id", {e["id"]: e for e in events})
    monkeypatch.setattr(event_data, "events_en_names", {2: "Running Event EN"})

    cog = EventsCog(mock_bot)

    # /event current prefers running event over upcoming
    inter = make_interaction()
    await cog.event_current.callback(cog, inter)
    assert inter.last_reply["embed"].title == "Running Event EN"

    # Between events -> soonest upcoming; only past -> latest past
    monkeypatch.setattr(event_data, "events_jp", [events[0], events[1], events[3]])
    assert event_data.get_current_event()["id"] == 3
    monkeypatch.setattr(event_data, "events_jp", [events[3]])
    assert event_data.get_current_event()["id"] == 1
    monkeypatch.setattr(event_data, "events_jp", events)

    # /event history returns pagination embed for closed events
    inter_hist = make_interaction()
    await cog.event_history.callback(cog, inter_hist, count=5)
    assert "Lịch sử sự kiện" in inter_hist.last_reply["embed"].title

    # !eventsearch single match vs multi match vs not found
    ctx = make_ctx()
    await cog.event_search_prefix.callback(cog, ctx, name="Running Event")
    assert ctx.last_reply["embed"].title == "Running Event EN"

    inter_multi = make_interaction()
    await cog.event_search.callback(cog, inter_multi, name="Event")
    assert inter_multi.last_reply["view"] is not None

    inter_none = make_interaction()
    await cog.event_search.callback(cog, inter_none, name="zzzz-missing")
    assert "Không tìm thấy" in inter_none.last_reply["content"]


async def test_profile_command_and_character_ranking(
    mock_bot, make_interaction, make_ctx, monkeypatch
):
    cog = ProfileCog(mock_bot)
    monkeypatch.setitem(
        ProfileCog._build_profile_kwargs.__globals__,
        "get_card_image_path",
        AsyncMock(return_value=None),
    )

    # Exact-name ranking: "an" must match Shiraishi An (10), not Minori Hanasato
    assert game_data.get_character_by_name("an")[0] == 10
    assert game_data.get_character_by_name("  An ")[0] == 10
    assert game_data.get_character_by_name("shiraishi an")[0] == 10
    assert game_data.get_character_by_name("hona")[0] == 3
    assert game_data.get_character_by_name("hosh")[0] == 1
    assert game_data.get_character_by_name("zzzz") == (None, None)
    assert len(character_autocomplete("ichi")) >= 1

    # /profile info with normal 4* card attaches toggleable CardToggleView
    inter = make_interaction()
    await cog.profile_info.callback(cog, inter, character="1")
    reply = inter.last_reply
    assert isinstance(reply["embed"], discord.Embed)
    assert "view" in reply

    # Clicking toggle button defers and edits original response
    btn = make_interaction()
    btn.message = MagicMock(spec=discord.Message)
    btn.message.embeds = [reply["embed"]]
    btn.message.attachments = []
    monkeypatch.setattr(
        "utils.media.image_helper.get_card_image_path", AsyncMock(return_value=None)
    )
    await reply["view"].toggle_callback(btn)
    assert btn.response.deferred is True and len(btn.edits) == 1

    # Pre-trained card must NOT attach an empty 0-button CardToggleView
    pre_trained = {
        "id": 99,
        "characterId": 1,
        "cardRarityType": "rarity_4",
        "prefix": "PreTrained",
        "assetbundleName": "card_099",
        "initialSpecialTrainingStatus": "done",
    }
    assert is_pre_trained_card(pre_trained) and not supports_trained_art(pre_trained)
    monkeypatch.setattr(cog, "get_random_card_for_character", lambda cid, rarity=None: pre_trained)
    ctx = make_ctx()
    await cog.profile_prefix.callback(cog, ctx, name="Ichika")
    assert "view" not in ctx.last_reply

    # Unknown character replies cleanly
    ctx_miss = make_ctx()
    await cog.profile_prefix.callback(cog, ctx_miss, name="nobody_xyz")
    assert "Không tìm thấy" in ctx_miss.last_reply["content"]
    assert len(card_data.cards) >= 1
