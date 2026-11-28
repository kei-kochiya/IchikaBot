"""Component tests for PJSK crypto, pjskb30 constants/rating, Pillow B30 renderer, and DB CRUD."""

from __future__ import annotations

import base64
import json
import time

import pytest
from PIL import Image

from utils.core import database
from utils.pjsk.b30_render import HEIGHT, WIDTH, render_b30_image
from utils.pjsk.client import (
    PJSKInvalidTransferError,
    build_cookie_header,
    generate_transfer_password,
    parse_profile_summary,
    parse_transfer_preview,
    validate_transfer_id,
)
from utils.pjsk.constants import (
    ChartConstant,
    compute_b30,
    extract_music_clears,
    get_chart_constants,
    merge_constants_csvs,
    parse_constants_csv,
)
from utils.pjsk.crypto import (
    decode_jwt_payload,
    decode_jwt_user_id,
    decrypt_bytes,
    decrypt_unpack,
    pack_encrypt,
    pjsk_id_to_created_ts,
    sign_inherit_jwt,
)


def _make_fake_jwt(payload: dict) -> str:
    h = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{h}.{p}.sig"


def test_pjsk_crypto_roundtrip_and_jwt_helpers():
    sample = {
        "userId": 123456789012345678,
        "name": "Ichika",
        "ratio": 1.5,
        "nested": [{"playResult": "full_perfect"}],
    }
    for region in ("en", "jp"):
        blob = pack_encrypt(sample, region)
        assert isinstance(blob, bytes) and len(blob) % 16 == 0
        decoded = decrypt_unpack(blob, region)
        assert decoded["userId"] == sample["userId"]
        assert decoded["name"] == "Ichika"
        assert abs(decoded["ratio"] - 1.5) < 1e-5
        assert decoded["nested"] == sample["nested"]

    # Empty payload encrypts and decrypts cleanly for both regions
    for region in ("en", "jp"):
        assert decrypt_bytes(pack_encrypt(None, region), region) == b""

    with pytest.raises(ValueError):
        pack_encrypt({}, "kr")

    # HS256 inherit token + JWT userId extraction
    jwt_tok = sign_inherit_jwt("AbCdEfGh12345678", "Pass1234", "my-secret")
    claims = decode_jwt_payload(jwt_tok)
    assert claims == {"inheritId": "AbCdEfGh12345678", "password": "Pass1234"}
    assert (
        decode_jwt_user_id(_make_fake_jwt({"userId": "819436380471005188"})) == 819436380471005188
    )
    assert pjsk_id_to_created_ts(819436380471005188) is not None
    assert pjsk_id_to_created_ts(0) is None


