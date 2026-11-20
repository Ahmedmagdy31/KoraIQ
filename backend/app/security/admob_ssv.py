"""AdMob rewarded-ad Server-Side Verification (ECDSA P-256 / SHA-256).

Per Google's spec, `signature` and `key_id` are always the LAST two query parameters and the
signed message is the raw query string up to (not including) "&signature=". We therefore verify
against the *raw* query string, never a re-encoded dict (re-encoding breaks the signature).
"""

from __future__ import annotations

import base64
import time
from urllib.parse import parse_qsl

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import get_settings

_KEYS: dict[str, ec.EllipticCurvePublicKey] = {}
_KEYS_FETCHED_AT = 0.0
_KEYS_TTL_S = 24 * 3600


class SSVError(ValueError):
    pass


async def _fetch_keys() -> None:
    global _KEYS, _KEYS_FETCHED_AT
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(get_settings().admob_ssv_keys_url)
    r.raise_for_status()
    keys = {}
    for k in r.json()["keys"]:
        keys[str(k["keyId"])] = serialization.load_pem_public_key(k["pem"].encode())
    _KEYS, _KEYS_FETCHED_AT = keys, time.time()


async def get_key(key_id: str) -> ec.EllipticCurvePublicKey:
    if key_id not in _KEYS or time.time() - _KEYS_FETCHED_AT > _KEYS_TTL_S:
        await _fetch_keys()  # also handles Google key rotation
    if key_id not in _KEYS:
        raise SSVError("unknown_key_id")
    return _KEYS[key_id]


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


async def verify(raw_query: str) -> dict[str, str]:
    """Verify and return the parsed params. Raises SSVError."""
    marker = "&signature="
    idx = raw_query.find(marker)
    if idx <= 0:
        raise SSVError("no_signature")
    message = raw_query[:idx].encode()
    params = dict(parse_qsl(raw_query, keep_blank_values=True))
    sig, key_id = params.get("signature"), params.get("key_id")
    if not sig or not key_id:
        raise SSVError("missing_fields")
    key = await get_key(key_id)
    try:
        key.verify(_b64url_decode(sig), message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise SSVError("bad_signature") from None
    allowed = get_settings().admob_allowed_ad_units
    if allowed and params.get("ad_unit") not in allowed:
        raise SSVError("ad_unit_not_allowed")
    return params
