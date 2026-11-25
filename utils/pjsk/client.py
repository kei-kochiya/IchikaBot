"""
Async Project Sekai (EN & JP) API client for account linking and Transfer-ID sync.

Supports:
  - Auto-updating appVersion/appHash from YangTheParrot/sekai-apphash & Sekai-World versions.json.
  - Persistent anonymous bot account per region for public profile lookups (bio verification),
    with automatic re-registration if the persisted credential is ever invalidated.
  - Faithful Sbotga/Haruki Transfer-ID flow:
      Bootstrap -> Preview (isExecuteInherit=False) -> Execute (isExecuteInherit=True)
      -> Login -> IssueInheritCode (new Transfer ID & password!) -> FetchSuite (FC/AP clears).
  - Secret redaction so Transfer IDs, passwords, JWTs, and credentials never appear in logs/errors.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import string
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp

from config import CACHE_DIR, SharedResources
from utils.pjsk.constants import extract_music_clears
from utils.pjsk.crypto import (
    decode_jwt_user_id,
    decrypt_unpack,
    pack_encrypt,
    sign_inherit_jwt,
)

logger = logging.getLogger(__name__)

SUPPORTED_REGIONS = ("en", "jp")

UNITY_VERSION = "2022.3.62f2"
DEVICE_MODEL = "IchikaBot/1.0"
VERSION_CACHE_TTL = 6 * 3600  # 6 hours
JP_COOKIE_TTL = 2 * 3600  # refresh JP CloudFront signed cookies every 2 hours
TRANSFER_ID_RE = re.compile(r"^[A-Za-z0-9]{16}$")

APPHASH_URLS = {
    "jp": "https://raw.githubusercontent.com/YangTheParrot/sekai-apphash/main/jp/apphash.json",
    "en": "https://raw.githubusercontent.com/YangTheParrot/sekai-apphash/main/en/apphash.json",
}

VERSIONS_URLS = {
    "jp": "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/versions.json",
    "en": "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main/versions.json",
}

GAME_VERSION_HOSTS = {
    "jp": "https://game-version.sekai.colorfulpalette.org",
    "en": "https://game-version.sekai-en.com",
}

JP_SIGNATURE_URL = "https://issue.sekai.colorfulpalette.org/api/signature"

DEFAULT_API_BASES = {
    "jp": "https://production-game-api.sekai.colorfulpalette.org",
    "en": "https://n-production-game-api.sekai-en.com",
}

INHERIT_TOKEN_ENV = {
    "jp": "PJSK_JP_INHERIT_TOKEN",
    "en": "PJSK_EN_INHERIT_TOKEN",
}

_COOKIE_ATTRS = frozenset(
    {"expires", "max-age", "domain", "path", "samesite", "priority", "version", "comment"}
)


# ── Exceptions ────────────────────────────────────────────────────────────────


class PJSKError(Exception):
    """Base error for Project Sekai API operations."""


class PJSKConfigError(PJSKError):
    """Raised when required configuration (e.g. inherit verify token) is missing."""


class PJSKAPIError(PJSKError):
    """HTTP / protocol error returned by the PJSK game server."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        error_code: str = "",
        raw_message: str = "",
    ):
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.raw_message = raw_message


class PJSKNotFoundError(PJSKAPIError):
    """Target profile or transfer ID was not found (HTTP 404)."""


class PJSKInvalidTransferError(PJSKAPIError):
    """Transfer ID or password was invalid/expired."""


class PJSKSyncPartialError(PJSKError):
    """Raised if suite fetch failed AFTER a new transfer ID was already generated.

    Carries the new transfer credentials so the caller can ALWAYS deliver them back to the user.
    """

    def __init__(self, message: str, *, new_transfer_id: str, new_password: str, user_id: int):
        super().__init__(message)
        self.new_transfer_id = new_transfer_id
        self.new_password = new_password
        self.user_id = user_id


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class VersionInfo:
    app_version: str
    app_hash: str
    data_version: str
    asset_version: str
    fetched_at: float = 0.0


@dataclass
class ProfileSummary:
    user_id: int
    name: str
    rank: int
    bio: str
    total_power: int = 0
    clear_counts: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class TransferPreview:
    user_id: int
    name: str
    rank: int
    is_restricted: bool
    restriction_info: dict[str, Any] | None = None