def test_client_pure_parsers_and_password_generator():
    for _ in range(10):
        pw = generate_transfer_password(12)
        assert len(pw) == 12
        assert pw.isalnum()
        assert any(c.isupper() for c in pw)
        assert any(c.islower() for c in pw)
        assert any(c.isdigit() for c in pw)

    cookie = build_cookie_header(
        [
            "CloudFront-Policy=abc123; Path=/; Secure, CloudFront-Signature=sig999; Path=/; HttpOnly",
            "CloudFront-Key-Pair-Id=KP1; Domain=.sekai.colorfulpalette.org",
        ]
    )
    assert "CloudFront-Policy=abc123" in cookie
    assert "CloudFront-Signature=sig999" in cookie
    assert "CloudFront-Key-Pair-Id=KP1" in cookie
    assert "Path=" not in cookie

    # Duplicate cookie names keep the newest value
    newest = build_cookie_header(["CloudFront-Policy=old; Path=/", "CloudFront-Policy=new; Path=/"])
    assert newest == "CloudFront-Policy=new"

    # SEGA JP /api/signature packs all 3 CloudFront cookies semicolon-delimited in one Set-Cookie header
    jp_sig = build_cookie_header(
        [
            "CloudFront-Policy=pol123; CloudFront-Signature=sig456; CloudFront-Key-Pair-Id=KP789; Path=/;"
        ]
    )
    assert (
        jp_sig
        == "CloudFront-Policy=pol123; CloudFront-Signature=sig456; CloudFront-Key-Pair-Id=KP789"
    )

    # Transfer ID validation rejects path/query injection characters
    assert validate_transfer_id("  AbCdEfGh12345678 ") == "AbCdEfGh12345678"
    for bad_tid in ("short", "AbCdEfGh1234567/", "AbCdEfGh1234567?", "AbCdEfGh1234567#"):
        with pytest.raises(PJSKInvalidTransferError):
            validate_transfer_id(bad_tid)

    # Suite clear extraction picks highest clear rank per (musicId, difficulty)
    suite = {
        "userMusics": [
            {
                "musicId": 1,
                "userMusicDifficultyStatuses": [
                    {
                        "musicId": 1,
                        "musicDifficulty": "master",
                        "userMusicResults": [
                            {"playResult": "clear"},
                            {"playResult": "full_perfect"},
                            {"playResult": "full_combo"},
                        ],
                    },
                    {
                        "musicId": 1,
                        "musicDifficulty": "expert",
                        "userMusicResults": [{"playResult": "full_combo"}],
                    },
                    {
                        "musicId": 1,
                        "musicDifficulty": "hard",
                        "userMusicResults": [{"playResult": "not_clear"}],
                    },
                ],
            }
        ]
    }
    clears = extract_music_clears(suite)
    assert clears == {(1, "master"): "ap", (1, "expert"): "fc"}

    # Modern PJSK v5/v6 top-level userMusicResults with musicDifficultyType & boolean flags
    v6_suite = {
        "userMusics": [{"musicId": 1}, {"musicId": 2}],
        "userMusicResults": [
            {
                "musicId": 1,
                "musicDifficultyType": "append",
                "playType": "multi",
                "playResult": "clear",
                "fullComboFlg": False,
                "fullPerfectFlg": False,
            },
            {
                "musicId": 1,
                "musicDifficultyType": "master",
                "playType": "solo",
                "playResult": "clear",
                "fullComboFlg": True,
                "fullPerfectFlg": False,
            },
            {
                "musicId": 1,
                "musicDifficultyType": "master",
                "playType": "multi",
                "playResult": "full_perfect",
                "fullComboFlg": True,
                "fullPerfectFlg": True,
            },
            {
                "musicId": 2,
                "musicDifficultyType": "expert",
                "playResult": "not_clear",
                "fullComboFlg": False,
                "fullPerfectFlg": False,
            },
        ],
    }
    assert extract_music_clears(v6_suite) == {
        (1, "append"): "clear",
        (1, "master"): "ap",
    }

    prof = parse_profile_summary(
        {
            "user": {"userId": 999, "name": "Hoshino", "rank": 250},
            "userProfile": {"word": "ICHIKA-ABC123"},
            "totalPower": {"totalPower": 321000},
            "userMusicDifficultyClearCount": [
                {
                    "musicDifficultyType": "master",
                    "liveClear": 400,
                    "fullCombo": 300,
                    "allPerfect": 50,
                }
            ],
        }
    )
    assert prof.user_id == 999
    assert prof.name == "Hoshino"
    assert prof.bio == "ICHIKA-ABC123"
    assert prof.total_power == 321000
    assert prof.clear_counts["master"] == {"clear": 400, "fc": 300, "ap": 50}

    preview_ok = parse_transfer_preview(
        {
            "afterUserGamedata": {"userId": 999, "name": "Hoshino", "rank": 250},
            "userEventDeviceTransferRestrict": {"isRestrictDeviceTransfer": False},
        }
    )
    assert preview_ok.user_id == 999 and preview_ok.is_restricted is False

    preview_blocked = parse_transfer_preview(
        {
            "afterUserGamedata": {"userId": 999, "name": "Hoshino", "rank": 250},
            "userEventDeviceTransferRestrict": {"isRestrictDeviceTransfer": True},
        }
    )
    assert preview_blocked.is_restricted is True


def test_pjskb30_csv_parsing_override_and_rating_formula():
    primary_csv = (
        "Song,Original,Constant,Level,Note Count,Difficulty,Song ID,Notes\n"
        "Tell Your World,Tell Your World,26.4,26,800,Master,1,\n"
        "The Intense Voice,初音ミクの激唱,33.5,33,1500,Master,10,\n"
        "The Intense Voice,初音ミクの激唱,30.2,30,1100,Expert,10,\n"
        "Tell Your World,Tell Your World,31.0,31,1200,Append,1,\n"
        "Bad Row,Bad,NaN,30,500,Master,99,\n"
        "Missing ID,Missing,29.0,29,500,Master,,\n"
    )
    override_csv = (
        "Song,Original,Constant,Level,Note Count,Difficulty,Song ID,Notes\n"
        "The Intense Voice,初音ミクの激唱,33.8,33,1500,Master,10,\n"
    )
    parsed = parse_constants_csv(primary_csv)
    assert len(parsed) == 4
    assert parsed[(10, "master")].constant == 33.5

    merged = merge_constants_csvs(primary_csv, override_csv)
    assert merged[(10, "master")].constant == 33.8  # overridden!

    clears = {
        (10, "master"): "fc",  # 33.8 - 1.0 = 32.8
        (1, "append"): "ap",  # 31.0
        (10, "expert"): "ap",  # 30.2
        (1, "master"): "clear",  # ignored in B30
    }
    summary = compute_b30(clears, merged)
    assert [e.song_id for e in summary.entries] == [10, 1, 10]
    assert [e.rating for e in summary.entries] == [32.8, 31.0, 30.2]
    assert summary.ap_count == 2 and summary.fc_count == 1
    assert abs(summary.ranking - ((32.8 + 31.0 + 30.2) / 3)) < 1e-6


