"""End-to-end command-flow & encrypted protocol tests for /pjsk link, sync, recover, import, profile, and /b30."""

from __future__ import annotations

import base64
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from cogs.info.pjsk import PJSKCog
from utils.core import database
from utils.pjsk.client import PJSKClient
from utils.pjsk.constants import ChartConstant
from utils.pjsk.crypto import (
    decode_jwt_payload,
    decrypt_bytes,
    decrypt_unpack,
    pack_encrypt,
    sign_inherit_jwt,
)


def _make_jwt(payload: dict) -> str:
    h = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{h}.{p}.fakesig"


class FakePJSKServer:
    """Local aiohttp server speaking real AES-128-CBC + MessagePack PJSK protocol."""

    def __init__(self, region: str, inherit_secret: str) -> None:
        self.region = region
        self.inherit_secret = inherit_secret
        self.target_uid = 819436380471005188
        self.bot_uid = 819436380471999999
        self.player_name = "Ichika"
        self.player_rank = 180
        self.player_bio = "hello sekai"
        self.transfer_id = "AbCdEfGh12345678"
        self.transfer_pw = "MyPass1234"
        self.restricted = False
        self.fail_suite = False
        self.issued_codes: list[tuple[str, str]] = []
        self.calls: list[str] = []

    def build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/versions.json", self.handle_versions)
        app.router.add_get("/apphash.json", self.handle_apphash)
        app.router.add_post("/api/signature", self.handle_signature)
        app.router.add_post("/api/user", self.handle_register)
        app.router.add_put("/api/user/{uid}/auth", self.handle_auth)
        app.router.add_get("/api/user/{bot_uid}/{target_uid}/profile", self.handle_profile)
        app.router.add_post("/api/inherit/user/{inherit_id}", self.handle_inherit)
        app.router.add_put("/api/user/{uid}/inherit", self.handle_issue_inherit)
        app.router.add_get("/api/suite/user/{uid}", self.handle_suite)
        return app

    def _enc(self, data: dict, status: int = 200, headers: dict | None = None) -> web.Response:
        return web.Response(
            body=pack_encrypt(data, self.region),
            status=status,
            content_type="application/octet-stream",
            headers=headers,
        )

    async def handle_versions(self, _req: web.Request) -> web.Response:
        return web.json_response(
            {
                "appVersion": "7.1.0",
                "appHash": "test-hash-uuid",
                "dataVersion": "7.1.0.10",
                "assetVersion": "7.1.0.10",
            }
        )

    async def handle_apphash(self, _req: web.Request) -> web.Response:
        return web.json_response(
            {
                "production_android": {
                    "app_version": "7.1.0",
                    "app_hash": "test-hash-uuid",
                }
            }
        )

    async def handle_signature(self, _req: web.Request) -> web.Response:
        self.calls.append("POST /api/signature")
        return web.Response(
            status=200,
            headers={
                "Set-Cookie": "CloudFront-Policy=ok; Path=/, CloudFront-Signature=sig; Path=/"
            },
        )

    async def handle_register(self, _req: web.Request) -> web.Response:
        self.calls.append("POST /api/user")
        return self._enc({"credential": _make_jwt({"userId": str(self.bot_uid)})})

    async def handle_auth(self, req: web.Request) -> web.Response:
        uid = req.match_info["uid"]
        self.calls.append(f"PUT /api/user/{uid}/auth")
        return self._enc(
            {
                "sessionToken": _make_jwt({"userId": uid, "sessionToken": "sess-1"}),
                "dataVersion": "7.1.0.10",
                "assetVersion": "7.1.0.10",
            }
        )

    async def handle_profile(self, req: web.Request) -> web.Response:
        target = int(req.match_info["target_uid"])
        self.calls.append(f"GET /api/user/bot/{target}/profile")
        if target != self.target_uid:
            return self._enc({"httpStatus": 404}, status=404)
        return self._enc(
            {
                "user": {
                    "userId": self.target_uid,
                    "name": self.player_name,
                    "rank": self.player_rank,
                },
                "userProfile": {"userId": self.target_uid, "word": self.player_bio},
                "totalPower": {"totalPower": 285000},
                "userMusicDifficultyClearCount": [
                    {
                        "musicDifficultyType": "master",
                        "liveClear": 300,
                        "fullCombo": 120,
                        "allPerfect": 15,
                    }
                ],
            }
        )

    async def handle_inherit(self, req: web.Request) -> web.Response:
        inh_id = req.match_info["inherit_id"]
        is_exec = req.query.get("isExecuteInherit")
        self.calls.append(f"POST /api/inherit/user/{inh_id}?isExecuteInherit={is_exec}")
        # Verify the request body decrypts cleanly with THIS region's AES key/IV!
        raw_body = await req.read()
        assert decrypt_bytes(raw_body, self.region) == b""
        tok = req.headers.get("x-inherit-id-verify-token", "")
        expected_tok = sign_inherit_jwt(self.transfer_id, self.transfer_pw, self.inherit_secret)
        if not tok:
            return self._enc({"httpStatus": 403, "errorCode": "session_error"}, status=403)
        if inh_id != self.transfer_id or tok != expected_tok:
            claims = decode_jwt_payload(tok)
            if claims.get("inheritId") != self.transfer_id:
                return self._enc({"httpStatus": 404}, status=404)
            return web.Response(status=400)

        if is_exec == "False":
            return self._enc(
                {
                    "afterUserGamedata": {
                        "userId": self.target_uid,
                        "name": self.player_name,
                        "rank": self.player_rank,
                    },
                    "userEventDeviceTransferRestrict": {
                        "isRestrictDeviceTransfer": self.restricted
                    },
                }
            )
        return self._enc({"credential": _make_jwt({"userId": str(self.target_uid)})})

    async def handle_issue_inherit(self, req: web.Request) -> web.Response:
        uid = req.match_info["uid"]
        self.calls.append(f"PUT /api/user/{uid}/inherit")
        body = decrypt_unpack(await req.read(), self.region)
        new_id = f"NEWCODE{len(self.issued_codes):09d}"
        self.issued_codes.append((new_id, body["password"]))
        return self._enc({"userInherit": {"inheritId": new_id}})

    async def handle_suite(self, req: web.Request) -> web.Response:
        uid = req.match_info["uid"]
        self.calls.append(f"GET /api/suite/user/{uid}")
        if self.fail_suite:
            return self._enc({"httpStatus": 500}, status=500)
        return self._enc(
            {
                "userGamedata": {
                    "userId": self.target_uid,
                    "name": self.player_name,
                    "rank": self.player_rank,
                },
                "userMusics": [
                    {
                        "musicId": 1,
                        "userMusicDifficultyStatuses": [
                            {
                                "musicId": 1,
                                "musicDifficulty": "master",
                                "userMusicResults": [{"playResult": "full_perfect"}],
                            },
                            {
                                "musicId": 1,
                                "musicDifficulty": "expert",
                                "userMusicResults": [{"playResult": "full_combo"}],
                            },
                        ],
                    },
                    {
                        "musicId": 2,
                        "userMusicDifficultyStatuses": [
                            {
                                "musicId": 2,
                                "musicDifficulty": "append",
                                "userMusicResults": [{"playResult": "full_combo"}],
                            }
                        ],
                    },
                ],
            }
        )