@dataclass
class TransferResult:
    user_id: int
    name: str
    rank: int
    clears: dict[tuple[int, str], str]
    new_transfer_id: str
    new_password: str
    total_musics: int


# ── Pure Helpers ──────────────────────────────────────────────────────────────


def validate_transfer_id(transfer_id: str) -> str:
    """Strip and validate a 16-character alphanumeric PJSK Transfer ID."""
    cleaned = transfer_id.strip()
    if not TRANSFER_ID_RE.fullmatch(cleaned):
        raise PJSKInvalidTransferError(
            "Transfer ID không hợp lệ (phải gồm đúng 16 ký tự chữ cái/chữ số)."
        )
    return cleaned


def generate_transfer_password(length: int = 12) -> str:
    """Generate a PJSK-compliant alphanumeric transfer password (8-16 chars, mixed case + digits)."""
    length = max(8, min(16, length))
    alphabet = string.ascii_letters + string.digits
    chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        *(secrets.choice(alphabet) for _ in range(length - 3)),
    ]
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def build_cookie_header(set_cookies: list[str]) -> str:
    """Extract name=value pairs from Set-Cookie headers (newest wins on duplicate names)."""
    cookies: dict[str, str] = {}
    for raw in set_cookies:
        for part in raw.replace(",", ";").split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            if not name or any(c.isspace() for c in name) or name.lower() in _COOKIE_ATTRS:
                continue
            cookies[name] = value.strip()
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def parse_profile_summary(data: dict[str, Any], fallback_user_id: int = 0) -> ProfileSummary:
    """Parse GET /api/user/{bot_uid}/{target_uid}/profile response into ProfileSummary."""
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    profile = data.get("userProfile") if isinstance(data.get("userProfile"), dict) else {}
    total_power_obj = data.get("totalPower") if isinstance(data.get("totalPower"), dict) else {}

    clear_counts: dict[str, dict[str, int]] = {}
    for entry in data.get("userMusicDifficultyClearCount") or []:
        if not isinstance(entry, dict):
            continue
        diff = str(entry.get("musicDifficultyType", "")).strip().lower()
        if diff:
            clear_counts[diff] = {
                "clear": int(entry.get("liveClear", 0) or 0),
                "fc": int(entry.get("fullCombo", 0) or 0),
                "ap": int(entry.get("allPerfect", 0) or 0),
            }

    return ProfileSummary(
        user_id=int(user.get("userId") or profile.get("userId") or fallback_user_id),
        name=str(user.get("name") or "Unknown"),
        rank=int(user.get("rank") or 0),
        bio=str(profile.get("word") or ""),
        total_power=int(total_power_obj.get("totalPower") or 0),
        clear_counts=clear_counts,
    )


def parse_transfer_preview(data: dict[str, Any]) -> TransferPreview:
    """Parse POST /api/inherit/user/{id}?isExecuteInherit=False response."""
    after = data.get("afterUserGamedata")
    if not isinstance(after, dict) or not after.get("userId"):
        raise PJSKAPIError("Phản hồi preview transfer thiếu afterUserGamedata.")

    restrict = data.get("userEventDeviceTransferRestrict")
    if not isinstance(restrict, dict):
        restrict = after.get("userEventDeviceTransferRestrict")

    is_restricted = False
    if isinstance(restrict, dict):
        if "isRestrictDeviceTransfer" in restrict:
            is_restricted = bool(restrict.get("isRestrictDeviceTransfer"))
        else:
            is_restricted = any(bool(v) for v in restrict.values())

    return TransferPreview(
        user_id=int(after["userId"]),
        name=str(after.get("name") or "Unknown"),
        rank=int(after.get("rank") or 0),
        is_restricted=is_restricted,
        restriction_info=restrict if isinstance(restrict, dict) else None,
    )


def _redact(text: str, secrets_list: list[str]) -> str:
    out = text
    for secret in secrets_list:
        if secret:
            out = out.replace(secret, "<redacted>")
    return out


