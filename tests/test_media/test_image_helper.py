import asyncio

import pytest

from utils.media import image_helper


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"\x89PNG-fake-image-bytes"):
        self.status = status
        self._body = body

    async def read(self) -> bytes:
        await asyncio.sleep(0.01)  # leave room for concurrent callers to pile up
        return self._body


class _FakeGet:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        await asyncio.sleep(0)
        return self._response

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeSession:
    """Answers every URL containing one of the configured fragments with that status."""

    def __init__(self, statuses: dict[str, int], default: int = 200):
        self.statuses = statuses
        self.default = default
        self.urls: list[str] = []

    def get(self, url: str) -> _FakeGet:
        self.urls.append(url)
        status = next((s for frag, s in self.statuses.items() if frag in url), self.default)
        return _FakeGet(_FakeResponse(status))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(image_helper, "CACHE_DIR", tmp_path)
    image_helper._inflight.clear()
    image_helper._not_found.clear()
    yield tmp_path
    image_helper._inflight.clear()
    image_helper._not_found.clear()


def _use_session(monkeypatch, session: _FakeSession):
    async def get_session():
        return session

    monkeypatch.setattr(image_helper.SharedResources, "get_session", get_session)


@pytest.mark.asyncio
async def test_downloads_and_caches_without_leaving_partial_files(cache, monkeypatch):
    session = _FakeSession({})
    _use_session(monkeypatch, session)

    path = await image_helper.get_card_image_path("res001_no001", is_trained=True)

    assert path == str(cache / "res001_no001_after_training.png")
    assert (cache / "res001_no001_after_training.png").read_bytes().startswith(b"\x89PNG")
    assert [p.name for p in cache.iterdir()] == ["res001_no001_after_training.png"]

    # Second call is served from disk
    assert await image_helper.get_card_image_path("res001_no001", is_trained=True) == path
    assert len(session.urls) == 1


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_download(cache, monkeypatch):
    session = _FakeSession({})
    _use_session(monkeypatch, session)

    paths = await asyncio.gather(*(image_helper.get_card_image_path("res002") for _ in range(8)))

    assert len(set(paths)) == 1 and paths[0] is not None
    assert len(session.urls) == 1
    assert not image_helper._inflight


@pytest.mark.asyncio
async def test_cancelling_one_waiter_does_not_abort_the_download(cache, monkeypatch):
    _use_session(monkeypatch, _FakeSession({}))

    first = asyncio.create_task(image_helper.get_card_image_path("res003"))
    second = asyncio.create_task(image_helper.get_card_image_path("res003"))
    await asyncio.sleep(0)
    first.cancel()

    with pytest.raises(asyncio.CancelledError):
        await first
    assert await second == str(cache / "res003_normal.png")


@pytest.mark.asyncio
async def test_falls_back_to_other_version_and_remembers_the_404(cache, monkeypatch):
    # Pre-trained card: only the trained art exists on the CDN
    session = _FakeSession({"card_normal": 404})
    _use_session(monkeypatch, session)

    path = await image_helper.get_card_image_path("res004", is_trained=False)
    assert path == str(cache / "res004_after_training.png")
    assert len(session.urls) == 2  # normal -> 404, then after_training -> 200

    # Next time neither the file nor the known-missing URL costs a request
    assert await image_helper.get_card_image_path("res004", is_trained=False) == path
    assert len(session.urls) == 2


@pytest.mark.asyncio
async def test_missing_everywhere_returns_none_and_is_not_retried(cache, monkeypatch):
    session = _FakeSession({}, default=404)
    _use_session(monkeypatch, session)

    assert await image_helper.get_card_image_path("res005") is None
    assert len(session.urls) == 2
    assert await image_helper.get_card_image_path("res005") is None
    assert len(session.urls) == 2


@pytest.mark.asyncio
async def test_server_errors_are_not_cached_as_missing(cache, monkeypatch):
    session = _FakeSession({}, default=500)
    _use_session(monkeypatch, session)

    assert await image_helper.get_card_image_path("res006") is None
    first_round = len(session.urls)

    assert await image_helper.get_card_image_path("res006") is None
    assert len(session.urls) == first_round * 2  # transient failures are retried


@pytest.mark.asyncio
async def test_not_found_memory_is_bounded(cache, monkeypatch):
    monkeypatch.setattr(image_helper, "_NOT_FOUND_LIMIT", 3)
    _use_session(monkeypatch, _FakeSession({}, default=404))

    for i in range(10):
        await image_helper.get_character_trim_path(i)

    assert len(image_helper._not_found) <= 3


@pytest.mark.asyncio
async def test_character_trim_is_cached(cache, monkeypatch):
    session = _FakeSession({})
    _use_session(monkeypatch, session)

    path = await image_helper.get_character_trim_path(7)

    assert path == str(cache / "chr_trim_7.webp")
    assert await image_helper.get_character_trim_path(7) == path
    assert len(session.urls) == 1