def _attach_dm(inter) -> list[dict]:
    """Attach a fake DM sender onto FakeInteraction.user returning an editable message."""
    dm_history: list[dict] = []

    async def _send(content=None, **kwargs):
        entry = {"content": content, **kwargs}
        dm_history.append(entry)

        async def _edit(content=None, **ek):
            dm_history.append({"edited": True, "content": content, **ek})

        msg = SimpleNamespace(edit=_edit)
        return msg

    inter.user.send = _send
    return dm_history


@asynccontextmanager
async def _pjsk_env(region: str, monkeypatch, tmp_path, secret: str | None = None):
    """Spin up a local encrypted FakePJSKServer and wire PJSKClient to it."""
    tok = secret or f"test-secret-{region}"
    server_state = FakePJSKServer(region, tok)
    async with TestServer(server_state.build_app()) as srv:
        base = str(srv.make_url("")).rstrip("/")
        client = PJSKClient(
            region,
            api_base=base,
            version_url=f"{base}/versions.json",
            apphash_url=f"{base}/apphash.json",
            signature_url=f"{base}/api/signature" if region == "jp" else "",
            inherit_token=tok,
            cache_dir=tmp_path,
            pacing_before_login=0.0,
        )
        monkeypatch.setattr("utils.pjsk.client.get_pjsk_client", lambda _r: client)
        yield server_state, client


