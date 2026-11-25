"""
Project Sekai B30 chart constants & rating calculation.

Faithfully follows https://github.com/auburnsummer/pjskb30:
  - Primary Google Sheet CSV + Override Google Sheet CSV merged by (song_id, difficulty).
  - AP (full_perfect) -> rating = diff_constant
  - FC (full_combo)   -> rating = diff_constant - 1.0
  - Top 30 charts sorted descending by effective rating.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
import logging
import math
import socket
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import aiohttp

from config import CACHE_DIR, SharedResources

logger = logging.getLogger(__name__)

# Official pjskb30 Google Sheets CSV endpoints (auburnsummer/pjskb30/src/signals/chartConstants.ts)
PRIMARY_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1B8tX9VL2PcSJKyuHFVd2UT_8kYlY4ZdwHwg9MfWOPug/export?format=csv&gid=1855810409"
)
OVERRIDE_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1Yv3GXnCIgEIbHL72EuZ-d5q_l-auPgddWi4Efa14jq0/export?format=csv&gid=182216"
)

CONSTANTS_CACHE_TTL = 12 * 3600  # 12 hours
B30_DIFFICULTIES = frozenset({"expert", "master", "append"})
VALID_DIFFICULTIES = frozenset({"easy", "normal", "hard", "expert", "master", "append"})
_DIFF_SORT_RANK = {"expert": 1, "master": 2, "append": 3}

# Clear state ranking (highest wins per song/difficulty)
_PLAY_RESULT_RANK = {
    "not_clear": 0,
    "clear": 1,
    "full_combo": 2,
    "full_perfect": 3,
}
_PLAY_RESULT_TO_STATE = {
    "clear": "clear",
    "full_combo": "fc",
    "full_perfect": "ap",
}
_STATE_RANK = {"not_clear": 0, "clear": 1, "fc": 2, "ap": 3}


def extract_music_clears(suite: dict) -> dict[tuple[int, str], str]:
    """Extract best clear state ('ap', 'fc', 'clear') per (music_id, difficulty) from suite JSON."""
    clears: dict[tuple[int, str], str] = {}
    user_musics = suite.get("userMusics")
    if not isinstance(user_musics, list):
        return clears

    for music in user_musics:
        if not isinstance(music, dict):
            continue
        statuses = music.get("userMusicDifficultyStatuses") or []
        for status in statuses:
            if not isinstance(status, dict):
                continue
            music_id = status.get("musicId") or music.get("musicId")
            diff_raw = status.get("musicDifficulty")
            diff = str(diff_raw).strip().lower() if diff_raw is not None else ""
            if not music_id or diff not in VALID_DIFFICULTIES:
                continue
            try:
                mid = int(music_id)
            except (TypeError, ValueError):
                continue

            best_rank = 0
            best_state: str | None = None
            for result in status.get("userMusicResults") or []:
                if not isinstance(result, dict):
                    continue
                play_result = str(result.get("playResult", "")).strip().lower()
                rank = _PLAY_RESULT_RANK.get(play_result, 0)
                if rank > best_rank:
                    best_rank = rank
                    best_state = _PLAY_RESULT_TO_STATE.get(play_result)

            if best_state:
                key = (mid, diff)
                prev = clears.get(key)
                if prev is None or _STATE_RANK[best_state] > _STATE_RANK[prev]:
                    clears[key] = best_state

    return clears


@dataclass(frozen=True)
class ChartConstant:
    song_id: int
    difficulty: str  # "expert" | "master" | "append"
    constant: float
    level: str
    note_count: int
    title_en_community: str
    title_original: str


@dataclass(frozen=True)
class B30Entry:
    song_id: int
    difficulty: str  # "expert" | "master" | "append"
    clear_state: str  # "ap" | "fc"
    constant: float
    rating: float
    level: str
    note_count: int
    title: str
    assetbundle_name: str | None = None


@dataclass(frozen=True)
class B30Summary:
    entries: list[B30Entry]
    ranking: (
        float  # pjskb30 average: sum / len(entries) (matches sbotgab30 sum / 30 when len == 30)
    )
    ranking_div30: float  # strict sum / 30.0
    ap_count: int
    fc_count: int
    total_ap: int
    total_fc: int


def parse_constants_csv(csv_text: str) -> dict[tuple[int, str], ChartConstant]:
    """Parse one pjskb30 Google Sheet CSV export into {(song_id, difficulty): ChartConstant}."""
    result: dict[tuple[int, str], ChartConstant] = {}
    reader = csv.reader(io.StringIO(csv_text))
    for idx, row in enumerate(reader):
        if idx == 0 or len(row) < 7:
            continue
        raw_song_id = row[6].strip()
        raw_diff = row[5].strip().lower()
        raw_const = row[2].strip()
        if not raw_song_id or raw_diff not in B30_DIFFICULTIES or not raw_const:
            continue
        try:
            song_id = int(raw_song_id)
            constant = float(raw_const)
        except ValueError:
            continue
        if not math.isfinite(constant) or constant <= 0:
            continue

        raw_notes = row[4].strip().replace(",", "")
        try:
            note_count = int(raw_notes) if raw_notes else 0
        except ValueError:
            note_count = 0

        title_en = row[0].strip()
        title_orig = row[1].strip() or title_en
        level = row[3].strip() or str(int(constant))

        result[(song_id, raw_diff)] = ChartConstant(
            song_id=song_id,
            difficulty=raw_diff,
            constant=constant,
            level=level,
            note_count=note_count,
            title_en_community=title_en or title_orig or f"Song #{song_id}",
            title_original=title_orig or title_en or f"Song #{song_id}",
        )
    return result


def merge_constants_csvs(
    primary_csv: str, override_csv: str = ""
) -> dict[tuple[int, str], ChartConstant]:
    """Parse and merge primary + override pjskb30 CSVs (override wins on matching key)."""
    merged = parse_constants_csv(primary_csv)
    if override_csv:
        merged.update(parse_constants_csv(override_csv))
    return merged


def compute_b30(
    clears: dict[tuple[int, str], str],
    constants: dict[tuple[int, str], ChartConstant],
    *,
    song_lookup: dict[int, dict] | None = None,
    en_title_lookup: dict[int, dict] | None = None,
    limit: int = 30,
) -> B30Summary:
    """Compute B30 entries and ranking from saved clears and pjskb30 chart constants."""
    scored: list[B30Entry] = []
    total_ap = 0
    total_fc = 0

    for (song_id, diff_raw), state_raw in clears.items():
        diff = diff_raw.lower()
        state = state_raw.lower()
        if diff not in B30_DIFFICULTIES or state not in ("ap", "fc"):
            continue
        if state == "ap":
            total_ap += 1
        else:
            total_fc += 1

        chart = constants.get((song_id, diff))
        if chart is None:
            continue

        rating = chart.constant if state == "ap" else (chart.constant - 1.0)
        if rating <= 0:
            continue

        # Prefer community EN title from pjskb30; fallback to official EN/JP master data
        song_obj = song_lookup.get(song_id) if song_lookup else None
        assetbundle = song_obj.get("assetbundleName") if isinstance(song_obj, dict) else None
        title = chart.title_en_community
        if not title or title.startswith("Song #"):
            en_meta = en_title_lookup.get(song_id) if en_title_lookup else None
            if en_meta and en_meta.get("title"):
                title = en_meta["title"]
            elif isinstance(song_obj, dict) and song_obj.get("title"):
                title = song_obj["title"]

        scored.append(
            B30Entry(
                song_id=song_id,
                difficulty=diff,
                clear_state=state,
                constant=chart.constant,
                rating=round(rating, 4),
                level=chart.level,
                note_count=chart.note_count,
                title=title,
                assetbundle_name=assetbundle,
            )
        )

    scored.sort(
        key=lambda e: (
            e.rating,
            e.clear_state == "ap",
            e.constant,
            _DIFF_SORT_RANK.get(e.difficulty, 0),
            -e.song_id,
        ),
        reverse=True,
    )
    top = scored[:limit]
    total_rating = sum(e.rating for e in top)
    ranking = total_rating / len(top) if top else 0.0
    ranking_div30 = total_rating / float(limit) if limit > 0 else 0.0

    return B30Summary(
        entries=top,
        ranking=ranking,
        ranking_div30=ranking_div30,
        ap_count=sum(1 for e in top if e.clear_state == "ap"),
        fc_count=sum(1 for e in top if e.clear_state == "fc"),
        total_ap=total_ap,
        total_fc=total_fc,
    )


# ── Cached Async Loader ───────────────────────────────────────────────────────

_mem_constants: dict[tuple[int, str], ChartConstant] | None = None
_mem_fetched_at: float = 0.0
_fetch_lock = asyncio.Lock()


def _cache_path(cache_dir: Path | None = None) -> Path:
    return (cache_dir or CACHE_DIR) / "pjskb30_constants.json"


def _load_disk_cache(path: Path) -> tuple[dict[tuple[int, str], ChartConstant], float] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = float(payload.get("fetched_at", 0.0))
        items = payload.get("charts") or []
        parsed: dict[tuple[int, str], ChartConstant] = {}
        for item in items:
            cc = ChartConstant(**item)
            parsed[(cc.song_id, cc.difficulty)] = cc
        if parsed:
            return parsed, fetched_at
    except Exception as exc:
        logger.warning("Failed to load pjskb30 constants disk cache: %s", exc)
    return None


def _save_disk_cache(
    path: Path, constants: dict[tuple[int, str], ChartConstant], fetched_at: float
) -> None:
    tmp = path.with_suffix(".json.part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(
                {
                    "fetched_at": fetched_at,
                    "charts": [asdict(cc) for cc in constants.values()],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError:
        pass
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


async def get_chart_constants(
    *,
    force_refresh: bool = False,
    cache_dir: Path | None = None,
    primary_url: str = PRIMARY_CSV_URL,
    override_url: str = OVERRIDE_CSV_URL,
) -> dict[tuple[int, str], ChartConstant]:
    """Fetch and cache pjskb30 chart constants (in-memory + 12h disk cache, stale fallback)."""
    global _mem_constants, _mem_fetched_at
    now = time.time()
    use_default = (
        cache_dir is None and primary_url == PRIMARY_CSV_URL and override_url == OVERRIDE_CSV_URL
    )

    if (
        use_default
        and not force_refresh
        and _mem_constants
        and (now - _mem_fetched_at) < CONSTANTS_CACHE_TTL
    ):
        return _mem_constants

    async with _fetch_lock:
        now = time.time()
        if (
            use_default
            and not force_refresh
            and _mem_constants
            and (now - _mem_fetched_at) < CONSTANTS_CACHE_TTL
        ):
            return _mem_constants

        disk_file = _cache_path(cache_dir)
        disk_cached = await asyncio.to_thread(_load_disk_cache, disk_file)
        if not force_refresh and disk_cached is not None:
            charts, ts = disk_cached
            if (now - ts) < CONSTANTS_CACHE_TTL:
                if use_default:
                    _mem_constants, _mem_fetched_at = charts, ts
                return charts

        # Fetch fresh CSVs from Google Sheets via shared aiohttp session (with IPv4 fallback
        # for Windows hosts where IPv6 routes to docs.google.com time out).
        try:

            async def _fetch_both(session: aiohttp.ClientSession) -> tuple[str, str]:
                async def _fetch_csv(url: str) -> str:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            raise RuntimeError(f"HTTP {resp.status} fetching {url}")
                        return await resp.text(encoding="utf-8", errors="replace")

                return await asyncio.gather(_fetch_csv(primary_url), _fetch_csv(override_url))

            try:
                primary_text, override_text = await _fetch_both(await SharedResources.get_session())
            except (aiohttp.ClientConnectorError, TimeoutError, OSError):
                async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(family=socket.AF_INET),
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as ipv4_session:
                    primary_text, override_text = await _fetch_both(ipv4_session)

            merged = merge_constants_csvs(primary_text, override_text)
            if not merged:
                raise RuntimeError("Parsed 0 chart constants from pjskb30 CSVs")

            await asyncio.to_thread(_save_disk_cache, disk_file, merged, now)
            if use_default:
                _mem_constants, _mem_fetched_at = merged, now
            logger.info("pjskb30: Loaded %d chart constants.", len(merged))
            return merged
        except Exception as exc:
            logger.warning("pjskb30: Failed to fetch fresh chart constants: %s", exc)
            if disk_cached is not None:
                charts, ts = disk_cached
                if use_default:
                    _mem_constants, _mem_fetched_at = charts, ts
                return charts
            if use_default and _mem_constants:
                return _mem_constants
            raise
