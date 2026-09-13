from pathlib import Path
import pytest
from utils.core.autoupdater import AutoUpdater, DataSource, register_all_sources, auto_updater


def test_datasource_registration_whitelist():
    updater = AutoUpdater()
    valid_source = DataSource(
        name="test_valid",
        url="https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/master/cards.json",
        local_path=Path("dummy.json")
    )
    invalid_source = DataSource(
        name="test_invalid",
        url="https://malicious.example.com/cards.json",
        local_path=Path("dummy.json")
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
    assert len(auto_updater.sources) >= 10
    assert "cards_jp" in auto_updater.sources
    assert "cards_en" in auto_updater.sources
    assert "musics_jp" in auto_updater.sources
    assert "events_jp" in auto_updater.sources
    assert "stamps_jp" in auto_updater.sources