async def test_pjsk_link_cancel_verify_and_unlink_recovery_guard(
    mock_bot, temp_db, make_interaction, monkeypatch, tmp_path
):
    async with _pjsk_env("en", monkeypatch, tmp_path) as (server_state, _client):
        cog = PJSKCog(mock_bot)

        # Open link modal -> submit User ID -> get Bio verification view
        inter_link = make_interaction(user_id=201)
        await cog.pjsk_link.callback(cog, inter_link, region="en")
        modal = inter_link.response.modals[0]
        modal.user_id_input._value = str(server_state.target_uid)

        inter_modal = make_interaction(user_id=201)
        await modal.on_submit(inter_modal)
        view = inter_modal.last_reply["view"]
        verify_code = view.verify_code
        assert verify_code.startswith("ICHIKA-")

        # Wrong user cannot press Verify or Cancel
        inter_other = make_interaction(user_id=999)
        await view.verify_button.callback(inter_other)
        assert inter_other.last_reply["ephemeral"] is True

        # Clicking Verify BEFORE updating Bio fails cleanly
        inter_v1 = make_interaction(user_id=201)
        await view.verify_button.callback(inter_v1)
        assert "Chưa tìm thấy mã" in inter_v1.last_reply["embed"].title

        # Update Bio -> Verify succeeds and persists link
        server_state.player_bio = f"playing pjsk {verify_code}"
        inter_v2 = make_interaction(user_id=201)
        await view.verify_button.callback(inter_v2)
        assert "Liên kết thành công" in inter_v2.edits[-1]["embed"].title
        link = await database.get_pjsk_link(201, "en")
        assert link is not None and link["pjsk_user_id"] == server_state.target_uid

        # /pjsk unlink refuses while an unconsumed crash-recovery record exists
        await database.save_pjsk_recovery(
            201,
            "en",
            server_state.target_uid,
            _make_jwt({"userId": str(server_state.target_uid)}),
            time.time(),
        )
        inter_un_blocked = make_interaction(user_id=201)
        await cog.pjsk_unlink.callback(cog, inter_un_blocked, region="en")
        assert "/pjsk recover" in inter_un_blocked.last_reply["content"]
        assert await database.get_pjsk_link(201, "en") is not None

        # Once recovery is cleared, /pjsk unlink removes the link cleanly
        await database.delete_pjsk_recovery(201, "en")
        inter_un_ok = make_interaction(user_id=201)
        await cog.pjsk_unlink.callback(cog, inter_un_ok, region="en")
        assert "Đã hủy liên kết" in inter_un_ok.last_reply["content"]
        assert await database.get_pjsk_link(201, "en") is None

        # Cancel flow on a fresh LinkVerifyView aborts without writing to DB
        inter_m2 = make_interaction(user_id=202)
        await modal.on_submit(inter_m2)
        cancel_view = inter_m2.last_reply["view"]
        inter_cancel = make_interaction(user_id=202)
        await cancel_view.cancel_button.callback(inter_cancel)
        assert "Đã hủy" in inter_cancel.response.edits[-1]["embed"].title
        assert await database.get_pjsk_link(202, "en") is None


