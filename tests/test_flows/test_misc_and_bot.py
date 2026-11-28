"""Integration tests for GasPriceCog, MercariCog (local TestServer), and bot.py event routing."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from aiohttp import web
from aiohttp.test_utils import TestServer
from discord import app_commands
from discord.ext import commands

import bot as bot_module
from cogs.misc.gas_price import (
    _VN_TZ,
    GasPriceCog,
    _is_fresh,
    _load_cache,
)
from cogs.misc.mercari import MercariCog, _compute_vnd_price
from utils.mercari_scraper import AsyncMercariScraper
from utils.mercari_scraper.shops_client import AsyncShopsClient
from utils.mercari_scraper.urls import extract_item_info

# ── GasPriceCog (end-to-end against local aiohttp TestServer) ─────────────────


async def test_gas_price_end_to_end_cache_and_fallback(mock_bot, tmp_path, monkeypatch):
    state = {
        "status": 200,
        "hits": 0,
        "objects": [
            {
                "Title": "Xăng RON 95",
                "Zone1Price": 22000,
                "Zone2Price": 22440,
                "LastModified": "2026-10-08T07:56:43.586Z",
                "DIsplayOrder": 2,
            },
            {
                "Title": "Xăng E5 RON 92",
                "Zone1Price": 21000,
                "Zone2Price": 21420,
                "LastModified": "2026-10-08T07:57:05.107Z",
                "DIsplayOrder": 1,
            },
        ],
    }

    async def handler(_request):
        state["hits"] += 1
        if state["status"] != 200:
            return web.Response(status=state["status"])
        return web.json_response({"Objects": state["objects"]})

    app = web.Application()
    app.router.add_get("/prices", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        monkeypatch.setattr("cogs.misc.gas_price._API_URL", str(server.make_url("/prices")))
        cache_file = tmp_path / "gas_cache.json"
        cog = GasPriceCog(mock_bot, cache_file=cache_file)

        # Cold miss -> fetches from TestServer, sorts by DIsplayOrder, writes atomic disk cache
        embed = await cog._price_embed()
        assert isinstance(embed, discord.Embed)
        assert [f.name for f in embed.fields] == ["Xăng E5 RON 92", "Xăng RON 95"]
        assert "21,000 đ" in embed.fields[0].value
        assert state["hits"] == 1
        assert _load_cache(cache_file) is not None

        # Warm hit (same day/slot) -> zero HTTP requests
        await cog._price_embed()
        assert state["hits"] == 1

        # Stale memory + disk cache + HTTP 500 -> hits upstream and falls back to stale data
        cog._cache["date"] = "2020-01-01"
        cache_file.write_text('{"date": "2020-01-01", "products": []}', encoding="utf-8")
        state["status"] = 500
        fallback = await cog._price_embed()
        assert isinstance(fallback, discord.Embed) and state["hits"] == 2

        # No cache + HTTP 500 -> helpful error message
        fresh_cog = GasPriceCog(mock_bot, cache_file=tmp_path / "empty.json")
        err = await fresh_cog._price_embed()
        assert isinstance(err, str) and "Thử lại" in err
    finally:
        await server.close()


def test_gas_price_15h_refresh_window():
    def at(hour):
        return datetime(2026, 11, 5, hour, 30, tzinfo=_VN_TZ)

    morning = {"date": "2026-11-05", "fetched_hour": 9, "products": [{"Title": "RON 95"}]}
    evening = {**morning, "fetched_hour": 16}

    assert _is_fresh(morning, at(14))
    assert not _is_fresh(morning, at(15))
    assert _is_fresh(evening, at(20))
    assert not _is_fresh({**evening, "date": "2026-11-04"}, at(10))
    assert not _is_fresh(None, at(10))


# ── MercariCog (Shops via local TestServer + C2C lookup) ──────────────────────


async def test_mercari_lookup_shops_via_test_server_and_c2c(mock_bot, make_interaction, make_ctx):
    assert (
        extract_item_info("https://jp.mercari.com/item/m12345678901?source=shared")[0]
        == "m12345678901"
    )
    assert (
        extract_item_info("https://jp.mercari.com/shops/product/2JXEJvn8QLxnZwwEJZ4RfK")[0]
        == "2JXEJvn8QLxnZwwEJZ4RfK"
    )
    assert _compute_vnd_price(1000, 999999999999) == 192_000
    assert _compute_vnd_price(1000, 304351602637012992) == 190_000

    # Local GraphQL server for Mercari Shops
    async def graphql_handler(request):
        body = await request.json()
        pid = body["variables"]["id"]
        if pid == "missing_id":
            return web.json_response({"data": {"product": None}})
        return web.json_response(
            {
                "data": {
                    "product": {
                        "id": pid,
                        "name": "Miku Nendoroid",
                        "price": 10000,
                        "inStock": False,
                        "assets": [{"id": "a1", "imageUrl": "https://example.com/miku.jpg"}],
                    }
                }
            }
        )

    app = web.Application()
    app.router.add_post("/graphql", graphql_handler)
    server = TestServer(app)
    await server.start_server()
    try:
        scraper = AsyncMercariScraper()
        scraper._shops_client = AsyncShopsClient(graphql_url=str(server.make_url("/graphql")))
        cog = MercariCog(mock_bot)
        cog._scraper = scraper

        # /mercari with Shops URL (preferred rate user) — never initializes C2C client
        inter = make_interaction(user_id=304351602637012992)
        await cog.slash_mercari.callback(
            cog, inter, link="https://jp.mercari.com/shops/product/shop123"
        )
        embed = inter.last_reply["embed"]
        assert embed.title == "Miku Nendoroid"
        assert embed.color == discord.Color.red()
        assert embed.fields[1].value == "1,810,000 VND"
        assert "Mercari Shops" in embed.footer.text
        assert scraper._c2c_client is None  # Shops-only lookup never touched mercapi!

        # Not found Shops product -> ephemeral string
        inter_miss = make_interaction()
        await cog.slash_mercari.callback(
            cog, inter_miss, link="https://jp.mercari.com/shops/product/missing_id"
        )
        assert inter_miss.last_reply["ephemeral"] is True
        assert "Không tìm thấy" in inter_miss.last_reply["content"]

        # !mercari with C2C item (exercises AsyncC2CClient parsing & cleanup without network)
        from types import SimpleNamespace

        from utils.mercari_scraper.c2c_client import AsyncC2CClient

        c2c = object.__new__(AsyncC2CClient)
        fake_http = MagicMock(is_closed=False, aclose=AsyncMock())
        c2c._mercapi = SimpleNamespace(
            _client=fake_http,
            item=AsyncMock(
                return_value=SimpleNamespace(
                    id_="m12345678901",
                    name="Ichika Badge",
                    price=5000,
                    status="ITEM_STATUS_ON_SALE",
                    photos=["https://example.com/1.jpg", "https://example.com/2.jpg"],
                    thumbnails=[],
                    seller_id="s1",
                    created=None,
                )
            ),
        )
        scraper._c2c_client = c2c

        ctx = make_ctx(user_id=123)
        await cog.prefix_mercari.callback(cog, ctx, link="m12345678901")
        c2c_embed = ctx.last_reply["embed"]
        assert c2c_embed.title == "Ichika Badge"
        assert c2c_embed.color == discord.Color.green()
        assert c2c_embed.fields[1].value == "920,000 VND"
        assert "2 ảnh • Mercari C2C" in c2c_embed.footer.text

        await cog.cog_unload()
        fake_http.aclose.assert_awaited_once()

        # Unexpected slash invoke errors are left to bot.py's global tree handler
        err_inter = make_interaction()
        err_inter.response._done = True
        await cog.slash_mercari_error(
            err_inter, app_commands.CommandInvokeError(MagicMock(name="mercari"), ValueError())
        )
        assert not err_inter.all_replies
    finally:
        await server.close()


# ── bot.py event & error routing ──────────────────────────────────────────────


async def test_bot_message_routing_ready_sync_and_error_handlers(make_interaction):
    # Bot messages & -g guesses skip process_commands; normal commands go through
    for content, is_bot, should_process in (
        ("-g test", True, False),
        ("-g ichika", False, False),
        ("-G miku", False, False),
        ("-g", False, False),
        ("!help", False, True),
        ("-sg", False, True),
    ):
        msg = MagicMock(spec=discord.Message)
        msg.author.bot = is_bot
        msg.content = content
        with patch("bot.bot.process_commands", new_callable=AsyncMock) as proc:
            await bot_module.on_message(msg)
            assert proc.called is should_process

    # on_ready syncs slash commands only once across reconnects
    bot_module._commands_synced = False
    with (
        patch.object(bot_module.bot.tree, "sync", new_callable=AsyncMock, return_value=[]) as sync,
        patch.object(type(bot_module.bot), "user", MagicMock()),
    ):
        await bot_module.on_ready()
        await bot_module.on_ready()
    sync.assert_awaited_once()

    # Global slash error handler: deferred -> followup, non-deferred -> response, CheckFailure once
    invoke_err = app_commands.CommandInvokeError(MagicMock(name="pull"), ValueError("boom"))
    deferred = make_interaction()
    deferred.response._done = True
    with patch("bot.logger.error") as log_err:
        await bot_module.bot.tree.on_error(deferred, invoke_err)
    assert deferred.followup.messages[0]["ephemeral"] is True
    assert isinstance(log_err.call_args.kwargs["exc_info"], ValueError)

    fresh = make_interaction()
    with patch("bot.logger.error"):
        await bot_module.bot.tree.on_error(fresh, invoke_err)
    assert len(fresh.response.messages) == 1 and not fresh.followup.messages

    handled_check = make_interaction()
    handled_check.response._done = True
    await bot_module.bot.tree.on_error(
        handled_check, app_commands.MissingPermissions(["manage_guild"])
    )
    assert not handled_check.all_replies

    unhandled_check = make_interaction()
    await bot_module.bot.tree.on_error(
        unhandled_check, app_commands.MissingPermissions(["administrator"])
    )
    assert len(unhandled_check.response.messages) == 1

    # Global prefix error handler: ignores CommandNotFound/CheckFailure, reports NoPrivateMessage & bugs
    ctx = MagicMock(spec=commands.Context)
    ctx.command = MagicMock()
    ctx.send = AsyncMock()
    with patch("bot.logger.error") as log_err:
        await bot_module.on_command_error(ctx, commands.CommandNotFound())
        await bot_module.on_command_error(ctx, commands.NotOwner())
        log_err.assert_not_called()
        ctx.send.assert_not_called()

    await bot_module.on_command_error(ctx, commands.NoPrivateMessage())
    ctx.send.assert_awaited_once()
    ctx.send.reset_mock()

    boom = RuntimeError("boom")
    with patch("bot.logger.error") as log_err:
        await bot_module.on_command_error(ctx, commands.CommandInvokeError(boom))
    ctx.send.assert_awaited_once()
    assert log_err.call_args.kwargs["exc_info"] is boom
