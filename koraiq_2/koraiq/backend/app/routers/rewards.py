from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import RewardIntent, User
from app.schemas import IntentIn, IntentOut, ResumeIn
from app.security import admob_ssv
from app.security.auth import get_player
from app.services import rewards

log = logging.getLogger(__name__)
router = APIRouter(tags=["rewards"])


def _out(i: RewardIntent) -> IntentOut:
    return IntentOut(intent_id=str(i.id), status=i.status, ssv_user_id=str(i.user_id), ssv_custom_data=str(i.id))


@router.post("/rewards/intents", response_model=IntentOut)
async def create_intent(body: IntentIn, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    return _out(await rewards.create_intent(db, user, body.purpose, body.ref))


@router.get("/rewards/intents/{intent_id}", response_model=IntentOut)
async def get_intent(intent_id: str, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    try:
        iid = uuid.UUID(intent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
    i = await db.scalar(select(RewardIntent).where(RewardIntent.id == iid, RewardIntent.user_id == user.id))
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return _out(i)


@router.get("/webhooks/admob-ssv", response_class=PlainTextResponse, include_in_schema=False)
async def admob_ssv_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Public (no auth) but every call must carry a valid Google ECDSA signature.
    200 = processed (incl. duplicates, so Google stops retrying); 400 = invalid signature."""
    raw = request.url.query
    try:
        params = await admob_ssv.verify(raw)
    except admob_ssv.SSVError as e:
        log.warning("SSV rejected: %s", e)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid") from None
    outcome = await rewards.apply_grant(db, params)
    log.info("SSV tx=%s outcome=%s", params.get("transaction_id"), outcome)
    return "ok"


dev_router = APIRouter(prefix="/dev", tags=["dev"])


@dev_router.post("/ssv-simulate", include_in_schema=False)
async def dev_ssv_simulate(body: ResumeIn, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    """DEVELOPMENT ONLY (router is not mounted when ENV is staging/production). Google's demo ad units
    never call our SSV URL, so this lets the full reward flow be exercised on an emulator."""
    return {"outcome": await rewards.apply_grant(db, {"custom_data": body.intent_id, "user_id": str(user.id), "transaction_id": ""})}