@pytest.mark.parametrize("region", ["en", "jp"])
async def test_pjsk_transfer_sync_profile_and_b30_flow(
    region, mock_bot, temp_db, make_interaction, monkeypatch, tmp_path
):
    async with _pjsk_env(region, monkeypatch, tmp_path) as (server_state, _client):
        cog = PJSKCog(mock_bot)
        await database.set_pjsk_link(201, region, server_state.target_uid, "Ichika", time.time())

        # /pjsk profile escapes markdown/mentions in player bio
        server_state.player_bio = "[click](https://evil.test) @everyone"
        inter_prof = make_interaction(user_id=201)
        await cog.pjsk_profile.callback(cog, inter_prof, region=region, user=None)
        prof_embed = inter_prof.last_reply["embed"]
        assert "Ichika" in prof_embed.title
        assert "\\[click]" in prof_embed.description
        assert "@\u200beveryone" in prof_embed.description

        # /pjsk sync -> TransferIDModal -> DM preview -> confirm -> new Transfer ID + saved clears
        inter_sync = make_interaction(user_id=201)
        await cog.pjsk_sync.callback(cog, inter_sync, region=region)
        t_modal = inter_sync.response.modals[0]
        t_modal.transfer_id._value = server_state.transfer_id
        t_modal.transfer_password._value = server_state.transfer_pw

        inter_tsub = make_interaction(user_id=201)
        dm_msgs = _attach_dm(inter_tsub)
        await t_modal.on_submit(inter_tsub)
        assert "Xác nhận Transfer" in dm_msgs[-1]["embed"].title
        confirm_view = dm_msgs[-1]["view"]

        inter_confirm = make_interaction(user_id=201)
        await confirm_view.transfer_button.callback(inter_confirm)
        final_embed = inter_confirm.edits[-1]["embed"]
        assert "Đồng bộ thành công" in final_embed.title
        assert confirm_view.is_finished() is True
        assert confirm_view.transfer_id == "" and confirm_view.transfer_password == ""
        assert len(server_state.issued_codes) == 1
        new_tid, new_pw = server_state.issued_codes[0]
        assert new_tid in final_embed.description and new_pw in final_embed.description

        # Regression: post-completion on_timeout() and double-click are harmless no-ops
        before_dm_count = len(dm_msgs)
        await confirm_view.on_timeout()
        assert len(dm_msgs) == before_dm_count
        inter_dup = make_interaction(user_id=201)
        await confirm_view.transfer_button.callback(inter_dup)
        assert inter_dup.last_reply["ephemeral"] is True and len(server_state.issued_codes) == 1
        assert await database.get_pjsk_recovery(201, region) is None

        assert await database.get_pjsk_clears(201, region) == {
            (1, "master"): "ap",
            (1, "expert"): "fc",
            (2, "append"): "fc",
        }

        # /b30 renders JPEG attachment with AllowedMentions.none()
        fake_constants = {
            (1, "master"): ChartConstant(1, "master", 31.5, "31", 1000, "Tell Your World", "TYW"),
            (1, "expert"): ChartConstant(1, "expert", 28.0, "28", 800, "Tell Your World", "TYW"),
            (2, "append"): ChartConstant(2, "append", 33.0, "33", 1400, "Append Song", "Append"),
        }
        monkeypatch.setattr(
            "utils.pjsk.constants.get_chart_constants", AsyncMock(return_value=fake_constants)
        )
        monkeypatch.setattr("cogs.info.pjsk.get_song_jacket_path", AsyncMock(return_value=None))

        inter_b30 = make_interaction(user_id=201)
        await cog.b30_shortcut.callback(cog, inter_b30, region=region, user=None)
        b30_reply = inter_b30.last_reply
        assert "B30 Rating:" in b30_reply["content"]
        assert b30_reply["allowed_mentions"].to_dict() == discord.AllowedMentions.none().to_dict()
        assert isinstance(b30_reply["file"], discord.File) and b30_reply["file"].filename.endswith(
            ".jpg"
        )

        if region == "jp":
            assert "POST /api/signature" in server_state.calls