async def test_get_chart_constants_uses_disk_cache(tmp_path):
    cache_file = tmp_path / "pjskb30_constants.json"
    cache_file.write_text(
        json.dumps(
            {
                "fetched_at": time.time(),
                "charts": [
                    {
                        "song_id": 1,
                        "difficulty": "master",
                        "constant": 27.5,
                        "level": "27",
                        "note_count": 900,
                        "title_en_community": "Tell Your World",
                        "title_original": "Tell Your World",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    charts = await get_chart_constants(cache_dir=tmp_path)
    assert charts[(1, "master")].constant == 27.5


def test_render_b30_image_produces_valid_1000x1500_jpeg(tmp_path):
    # Create a real synthetic jacket image for song 1; leave song 2 missing to exercise placeholder
    jacket_path = tmp_path / "jacket_s_001.webp"
    Image.new("RGB", (256, 256), (90, 140, 230)).save(jacket_path, "WEBP")

    constants = {
        (i, diff): ChartConstant(
            song_id=i,
            difficulty=diff,
            constant=30.0 + (i % 6) * 0.4,
            level="31",
            note_count=1000,
            title_en_community=f"Very Long Project Sekai Song Title Number {i} feat. Hatsune Miku",
            title_original=f"楽曲タイトル {i}",
        )
        for i, diff in [
            (1, "append"),
            (2, "master"),
            (3, "expert"),
            (4, "append"),
        ]
    }
    clears = {
        (1, "append"): "ap",
        (2, "master"): "fc",
        (3, "expert"): "ap",
        (4, "append"): "fc",
    }
    summary = compute_b30(clears, constants)
    buf = render_b30_image(
        summary,
        {1: str(jacket_path), 2: None},
        player_name="Ichika Hoshino",
        region="jp",
    )
    with Image.open(buf) as im:
        assert im.format == "JPEG"
        assert im.size == (WIDTH, HEIGHT)

    # Empty state also renders cleanly
    empty_summary = compute_b30({}, constants)
    empty_buf = render_b30_image(empty_summary, {}, player_name="Newbie", region="en")
    with Image.open(empty_buf) as im:
        assert im.size == (WIDTH, HEIGHT)


async def test_database_pjsk_tables_crud(temp_db):
    assert await database.get_pjsk_link(101, "en") is None

    await database.set_pjsk_link(101, "en", 555001, "Ichika", 1700000000.0)
    link = await database.get_pjsk_link(101, "en")
    assert link is not None and link["pjsk_user_id"] == 555001
    assert (await database.get_pjsk_link_by_game_id("en", 555001))["discord_id"] == 101

    await database.replace_pjsk_clears(
        101,
        "en",
        {(1, "master"): "ap", (2, "expert"): "fc"},
        pjsk_name="Ichika Updated",
        synced_at=1700000500.0,
    )
    assert await database.get_pjsk_clears(101, "en") == {(1, "master"): "ap", (2, "expert"): "fc"}
    updated_link = await database.get_pjsk_link(101, "en")
    assert updated_link["pjsk_name"] == "Ichika Updated"
    assert updated_link["synced_at"] == 1700000500.0

    # Re-linking to a different PJSK user ID wipes stale clears & resets synced_at
    await database.set_pjsk_link(101, "en", 555002, "Saki\nTenma", 1700001000.0)
    relinked = await database.get_pjsk_link(101, "en")
    assert relinked["pjsk_user_id"] == 555002
    assert relinked["pjsk_name"] == "Saki Tenma"
    assert relinked["synced_at"] == 0
    assert await database.get_pjsk_clears(101, "en") == {}

    # Crash recovery save -> read -> expire/prune -> delete
    now = time.time()
    await database.save_pjsk_recovery(101, "en", 555002, "jwt.cred.here", now)
    rec = await database.get_pjsk_recovery(101, "en")
    assert rec is not None and rec["credential"] == "jwt.cred.here"
    await database.save_pjsk_recovery(102, "en", 555099, "old.cred", now - 200 * 3600)
    assert await database.get_pjsk_recovery(102, "en") is None
    await database.delete_pjsk_recovery(101, "en")
    assert await database.get_pjsk_recovery(101, "en") is None

    # Bot anonymous account persistence
    await database.set_pjsk_bot_account("jp", 999001, "bot.jwt.cred")
    bot_acc = await database.get_pjsk_bot_account("jp")
    assert bot_acc is not None and bot_acc["user_id"] == 999001

    # Unlink wipes link AND clears
    assert await database.delete_pjsk_link(101, "en") is True
    assert await database.get_pjsk_link(101, "en") is None
    assert await database.get_pjsk_clears(101, "en") == {}
    assert await database.delete_pjsk_link(101, "en") is False