def _read_version_cache_sync(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_version_cache_sync(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


# ── Main Client ───────────────────────────────────────────────────────────────


class PJSKClient:
    """Async Project Sekai client for a single region ('en' or 'jp')."""

    def __init__(
        self,
        region: str,
        *,
        api_base: str | None = None,
        version_url: str | None = None,
        apphash_url: str | None = None,
        game_version_host: str | None = None,
        signature_url: str | None = None,
        inherit_token: str | None = None,
        cache_dir: Path | None = None,
        pacing_before_login: float = 1.5,
        session_getter: Callable[[], Awaitable[aiohttp.ClientSession]] | None = None,
    ):
        region = region.lower().strip()
        if region not in SUPPORTED_REGIONS:
            raise ValueError(f"Unsupported PJSK region: {region!r}")

        self.region = region
        self._explicit_api_base = api_base.rstrip("/") if api_base else None
        self.api_base: str | None = self._explicit_api_base
        self.version_url = version_url or VERSIONS_URLS[region]
        self.apphash_url = apphash_url or APPHASH_URLS[region]
        self.game_version_host = (game_version_host or GAME_VERSION_HOSTS[region]).rstrip("/")
        self.signature_url = (
            signature_url
            if signature_url is not None
            else (JP_SIGNATURE_URL if region == "jp" else "")
        )
        self._explicit_inherit_token = inherit_token
        self.cache_dir = cache_dir or CACHE_DIR
        self.pacing_before_login = pacing_before_login
        self._get_session = session_getter or SharedResources.get_session

        self._version: VersionInfo | None = None
        self._jp_cookie: str = ""
        self._jp_cookie_fetched_at: float = 0.0
        self._bot_uid: int | None = None
        self._bot_cred: str | None = None
        self._bot_session_token: str | None = None
        self._bot_data_version: str | None = None
        self._bot_asset_version: str | None = None

        self._init_lock = asyncio.Lock()
        self._bot_lock = asyncio.Lock()

    @property
    def inherit_token(self) -> str:
        """Read the region's inherit JWT signing secret (explicit override or .env)."""
        if self._explicit_inherit_token is not None:
            return self._explicit_inherit_token.strip()
        return os.getenv(INHERIT_TOKEN_ENV[self.region], "").strip()

    @property
    def _version_cache_file(self) -> Path:
        return self.cache_dir / f"pjsk_version_{self.region}.json"

    def _base_headers(
        self,
        ver: VersionInfo,
        *,
        cookie: str | None = None,
        session_token: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        headers = {
            "Accept": "application/octet-stream",
            "Content-Type": "application/octet-stream",
            "Accept-Encoding": "deflate, gzip",
            "User-Agent": f"UnityPlayer/{UNITY_VERSION}",
            "X-Platform": "Android",
            "X-DeviceModel": DEVICE_MODEL,
            "X-OperatingSystem": "Android",
            "X-Unity-Version": UNITY_VERSION,
            "X-App-Version": ver.app_version,
            "X-App-Hash": ver.app_hash,
            "X-Data-Version": ver.data_version,
            "X-Asset-Version": ver.asset_version,
            "X-Request-Id": str(uuid.uuid4()),
        }
        if cookie:
            headers["Cookie"] = cookie
        if session_token:
            headers["X-Session-Token"] = session_token
        if extra:
            headers.update(extra)
        return headers

    async def _raw_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        secrets_to_redact: list[str] | None = None,
    ) -> tuple[int, Any, dict[str, str], list[str]]:
        """Send an encrypted PJSK request and return (status, decoded, lower_headers, set_cookies)."""
        session = await self._get_session()
        redact_list = secrets_to_redact or []
        try:
            async with session.request(method, url, data=body, headers=headers) as resp:
                raw = await resp.read()
                set_cookies = resp.headers.getall("Set-Cookie", [])
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                decoded: Any = None
                if raw:
                    try:
                        decoded = decrypt_unpack(raw, self.region)
                    except Exception:
                        decoded = None
                return resp.status, decoded, resp_headers, set_cookies
        except (aiohttp.ClientError, TimeoutError) as exc:
            safe_err = _redact(str(exc), redact_list) or type(exc).__name__
            raise PJSKAPIError(
                f"Lỗi kết nối tới server PJSK ({self.region.upper()}): {safe_err}"
            ) from None

    async def _fetch_versions(self, *, force: bool = False) -> VersionInfo:
        """Load appVersion/appHash/dataVersion/assetVersion (with atomic 6h disk cache)."""
        now = time.time()
        if not force and self._version and (now - self._version.fetched_at) < VERSION_CACHE_TTL:
            return self._version

        if not force:
            cached = await asyncio.to_thread(_read_version_cache_sync, self._version_cache_file)
            if cached and (now - float(cached.get("fetched_at", 0))) < VERSION_CACHE_TTL:
                self._version = VersionInfo(
                    app_version=cached["app_version"],
                    app_hash=cached["app_hash"],
                    data_version=cached["data_version"],
                    asset_version=cached["asset_version"],
                    fetched_at=float(cached["fetched_at"]),
                )
                return self._version

        session = await self._get_session()
        no_cache = {"Cache-Control": "no-cache", "Pragma": "no-cache"} if force else None

        app_ver = ""
        app_hash = ""
        data_ver = "0.0.0.0"
        asset_ver = "0.0.0.0"

        with contextlib.suppress(Exception):
            async with session.get(self.version_url, headers=no_cache) as resp:
                if resp.status == 200:
                    ver_json = await resp.json(content_type=None)
                    app_ver = str(ver_json.get("appVersion") or "")
                    app_hash = str(ver_json.get("appHash") or "")
                    data_ver = str(ver_json.get("dataVersion") or data_ver)
                    asset_ver = str(ver_json.get("assetVersion") or asset_ver)

        if self.apphash_url:
            with contextlib.suppress(Exception):
                async with session.get(self.apphash_url, headers=no_cache) as resp:
                    if resp.status == 200:
                        ah_json = await resp.json(content_type=None)
                        android = ah_json.get("production_android")
                        if isinstance(android, dict):
                            ah_ver = str(android.get("app_version") or "")
                            ah_hash = str(android.get("app_hash") or "")
                            if (
                                ah_ver
                                and ah_hash
                                and (not app_ver or _ver_tuple(ah_ver) >= _ver_tuple(app_ver))
                            ):
                                app_ver = ah_ver
                                app_hash = ah_hash

        if not app_ver or not app_hash:
            raise PJSKAPIError(
                f"Không thể lấy appVersion/appHash cho server {self.region.upper()}."
            )

        info = VersionInfo(
            app_version=app_ver,
            app_hash=app_hash,
            data_version=data_ver,
            asset_version=asset_ver,
            fetched_at=now,
        )
        self._version = info
        await asyncio.to_thread(
            _write_version_cache_sync,
            self._version_cache_file,
            {
                "app_version": info.app_version,
                "app_hash": info.app_hash,
                "data_version": info.data_version,
                "asset_version": info.asset_version,
                "fetched_at": info.fetched_at,
            },
        )
        return info

    async def _fetch_jp_cookie(self, ver: VersionInfo) -> str:
        """Fetch CloudFront signed cookies required by JP endpoints."""
        if not self.signature_url:
            return ""
        headers = self._base_headers(ver)
        headers["Cookie"] = ""
        status, _, _, set_cookies = await self._raw_request(
            "POST", self.signature_url, headers=headers
        )
        if status != 200:
            raise PJSKAPIError(f"Không thể lấy JP signature cookie (HTTP {status}).", status=status)
        cookie = build_cookie_header(set_cookies)
        if not cookie:
            raise PJSKAPIError("JP signature endpoint trả về Set-Cookie rỗng.", status=status)
        self._jp_cookie = cookie
        self._jp_cookie_fetched_at = time.time()
        return cookie

    async def _resolve_api_base(self, ver: VersionInfo, cookie: str) -> str:
        """Resolve the production API host via game-version endpoint."""
        if self._explicit_api_base:
            self.api_base = self._explicit_api_base
            return self.api_base

        url = f"{self.game_version_host}/{ver.app_version}/{ver.app_hash}"
        status, data, _, _ = await self._raw_request(
            "GET", url, headers=self._base_headers(ver, cookie=cookie)
        )
        if status == 200 and isinstance(data, dict) and data.get("profile"):
            profile = str(data["profile"])
            if self.region == "jp" and data.get("domain"):
                self.api_base = ("https://" + str(data["domain"]).replace("{0}", profile)).rstrip(
                    "/"
                )
            elif self.region == "en":
                self.api_base = f"https://n-{profile}-game-api.sekai-en.com"
            else:
                self.api_base = DEFAULT_API_BASES[self.region]
            return self.api_base

        self.api_base = DEFAULT_API_BASES[self.region]
        return self.api_base

    async def ensure_bootstrapped(
        self, *, force_refresh: bool = False
    ) -> tuple[VersionInfo, str, str]:
        """Ensure version info, fresh JP signature cookie, and api_base are ready."""
        async with self._init_lock:
            ver = await self._fetch_versions(force=force_refresh)
            cookie_stale = (time.time() - self._jp_cookie_fetched_at) >= JP_COOKIE_TTL
            if self.signature_url and (force_refresh or not self._jp_cookie or cookie_stale):
                await self._fetch_jp_cookie(ver)
            if force_refresh or not self.api_base:
                await self._resolve_api_base(ver, self._jp_cookie)
            assert self.api_base is not None
            return (
                VersionInfo(
                    app_version=ver.app_version,
                    app_hash=ver.app_hash,
                    data_version=ver.data_version,
                    asset_version=ver.asset_version,
                    fetched_at=ver.fetched_at,
                ),
                self._jp_cookie,
                self.api_base,
            )

    # ── Bot Anonymous Account (for public profile lookups) ────────────────────

    async def _register_bot_account(
        self, ver: VersionInfo, cookie: str, api_base: str
    ) -> tuple[int, str, str]:
        """Register a new anonymous account for public profile queries."""
        from utils.core import database

        reg_body = pack_encrypt(
            {
                "platform": "Android",
                "deviceModel": DEVICE_MODEL,
                "operatingSystem": "Android",
            },
            self.region,
        )
        status, reg, _, set_cookies = await self._raw_request(
            "POST",
            f"{api_base}/api/user",
            headers=self._base_headers(ver, cookie=cookie),
            body=reg_body,
        )
        if set_cookies and self.signature_url:
            cookie = build_cookie_header(set_cookies) or cookie
            self._jp_cookie = cookie
            self._jp_cookie_fetched_at = time.time()
        if status != 200 or not isinstance(reg, dict) or not reg.get("credential"):
            raise PJSKAPIError(
                f"Không thể đăng ký tài khoản ẩn danh PJSK ({self.region.upper()}): HTTP {status}",
                status=status,
            )
        cred = str(reg["credential"])
        uid = decode_jwt_user_id(cred)
        await database.set_pjsk_bot_account(self.region, uid, cred)
        return uid, cred, cookie

    async def _ensure_bot_auth(
        self, *, force_reauth: bool = False
    ) -> tuple[int, str, VersionInfo, str, str]:
        """Authenticate the bot's anonymous account for this region (with self-healing)."""
        from utils.core import database

        async with self._bot_lock:
            ver, cookie, api_base = await self.ensure_bootstrapped(force_refresh=force_reauth)
            if self._bot_data_version:
                ver.data_version = self._bot_data_version
            if self._bot_asset_version:
                ver.asset_version = self._bot_asset_version

            if not force_reauth and self._bot_uid and self._bot_session_token:
                return self._bot_uid, self._bot_session_token, ver, cookie, api_base

            if self._bot_cred is None:
                saved = await database.get_pjsk_bot_account(self.region)
                if saved:
                    self._bot_uid = saved["user_id"]
                    self._bot_cred = saved["credential"]

            if not self._bot_cred:
                self._bot_uid, self._bot_cred, cookie = await self._register_bot_account(
                    ver, cookie, api_base
                )

            assert self._bot_uid is not None
            auth_body = pack_encrypt(
                {"credential": self._bot_cred, "deviceId": None, "authTriggerType": "normal"},
                self.region,
            )
            status, auth, _, _ = await self._raw_request(
                "PUT",
                f"{api_base}/api/user/{self._bot_uid}/auth?refreshUpdatedResources=False",
                headers=self._base_headers(ver, cookie=cookie),
                body=auth_body,
            )
            if status == 426 and not force_reauth:
                ver, cookie, api_base = await self.ensure_bootstrapped(force_refresh=True)
                status, auth, _, _ = await self._raw_request(
                    "PUT",
                    f"{api_base}/api/user/{self._bot_uid}/auth?refreshUpdatedResources=False",
                    headers=self._base_headers(ver, cookie=cookie),
                    body=auth_body,
                )
            elif status in (401, 403, 404):
                # Persisted anonymous account was invalidated: wipe & register a fresh one
                await database.delete_pjsk_bot_account(self.region)
                self._bot_uid, self._bot_cred, cookie = await self._register_bot_account(
                    ver, cookie, api_base
                )
                auth_body = pack_encrypt(
                    {"credential": self._bot_cred, "deviceId": None, "authTriggerType": "normal"},
                    self.region,
                )
                status, auth, _, _ = await self._raw_request(
                    "PUT",
                    f"{api_base}/api/user/{self._bot_uid}/auth?refreshUpdatedResources=False",
                    headers=self._base_headers(ver, cookie=cookie),
                    body=auth_body,
                )

            if status != 200 or not isinstance(auth, dict) or not auth.get("sessionToken"):
                raise PJSKAPIError(
                    f"Đăng nhập tài khoản bot PJSK ({self.region.upper()}) thất bại: HTTP {status}",
                    status=status,
                )

            self._bot_session_token = str(auth["sessionToken"])
            if auth.get("dataVersion"):
                ver.data_version = self._bot_data_version = str(auth["dataVersion"])
            if auth.get("assetVersion"):
                ver.asset_version = self._bot_asset_version = str(auth["assetVersion"])
            return self._bot_uid, self._bot_session_token, ver, cookie, api_base

    async def get_profile(self, target_user_id: int) -> ProfileSummary:
        """Fetch public PJSK player profile (name, rank, bio/word, clear counts)."""
        for attempt in range(2):
            bot_uid, token, ver, cookie, api_base = await self._ensure_bot_auth(
                force_reauth=(attempt > 0)
            )
            url = f"{api_base}/api/user/{bot_uid}/{target_user_id}/profile"
            status, data, resp_headers, _ = await self._raw_request(
                "GET",
                url,
                headers=self._base_headers(ver, cookie=cookie, session_token=token),
            )
            if resp_headers.get("x-session-token"):
                async with self._bot_lock:
                    self._bot_session_token = resp_headers["x-session-token"]
            if status == 200 and isinstance(data, dict):
                return parse_profile_summary(data, fallback_user_id=target_user_id)
            if status in (403, 426) and attempt == 0:
                async with self._bot_lock:
                    self._bot_session_token = None
                continue
            if status == 404:
                raise PJSKNotFoundError(
                    f"Không tìm thấy người chơi ID `{target_user_id}` trên server {self.region.upper()}.",
                    status=404,
                )
            err_code = data.get("errorCode", "") if isinstance(data, dict) else ""
            raise PJSKAPIError(
                f"Lỗi khi lấy hồ sơ PJSK (HTTP {status}).",
                status=status,
                error_code=str(err_code),
            )
        raise PJSKAPIError("Không thể lấy hồ sơ PJSK sau khi làm mới phiên.")

    # ── Transfer-ID Sync Flow ─────────────────────────────────────────────────

    def _require_inherit_token(self) -> str:
        secret = self.inherit_token
        if not secret:
            env_name = INHERIT_TOKEN_ENV[self.region]
            raise PJSKConfigError(
                f"Chưa cấu hình `{env_name}` trong `.env` để xác thực Transfer ID cho server {self.region.upper()}."
            )
        return secret

    def _inherit_path(self, transfer_id: str, *, execute: bool) -> str:
        flag = "True" if execute else "False"
        extra_q = "&isAdult=True&tAge=16" if self.region == "en" else ""
        return f"/api/inherit/user/{transfer_id}?isExecuteInherit={flag}{extra_q}"

    async def preview_transfer(self, transfer_id: str, password: str) -> TransferPreview:
        """Preview a Transfer ID without consuming it (isExecuteInherit=False)."""
        secret = self._require_inherit_token()
        transfer_id = validate_transfer_id(transfer_id)
        verify_jwt = sign_inherit_jwt(transfer_id, password, secret)
        secrets_list = [transfer_id, password, secret, verify_jwt]
        empty_body = pack_encrypt(None, self.region)

        for attempt in range(2):
            ver, cookie, api_base = await self.ensure_bootstrapped(force_refresh=(attempt > 0))
            headers = self._base_headers(
                ver,
                cookie=cookie,
                extra={"x-inherit-id-verify-token": verify_jwt},
            )
            url = f"{api_base}{self._inherit_path(transfer_id, execute=False)}"
            status, data, _, _ = await self._raw_request(
                "POST",
                url,
                headers=headers,
                body=empty_body,
                secrets_to_redact=secrets_list,
            )
            if status == 200 and isinstance(data, dict):
                return parse_transfer_preview(data)
            # Retry once on 426 (version bump) or JP 403 (expired CloudFront cookie)
            if (status == 426 or (status == 403 and self.signature_url)) and attempt == 0:
                continue
            if status == 404:
                raise PJSKInvalidTransferError(
                    "Transfer ID hoặc mật khẩu không đúng (hoặc đã hết hạn).",
                    status=404,
                )
            if status == 400:
                raise PJSKInvalidTransferError(
                    "Server từ chối yêu cầu xác thực Transfer ID (HTTP 400 — kiểm tra lại mật khẩu hoặc inherit token).",
                    status=400,
                )
            err_code = data.get("errorCode", "") if isinstance(data, dict) else ""
            raise PJSKAPIError(
                f"Không thể kiểm tra Transfer ID (HTTP {status}).",
                status=status,
                error_code=str(err_code),
            )
        raise PJSKAPIError("Không thể kiểm tra Transfer ID sau khi làm mới phiên bản.")

    async def _login_and_issue_code(
        self,
        *,
        user_id: int,
        credential: str,
        ver: VersionInfo,
        cookie: str,
        api_base: str,
        secrets_list: list[str],
    ) -> tuple[str, str, str, VersionInfo, str, str]:
        """Log in with *credential* and immediately issue a fresh Transfer ID + password.

        Returns (session_token, new_transfer_id, new_password, updated_ver, cookie, api_base).
        """
        auth_body = pack_encrypt(
            {"credential": credential, "deviceId": None, "authTriggerType": "normal"},
            self.region,
        )
        auth_url = f"{api_base}/api/user/{user_id}/auth?refreshUpdatedResources=False"

        auth_data: dict[str, Any] | None = None
        for attempt in range(2):
            if attempt > 0:
                ver, cookie, api_base = await self.ensure_bootstrapped(force_refresh=True)
                auth_url = f"{api_base}/api/user/{user_id}/auth?refreshUpdatedResources=False"
            status, data, _, _ = await self._raw_request(
                "PUT",
                auth_url,
                headers=self._base_headers(ver, cookie=cookie),
                body=auth_body,
                secrets_to_redact=secrets_list,
            )
            if status == 200 and isinstance(data, dict) and data.get("sessionToken"):
                auth_data = data
                break
            if (status == 426 or (status == 403 and self.signature_url)) and attempt == 0:
                continue
            raise PJSKAPIError(
                f"Đăng nhập tài khoản sau khi transfer thất bại (HTTP {status}).",
                status=status,
            )

        assert auth_data is not None
        session_token = str(auth_data["sessionToken"])
        secrets_list.append(session_token)
        session_ver = VersionInfo(
            app_version=ver.app_version,
            app_hash=ver.app_hash,
            data_version=str(auth_data.get("dataVersion") or ver.data_version),
            asset_version=str(auth_data.get("assetVersion") or ver.asset_version),
            fetched_at=ver.fetched_at,
        )

        # Immediately issue a fresh Transfer ID + password BEFORE fetching suite!
        new_password = generate_transfer_password(12)
        secrets_list.append(new_password)
        inherit_body = pack_encrypt({"password": new_password}, self.region)
        inherit_url = f"{api_base}/api/user/{user_id}/inherit"

        status, inh_data, resp_headers, _ = await self._raw_request(
            "PUT",
            inherit_url,
            headers=self._base_headers(session_ver, cookie=cookie, session_token=session_token),
            body=inherit_body,
            secrets_to_redact=secrets_list,
        )
        if resp_headers.get("x-session-token"):
            session_token = resp_headers["x-session-token"]
            secrets_list.append(session_token)
        user_inherit = inh_data.get("userInherit") if isinstance(inh_data, dict) else None
        new_transfer_id = (
            str(user_inherit.get("inheritId") or "") if isinstance(user_inherit, dict) else ""
        )
        if status != 200 or not new_transfer_id:
            raise PJSKAPIError(
                f"Không thể tạo Transfer ID mới cho tài khoản (HTTP {status}).",
                status=status,
            )
        secrets_list.append(new_transfer_id)
        return session_token, new_transfer_id, new_password, session_ver, cookie, api_base

    async def execute_transfer_and_sync(
        self,
        transfer_id: str,
        password: str,
        *,
        on_credential_acquired: Callable[[int, str], Awaitable[None]] | None = None,
    ) -> TransferResult:
        """Execute transfer, immediately issue a new Transfer ID, and pull song clears.

        CRITICAL SAFETY:
          - Never retries `isExecuteInherit=True` (consumes code once).
          - Calls `on_credential_acquired(user_id, credential)` immediately after execute so
            the caller can persist a crash-recovery record in SQLite.
          - Generates the new Transfer ID + password BEFORE fetching suite, and raises
            `PJSKSyncPartialError` carrying those credentials if suite fetch fails.
        """
        secret = self._require_inherit_token()
        transfer_id = validate_transfer_id(transfer_id)
        verify_jwt = sign_inherit_jwt(transfer_id, password, secret)
        secrets_list = [transfer_id, password, secret, verify_jwt]

        ver, cookie, api_base = await self.ensure_bootstrapped()
        headers = self._base_headers(
            ver,
            cookie=cookie,
            extra={"x-inherit-id-verify-token": verify_jwt},
        )
        exec_url = f"{api_base}{self._inherit_path(transfer_id, execute=True)}"
        status, exec_data, _, _ = await self._raw_request(
            "POST",
            exec_url,
            headers=headers,
            body=pack_encrypt(None, self.region),
            secrets_to_redact=secrets_list,
        )
        if status != 200 or not isinstance(exec_data, dict) or not exec_data.get("credential"):
            if status == 404:
                raise PJSKInvalidTransferError(
                    "Transfer ID hoặc mật khẩu không đúng (hoặc đã bị sử dụng).",
                    status=404,
                )
            raise PJSKAPIError(f"Chuyển tài khoản thất bại (HTTP {status}).", status=status)

        credential = str(exec_data["credential"])
        secrets_list.append(credential)
        user_id = decode_jwt_user_id(credential)

        if on_credential_acquired is not None:
            await on_credential_acquired(user_id, credential)

        if self.pacing_before_login > 0:
            await asyncio.sleep(self.pacing_before_login)

        (
            session_token,
            new_transfer_id,
            new_password,
            session_ver,
            cookie,
            api_base,
        ) = await self._login_and_issue_code(
            user_id=user_id,
            credential=credential,
            ver=ver,
            cookie=cookie,
            api_base=api_base,
            secrets_list=secrets_list,
        )

        # Fetch full suite data (userMusics + userGamedata)
        suite_q = "?isLogin=true" if self.region == "jp" else ""
        suite_url = f"{api_base}/api/suite/user/{user_id}{suite_q}"
        try:
            status, suite, _, _ = await self._raw_request(
                "GET",
                suite_url,
                headers=self._base_headers(session_ver, cookie=cookie, session_token=session_token),
                secrets_to_redact=secrets_list,
            )
            if status != 200 or not isinstance(suite, dict):
                raise PJSKAPIError(f"Không thể tải dữ liệu bài hát (HTTP {status}).", status=status)
        except Exception as exc:
            safe_msg = _redact(str(exc), secrets_list)
            raise PJSKSyncPartialError(
                f"Đã tạo Transfer ID mới nhưng tải dữ liệu bài hát bị lỗi: {safe_msg}",
                new_transfer_id=new_transfer_id,
                new_password=new_password,
                user_id=user_id,
            ) from None

        clears = extract_music_clears(suite)
        gamedata = suite.get("userGamedata") if isinstance(suite.get("userGamedata"), dict) else {}
        name = str(gamedata.get("name") or "Unknown")
        rank = int(gamedata.get("rank") or 0)
        total_musics = len(suite.get("userMusics") or [])

        return TransferResult(
            user_id=user_id,
            name=name,
            rank=rank,
            clears=clears,
            new_transfer_id=new_transfer_id,
            new_password=new_password,
            total_musics=total_musics,
        )

    async def reissue_transfer_from_credential(
        self, user_id: int, credential: str
    ) -> tuple[str, str]:
        """Crash-recovery flow: login with a stored credential and issue a new Transfer ID."""
        ver, cookie, api_base = await self.ensure_bootstrapped()
        secrets_list = [credential]
        _, new_transfer_id, new_password, _, _, _ = await self._login_and_issue_code(
            user_id=user_id,
            credential=credential,
            ver=ver,
            cookie=cookie,
            api_base=api_base,
            secrets_list=secrets_list,
        )
        return new_transfer_id, new_password


def _ver_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for p in version.split("."):
        digits = "".join(c for c in p if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


# ── Singleton Accessor ────────────────────────────────────────────────────────

_clients: dict[str, PJSKClient] = {}


def get_pjsk_client(region: str) -> PJSKClient:
    """Get or lazily create the PJSKClient singleton for *region* ('en' or 'jp')."""
    key = region.lower().strip()
    if key not in _clients:
        _clients[key] = PJSKClient(key)
    return _clients[key]