@pytest.mark.parametrize("region", ["en", "jp"])
async def test_pjsk_recover_flow(
    region, mock_bot, temp_db, make_interaction, monkeypatch, tmp_path
):
    async with _pjsk_env(region, monkeypatch, tmp_path) as (server_state, _client):
        cog = PJSKCog(mock_bot)

        # No pending recovery record -> clean ephemeral message
        inter_empty = make_interaction(user_id=250)
        await cog.pjsk_recover.callback(cog, inter_empty, region=region)
        assert "Không có phiên transfer" in inter_empty.last_reply["content"]

        # Active recovery record -> re-issues new Transfer ID via DM and wipes record
        await database.save_pjsk_recovery(
            250,
            region,
            server_state.target_uid,
            _make_jwt({"userId": str(server_state.target_uid)}),
            time.time(),
        )
        inter_rec = make_interaction(user_id=250)
        rec_dms = _attach_dm(inter_rec)
        await cog.pjsk_recover.callback(cog, inter_rec, region=region)
        assert "Khôi phục Transfer ID thành công" in rec_dms[-1]["embed"].title
        assert len(server_state.issued_codes) == 1
        assert await database.get_pjsk_recovery(250, region) is None


async def test_pjsk_sync_guards_restriction_cancel_and_partial_failure(
    mock_bot, temp_db, make_interaction, monkeypatch, tmp_path
):
    async with _pjsk_env("en", monkeypatch, tmp_path, secret="guard-secret") as (
        server_state,
        _client,
    ):
        cog = PJSKCog(mock_bot)
        await database.set_pjsk_link(301, "en", server_state.target_uid, "Ichika", time.time())

        # t300 restriction blocks transfer before Execute
        server_state.restricted = True
        inter_sync = make_interaction(user_id=301)
        await cog.pjsk_sync.callback(cog, inter_sync, region="en")
        modal = inter_sync.response.modals[0]
        modal.transfer_id._value = server_state.transfer_id
        modal.transfer_password._value = server_state.transfer_pw

        inter_sub = make_interaction(user_id=301)
        dms = _attach_dm(inter_sub)
        await modal.on_submit(inter_sub)
        assert "Top 300" in dms[-1]["embed"].title
        assert not server_state.issued_codes

        # Cancel in TransferConfirmView clears secrets without consuming code
        server_state.restricted = False
        inter_sub_c = make_interaction(user_id=301)
        dms_c = _attach_dm(inter_sub_c)
        await modal.on_submit(inter_sub_c)
        c_view = dms_c[-1]["view"]
        inter_c = make_interaction(user_id=301)
        await c_view.cancel_button.callback(inter_c)
        assert "Đã hủy" in inter_c.response.edits[-1]["embed"].title
        assert c_view.transfer_id == "" and not server_state.issued_codes

        # Suite failure AFTER IssueInheritCode still delivers the NEW Transfer ID back to user
        server_state.fail_suite = True
        inter_sub2 = make_interaction(user_id=301)
        dms2 = _attach_dm(inter_sub2)
        await modal.on_submit(inter_sub2)
        confirm_view = dms2[-1]["view"]

        inter_go = make_interaction(user_id=301)
        await confirm_view.transfer_button.callback(inter_go)
        warn_embed = inter_go.edits[-1]["embed"]
        assert "Đã tạo Transfer ID mới" in warn_embed.title
        assert server_state.issued_codes[0][0] in warn_embed.description
        assert await database.get_pjsk_recovery(301, "en") is None
