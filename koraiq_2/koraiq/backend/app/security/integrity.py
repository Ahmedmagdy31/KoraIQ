"""Google Play Integrity API — *Standard* requests, decoded server-side by Google.

Client contract (see mobile/android/.../IntegrityPlugin.kt):
  headers  X-Integrity-Token: <token>
           X-Integrity-Nonce: <random 16+ byte hex, single use>
  requestHash = sha256_hex(f"{action}:{firebase_uid}:{nonce}")

Server checks: package name, requestHash binding, token age, PLAY_RECOGNIZED app,
MEETS_DEVICE_INTEGRITY, optional signing-cert pin, and nonce single-use (Redis SET NX).

Modes: off -> skip; soft -> failures make the action *unranked* (still playable, no leaderboard
impact, kinder to users on unsupported devices); enforce -> HTTP 403.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.redis_client import get_redis

log = logging.getLogger(__name__)
_SCOPE = "https://www.googleapis.com/auth/playintegrity"
_creds = None


@dataclass(frozen=True)
class IntegrityResult:
    ok: bool
    reason: str = ""


def request_hash(action: str, uid: str, nonce: str) -> str:
    return hashlib.sha256(f"{action}:{uid}:{nonce}".encode()).hexdigest()


async def _access_token() -> str:
    global _creds
    import google.auth
    from google.auth.transport.requests import Request as GRequest

    if _creds is None:
        _creds, _ = google.auth.default(scopes=[_SCOPE])
    if not _creds.valid:
        await run_in_threadpool(_creds.refresh, GRequest())
    return _creds.token


async def decode_token(token: str) -> dict:
    pkg = get_settings().android_package_name
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.post(
            f"https://playintegrity.googleapis.com/v1/{pkg}:decodeIntegrityToken",
            json={"integrity_token": token},
            headers={"Authorization": f"Bearer {await _access_token()}"},
        )
    r.raise_for_status()
    return r.json()["tokenPayloadExternal"]


def evaluate(payload: dict, expected_hash: str) -> IntegrityResult:
    s = get_settings()
    req = payload.get("requestDetails", {})
    if req.get("requestPackageName") != s.android_package_name:
        return IntegrityResult(False, "package")
    if req.get("requestHash") != expected_hash:
        return IntegrityResult(False, "request_hash")
    if abs(time.time() * 1000 - int(req.get("timestampMillis", 0))) > s.integrity_max_token_age_s * 1000:
        return IntegrityResult(False, "stale")
    app = payload.get("appIntegrity", {})
    if app.get("appRecognitionVerdict") != "PLAY_RECOGNIZED":
        return IntegrityResult(False, "app_not_recognized")
    if s.integrity_allowed_cert_sha256 and not set(app.get("certificateSha256Digest", [])) & set(s.integrity_allowed_cert_sha256):
        return IntegrityResult(False, "cert")
    verdicts = payload.get("deviceIntegrity", {}).get("deviceRecognitionVerdict", []) or []
    if "MEETS_DEVICE_INTEGRITY" not in verdicts:
        return IntegrityResult(False, "device")
    return IntegrityResult(True)


async def check(request: Request, action: str, uid: str) -> bool:
    """Returns True if the action is *ranked*. Raises 403 in enforce mode on failure."""
    mode = get_settings().integrity_mode
    if mode == "off":
        return True
    token = request.headers.get("x-integrity-token")
    nonce = request.headers.get("x-integrity-nonce", "")
    result = IntegrityResult(False, "missing")
    if token and 32 <= len(nonce) <= 128:
        try:
            if not await get_redis().set(f"pi:nonce:{nonce}", "1", nx=True, ex=600):
                result = IntegrityResult(False, "replay")
            else:
                result = evaluate(await decode_token(token), request_hash(action, uid, nonce))
        except Exception:  # noqa: BLE001
            log.warning("integrity decode failed", exc_info=True)
            result = IntegrityResult(False, "decode_error")
    if not result.ok:
        log.info("integrity failed uid=%s action=%s reason=%s", uid, action, result.reason)
        # A Google-side outage must not take the whole game down: degrade to unranked instead.
        if mode == "enforce" and result.reason != "decode_error":
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"integrity_{result.reason}")
    return result.ok
