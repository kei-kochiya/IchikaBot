import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from utils.core.autoupdater import AutoUpdater, DataSource, auto_updater, register_all_sources


def test_datasource_registration_whitelist():
    updater = AutoUpdater()
    valid_source = DataSource(
        name="test_valid",
        url="https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/master/cards.json",
        local_path=Path("dummy.json"),
    )
    invalid_source = DataSource(
        name="test_invalid",
        url="https://malicious.example.com/cards.json",
        local_path=Path("dummy.json"),
    )

    assert updater.register(valid_source) is True
    assert "test_valid" in updater.sources

    assert updater.register(invalid_source) is False
    assert "test_invalid" not in updater.sources


def test_needs_update_logic():
    updater = AutoUpdater()

    # None current data always needs update
    assert updater._needs_update(None, [1, 2, 3]) is True

    # List comparison by length
    assert updater._needs_update([1, 2], [1, 2, 3]) is True
    assert updater._needs_update([1, 2, 3], [1, 2, 3]) is False

    # Dict comparison by key count
    assert updater._needs_update({"a": 1}, {"a": 1, "b": 2}) is True
    assert updater._needs_update({"a": 1}, {"a": 1}) is False


@pytest.mark.asyncio
async def test_register_all_sources():
    await register_all_sources()
    assert len(auto_updater.sources) >= 8
    assert "cards_jp" in auto_updater.sources
    assert "cards_en" in auto_updater.sources
    assert "musics_jp" in auto_updater.sources
    assert "events_jp" in auto_updater.sources


# ── End-to-end behaviour against a local server that mimics raw.githubusercontent.com ──


@pytest.fixture
async def remote(tmp_path):
    """A local HTTP server honouring ETag / If-None-Match, plus an updater pointed at it."""
    state = {"body": b"[]", "etag": '"v1"', "status": 200, "if_none_match": [], "hits": 0}

    async def handler(request):
        state["hits"] += 1
        state["if_none_match"].append(request.headers.get("If-None-Match"))
        if state["status"] != 200:
            return web.Response(status=state["status"])
        etag = state["etag"]
        if etag and request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers={"ETag": etag})
        headers = {"Content-Type": "text/plain; charset=utf-8"}
        if etag:
            headers["ETag"] = etag
        return web.Response(body=state["body"], headers=headers)

    app = web.Application()
    app.router.add_get("/data.json", handler)
    server = TestServer(app)
    await server.start_server()

    local = tmp_path / "data" / "data.json"
    state_file = tmp_path / "state.json"

    def make_updater() -> AutoUpdater:
        updater = AutoUpdater(state_file=state_file)
        # Bypass the URL whitelist: the point here is the download/replace behaviour
        updater.sources["demo"] = DataSource("demo", str(server.make_url("/data.json")), local)
        return updater

    yield SimpleNamespace(state=state, local=local, make_updater=make_updater)
    await server.close()


def _write_remote(remote, items, etag='"v1"'):
    remote.state["body"] = json.dumps(items).encode()
    remote.state["etag"] = etag


@pytest.mark.asyncio
async def test_first_run_installs_file_then_conditional_request_skips_download(remote):
    updater = remote.make_updater()
    _write_remote(remote, [{"id": 1}, {"id": 2}])

    ok, msg = await updater.check_and_update("demo")
    assert ok
    assert msg == "Updated: 0 -> 2 items"
    assert json.loads(remote.local.read_text(encoding="utf-8")) == [{"id": 1}, {"id": 2}]
    assert not remote.local.with_name("data.json.part").exists()

    # Second run: the stored ETag is sent back and the server answers 304 (no body)
    ok, msg = await updater.check_and_update("demo")
    assert (ok, msg) == (True, "Already up to date")
    assert remote.state["if_none_match"][-1] == '"v1"'


@pytest.mark.asyncio
async def test_etag_survives_restart(remote):
    _write_remote(remote, [{"id": 1}])
    await remote.make_updater().check_and_update("demo")

    # A brand-new updater (i.e. after a bot restart) must still send If-None-Match
    ok, msg = await remote.make_updater().check_and_update("demo")
    assert (ok, msg) == (True, "Already up to date")
    assert remote.state["if_none_match"][-1] == '"v1"'


@pytest.mark.asyncio
async def test_edit_that_keeps_the_item_count_is_detected(remote):
    updater = remote.make_updater()
    _write_remote(remote, [{"id": 1, "name": "old"}])
    await updater.check_and_update("demo")

    _write_remote(remote, [{"id": 1, "name": "new"}], etag='"v2"')
    ok, msg = await updater.check_and_update("demo")

    assert ok
    assert msg == "Updated: 1 -> 1 items"
    assert json.loads(remote.local.read_text(encoding="utf-8"))[0]["name"] == "new"


@pytest.mark.asyncio
async def test_server_without_etag_falls_back_to_content_hash(remote):
    updater = remote.make_updater()
    _write_remote(remote, [{"id": 1}], etag=None)

    ok, msg = await updater.check_and_update("demo")
    assert ok
    assert msg.startswith("Updated")

    # Body is downloaded again (no ETag to ask about), but identical content is not reinstalled
    ok, msg = await updater.check_and_update("demo")
    assert (ok, msg) == (True, "Already up to date")
    assert remote.state["hits"] == 2


@pytest.mark.asyncio
async def test_invalid_json_is_rejected_and_existing_file_kept(remote):
    updater = remote.make_updater()
    _write_remote(remote, [{"id": 1}])
    await updater.check_and_update("demo")
    original = remote.local.read_text(encoding="utf-8")

    remote.state["body"] = b'[{"id": 1}, {"id": 2, oops'
    remote.state["etag"] = '"v2"'
    ok, msg = await updater.check_and_update("demo")

    assert not ok
    assert msg.startswith("Invalid JSON")
    assert remote.local.read_text(encoding="utf-8") == original
    assert not remote.local.with_name("data.json.part").exists()


@pytest.mark.asyncio
async def test_empty_dataset_is_rejected(remote):
    updater = remote.make_updater()
    _write_remote(remote, [{"id": 1}])
    await updater.check_and_update("demo")

    _write_remote(remote, [], etag='"v2"')
    ok, msg = await updater.check_and_update("demo")

    assert not ok
    assert "empty" in msg
    assert json.loads(remote.local.read_text(encoding="utf-8")) == [{"id": 1}]


@pytest.mark.asyncio
async def test_http_error_is_reported_without_touching_files(remote):
    updater = remote.make_updater()
    remote.state["status"] = 500

    ok, msg = await updater.check_and_update("demo")

    assert (ok, msg) == (False, "HTTP 500")
    assert not remote.local.exists()


@pytest.mark.asyncio
async def test_unknown_source():
    ok, msg = await AutoUpdater().check_and_update("nope")
    assert not ok
    assert "Unknown source" in msg


@pytest.mark.asyncio
async def test_busy_flag_reflects_running_update(remote):
    updater = remote.make_updater()
    assert updater.busy is False
    async with updater._lock:
        assert updater.busy is True
    assert updater.busy is False
