"""Rewarded-ad intents. Flow:
 1. client POST /rewards/intents {purpose, ref}  -> {intent_id}
 2. client loads RewardedAd with ServerSideVerificationOptions(userId=<users.id>, customData=<intent_id>)
 3. Google -> GET /webhooks/admob-ssv (signed) -> apply_grant()
 4. client polls GET /rewards/intents/{id} (or calls /game/{id}/resume for revives)
The client's own onUserEarnedReward callback grants NOTHING.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Fixture, GameSession, Prediction, RewardIntent, User
from app.services import economy, lives, predictions
from app.services.seasons import cairo_today, utcnow

log = logging.getLogger(__name__)
PURPOSES = ("REVIVE", "DOUBLE_PREDICTION", "EXTRA_LIFE", "COIN_BONUS")


async def create_intent(db: AsyncSession, user: User, purpose: str, ref: str | None) -> RewardIntent:
    now = utcnow()
    if purpose == "REVIVE":
        try:
            sid = uuid.UUID(str(ref))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_ref") from None
        gs = await db.get(GameSession, sid)
        if gs is None or gs.user_id != user.id or gs.status != "AWAITING_REVIVE" or gs.revive_used:
            raise HTTPException(status.HTTP_409_CONFLICT, "revive_not_available")
    elif purpose == "DOUBLE_PREDICTION":
        if not str(ref).isdigit():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_ref")
        p = await db.scalar(select(Prediction).where(Prediction.user_id == user.id, Prediction.fixture_id == int(ref)))
        if p is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "predict_first")
        if p.is_double_points:
            raise HTTPException(status.HTTP_409_CONFLICT, "already_doubled")
        f = await db.get(Fixture, int(ref))
        if predictions.is_locked(f, now):
            raise HTTPException(status.HTTP_423_LOCKED, "prediction_locked")
    elif purpose == "EXTRA_LIFE":
        ref = cairo_today(now).isoformat()
        _, used = lives.effective_lives(user, cairo_today(now))
        if used >= get_settings().daily_ad_lives_cap:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "daily_ad_cap_reached")
    elif purpose == "COIN_BONUS":
        ref = cairo_today(now).isoformat()
        if await economy.count_today(db, user.id, "AD_BONUS") >= get_settings().coins_ad_bonus_daily_cap:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "daily_ad_cap_reached")
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_purpose")

    pending = await db.scalar(
        select(func.count())
        .select_from(RewardIntent)
        .where(
            RewardIntent.user_id == user.id,
            RewardIntent.status == "PENDING",
            RewardIntent.created_at > now - timedelta(hours=1),
        )
    )
    if pending >= 20:  # nobody watches 20 ads/hour without finishing them; stops intent spraying
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_pending_intents")
    intent = RewardIntent(id=uuid.uuid4(), user_id=user.id, purpose=purpose, ref=str(ref), created_at=now)
    db.add(intent)
    await db.commit()
    return intent


async def apply_grant(db: AsyncSession, params: dict[str, str]) -> str:
    """Called only with a cryptographically verified SSV payload. Returns an outcome label."""
    try:
        intent_id = uuid.UUID(params.get("custom_data", ""))
    except ValueError:
        return "no_intent"  # e.g. the AdMob console 'verify URL' test ping
    tx = params.get("transaction_id", "")
    intent = await db.scalar(select(RewardIntent).where(RewardIntent.id == intent_id).with_for_update())
    if intent is None:
        return "unknown_intent"
    if intent.status != "PENDING":
        return "duplicate"  # AdMob retries; idempotent
    if params.get("user_id") != str(intent.user_id):
        intent.status = "REJECTED"
        await db.commit()
        log.warning("SSV user mismatch intent=%s", intent_id)
        return "user_mismatch"
    if tx and await db.scalar(select(RewardIntent.id).where(RewardIntent.transaction_id == tx)):
        return "duplicate_tx"

    now = utcnow()
    intent.transaction_id, intent.granted_at, intent.status = tx or None, now, "GRANTED"
    outcome = "granted"
    if intent.purpose == "EXTRA_LIFE":
        ok = await lives.grant_ad_life(db, intent.user_id, cairo_today(now))
        intent.status, outcome = ("CONSUMED", "life_added") if ok is not None else ("REJECTED", "cap_reached")
    elif intent.purpose == "DOUBLE_PREDICTION":
        ok = await predictions.apply_double(db, intent.user_id, int(intent.ref), intent.created_at)
        intent.status, outcome = ("CONSUMED", "doubled") if ok else ("REJECTED", "locked_or_missing")
    elif intent.purpose == "COIN_BONUS":
        capped = await economy.count_today(db, intent.user_id, "AD_BONUS") >= get_settings().coins_ad_bonus_daily_cap
        if not capped and await economy.credit(db, intent.user_id, get_settings().coins_ad_bonus, "AD_BONUS", str(intent.id)):
            intent.status, outcome = "CONSUMED", "coins_added"
        else:
            intent.status, outcome = "REJECTED", "cap_reached"
    # REVIVE stays GRANTED until the client calls /game/{id}/resume (so the clock restarts after the ad).
    await db.commit()
    return outcome
