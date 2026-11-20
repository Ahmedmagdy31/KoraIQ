""" "Sealed prefetch": all 10 questions are downloaded up-front (one request, network-resilient) but
each one is AES-256-GCM encrypted with its own key. Key *i* is released only when question *i*
starts, so the server owns the clock: a cheater who decompiles the APK still cannot read question
7 while the timer for question 1 is running, and cannot use the full 150s budget to research
ahead. Each key is 32 bytes -> ~44 chars in JSON: trivial even on 3G.

Wire format per question: base64(nonce[12]) + base64(ciphertext||tag[16]); AAD = f"{session_id}:{index}".
"""

from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def new_key() -> str:
    return base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()


def seal(key_b64: str, session_id: str, index: int, payload: dict) -> dict[str, str]:
    nonce = os.urandom(12)
    ct = AESGCM(base64.b64decode(key_b64)).encrypt(
        nonce, json.dumps(payload, ensure_ascii=False).encode(), f"{session_id}:{index}".encode()
    )
    return {"nonce": base64.b64encode(nonce).decode(), "ciphertext": base64.b64encode(ct).decode()}


def unseal(key_b64: str, session_id: str, index: int, sealed: dict[str, str]) -> dict:
    """Reference implementation of what the client does (used in tests)."""
    pt = AESGCM(base64.b64decode(key_b64)).decrypt(
        base64.b64decode(sealed["nonce"]), base64.b64decode(sealed["ciphertext"]), f"{session_id}:{index}".encode()
    )
    return json.loads(pt)
