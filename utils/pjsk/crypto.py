"""
Cryptographic & wire-format helpers for Project Sekai (EN & JP) game APIs.

Wire format (verified against MetaSekaiLab/sssekai and live EN/JP servers):
  - Request/response bodies: MessagePack (use_single_float=True) -> PKCS7(128) -> AES-128-CBC.
  - Inherit verify header (x-inherit-id-verify-token): HS256 JWT of {"inheritId", "password"}.

Import this module lazily inside PJSK API calls so `cryptography` and `msgpack`
stay unloaded until a PJSK command is actually used.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

import msgpack
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# AES-128-CBC (key, iv) per region (from MetaSekaiLab/sssekai APIManager.py)
KEYSETS: dict[str, tuple[bytes, bytes]] = {
    "jp": (b"g2fcC0ZczN9MTJ61", b"msx3IV0i9XE5uYZ1"),
    "en": (
        b"\xdf8B\x14\xb2\x9a:\xdf\xbf\x1b\xd9\xee[\x16\xf8\x84",
        b"~\x85l\x90y\x87\xf8\xae\xc6\xaf\xc0\xc5G8\xfc~",
    ),
}

# Encrypted empty payload used by POST /api/inherit/user/{inheritId}
REQUEST_DATA_GENERAL: bytes = base64.b64decode("/6O9YhTzP+c8ty/uImK+2w==")


def get_keyset(region: str) -> tuple[bytes, bytes]:
    """Return the (key, iv) AES-128-CBC keyset for *region* ('en' or 'jp')."""
    key = region.lower()
    if key not in KEYSETS:
        raise ValueError(f"Unsupported PJSK region: {region!r}")
    return KEYSETS[key]


def encrypt_bytes(raw: bytes, region: str) -> bytes:
    """PKCS7-pad and AES-128-CBC-encrypt raw bytes for *region*."""
    key, iv = get_keyset(region)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(raw) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def decrypt_bytes(blob: bytes, region: str) -> bytes:
    """AES-128-CBC-decrypt and PKCS7-unpad raw bytes for *region*."""
    key, iv = get_keyset(region)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(blob) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def pack_encrypt(data: dict[str, Any] | None, region: str) -> bytes:
    """Pack a dict with MessagePack (single-precision floats) and encrypt for *region*."""
    raw = b"" if data is None else msgpack.packb(data, use_single_float=True)
    return encrypt_bytes(raw, region)


def decrypt_unpack(blob: bytes, region: str) -> Any:
    """Decrypt and MessagePack-unpack a game API response body."""
    raw = decrypt_bytes(blob, region)
    if not raw:
        return {}
    return msgpack.unpackb(raw, raw=False, strict_map_key=False)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_inherit_jwt(inherit_id: str, password: str, secret: str) -> str:
    """Build the HS256 JWT for the `x-inherit-id-verify-token` header."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps(
            {"inheritId": inherit_id, "password": password},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    sig = _b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode the payload section of a JWT without verifying signature."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    b64 = parts[1]
    b64 += "=" * (-len(b64) % 4)
    return json.loads(base64.urlsafe_b64decode(b64))


def decode_jwt_user_id(token: str) -> int:
    """Extract the numeric PJSK `userId` from a credential or session JWT."""
    payload = decode_jwt_payload(token)
    uid = payload.get("userId")
    if uid is None or str(uid).strip() == "":
        raise ValueError("JWT payload does not contain userId")
    return int(uid)


def pjsk_id_to_created_ts(user_id: int) -> int | None:
    """Decode EN/JP PJSK snowflake user ID into an approximate Unix timestamp (seconds)."""
    if user_id <= 0:
        return None
    bits = format(user_id, "064b")
    ms = int(bits[:42], 2) + 1_600_218_000_000
    ts = ms // 1000
    # Sanity-check against PJSK launch (Sep 2020) and far future
    if 1_600_000_000 <= ts <= 2_500_000_000:
        return ts
    return None
