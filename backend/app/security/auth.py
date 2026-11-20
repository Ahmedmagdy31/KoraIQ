"""Firebase ID-token verification. The user identity is taken ONLY from the verified token."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.security import ratelimit

log = logging.getLogger(__name__)
_firebase_app = None


def firebase_app():
    """Lazily initialise firebase-admin (also used by messaging + user deletion)."""
    global _firebase_app
    if _firebase_app is None:
        import firebase_admin
        from firebase_admin import credentials

        raw = get_settings().firebase_credentials
        if raw:
            cred = credentials.Certificate(json.loads(raw) if raw.lstrip().startswith("{") else raw)
        elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("K_SERVICE"):
            cred = credentials.ApplicationDefault()
        else:
            return None
        _firebase_app = firebase_admin.initialize_app(cred)
    return _firebase_app


@dataclass(frozen=True)
class Principal:
    uid: str
    is_guest: bool
    is_admin: bool


def _unauthorized(code: str = "invalid_token") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, code, headers={"WWW-Authenticate": "Bearer"})


async def get_principal(request: Request) -> Principal:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise _unauthorized("missing_token")
    token = header[7:].strip()
    settings = get_settings()

    if settings.auth_mode == "dev":  # guarded by Settings validator: never outside development/test
        if not token.startswith("dev:"):
            raise _unauthorized()
        parts = token.split(":")
        return Principal(uid=parts[1], is_guest="guest" in parts, is_admin="admin" in parts)

    from firebase_admin import auth as fb_auth

    if firebase_app() is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "auth_not_configured")
    try:
        claims = await run_in_threadpool(fb_auth.verify_id_token, token, firebase_app(), settings.firebase_check_revoked)
    except Exception:  # noqa: BLE001 - any verification failure is a 401
        raise _unauthorized() from None
    provider = (claims.get("firebase") or {}).get("sign_in_provider", "")
    return Principal(uid=claims["uid"], is_guest=provider == "anonymous", is_admin=claims.get("admin") is True)


async def get_user(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> User:
    user = await db.scalar(select(User).where(User.firebase_uid == principal.uid))
    if user is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "call_auth_sync_first")
    await ratelimit.hit(f"u:{user.id}", get_settings().rl_default_per_user)
    return user


async def get_player(user: User = Depends(get_user)) -> User:
    """A user allowed to play: onboarded, consented, 13+, not banned."""
    if user.is_banned:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "banned")
    if not user.nickname or not user.terms_accepted_at or not user.age_confirmed:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "onboarding_required")
    return user


async def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin_only")
    return principal
