from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.schemas import AnswerIn, FiftyIn, ResumeIn, StartIn
from app.security import integrity, ratelimit
from app.security.auth import get_player
from app.services import game
from app.services.topics import resolve

router = APIRouter(prefix="/game", tags=["game"])


async def _rl(user: User) -> None:
    await ratelimit.hit(f"game:{user.id}", get_settings().rl_game_per_user)


def _uuid(v: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session_not_found") from None


@router.post("/start")
async def start(body: StartIn, request: Request, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    await _rl(user)
    topic = await resolve(db, body.topic)
    ranked = await integrity.check(request, "game_start", user.firebase_uid)
    return await game.start(db, user, ranked=ranked, lang=body.lang, topic=topic)


@router.post("/{session_id}/answer")
async def answer(session_id: str, body: AnswerIn, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    await _rl(user)
    return await game.answer(db, user, _uuid(session_id), body.index, body.selected)


@router.post("/{session_id}/resume")
async def resume(session_id: str, body: ResumeIn, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    await _rl(user)
    return await game.resume_after_revive(db, user, _uuid(session_id), _uuid(body.intent_id))


@router.post("/{session_id}/finish")
async def finish(session_id: str, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    await _rl(user)
    return await game.finish(db, user, _uuid(session_id))


@router.post("/{session_id}/fifty")
async def fifty(session_id: str, body: FiftyIn, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    await _rl(user)
    return await game.fifty_fifty(db, user, _uuid(session_id), body.index)
