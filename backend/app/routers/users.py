from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.db import get_db
from app.models import Cosmetic, SeasonScore, User
from app.redis_client import get_redis
from app.schemas import MeOut, OnboardingIn, ProfilePatch
from app.security import ratelimit
from app.security.auth import Principal, firebase_app, get_principal, get_user
from app.services import leaderboard, lives, progression
from app.services.seasons import cairo_today, get_or_create_season, utcnow
from app.services.text import NicknameError, validate_nickname

log = logging.getLogger(__name__)
router = APIRouter(tags=["users"])


async def _me(db: AsyncSession, user: User) -> MeOut:
    s = get_settings()
    season = await get_or_create_season(db)
    today = cairo_today()
    lv, ad_used = lives.effective_lives(user, today)
    pts = await db.scalar(
        select(SeasonScore.points).where(SeasonScore.season_id == season.id, SeasonScore.user_id == user.id, SeasonScore.scope == "all")
    )
    rank = await leaderboard.rank_of(db, season, user.id) if pts else None
    await db.commit()
    return MeOut(
        id=str(user.id),
        nickname=user.nickname,
        favorite_club=user.favorite_club,
        locale=user.locale,
        is_guest=user.is_guest,
        lives=lv,
        ad_lives_left_today=max(0, s.daily_ad_lives_cap - ad_used),
        all_time_points=user.all_time_points,
        season_points=pts or 0,
        season_rank=rank,
        needs_onboarding=not (user.nickname and user.age_confirmed and user.terms_version == s.terms_version),
        terms_version_current=s.terms_version,
        is_banned=user.is_banned,
        level=user.level,
        xp=user.xp,
        xp_level_start=progression.xp_to_reach(user.level),
        xp_next_level=progression.xp_to_reach(user.level + 1),
        coins=user.coins,
        streak_days=_live_streak(user, today),
        streak_freezes=user.streak_freezes,
        played_today=user.streak_last_day == today,
        equipped=await _equipped(db, user),
    )


async def _equipped(db: AsyncSession, user: User) -> dict:
    """Equipped cosmetics with their render assets, so the app needs no hard-coded catalogue."""
    slots = {"frame": user.equipped_frame, "title": user.equipped_title, "theme": user.equipped_theme}
    codes = [c for c in slots.values() if c]
    found = {c.code: c for c in await db.scalars(select(Cosmetic).where(Cosmetic.code.in_(codes)))} if codes else {}
    return {
        slot: None
        if code not in found
        else {"code": code, "name_ar": found[code].name_ar, "name_en": found[code].name_en, "asset": found[code].asset}
        for slot, code in slots.items()
    }


def _live_streak(user: User, today) -> int:
    """The stored streak is only advanced on play; show 0 if it's already broken beyond the freezes held."""
    if user.streak_last_day is None:
        return 0
    missed = (today - user.streak_last_day).days - 1
    return user.streak_days if missed <= user.streak_freezes else 0


@router.post("/auth/sync", response_model=MeOut)
async def auth_sync(request: Request, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)):
    """Idempotent upsert after every sign-in. Also flips is_guest when an anonymous account is linked to Google."""
    s = get_settings()
    await ratelimit.hit(f"auth:ip:{ratelimit.client_ip(request)}", s.rl_auth_per_ip)
    await ratelimit.hit(f"auth:uid:{p.uid}", s.rl_auth_per_user)
    await db.execute(
        insert(User)
        .values(firebase_uid=p.uid, is_guest=p.is_guest)
        .on_conflict_do_update(index_elements=[User.firebase_uid], set_={"is_guest": p.is_guest})
    )
    await db.commit()
    user = await db.scalar(select(User).where(User.firebase_uid == p.uid))
    return await _me(db, user)


@router.get("/users/me", response_model=MeOut)
async def get_me(user: User = Depends(get_user), db: AsyncSession = Depends(get_db)):
    return await _me(db, user)


def _age_on(birth, today) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


@router.post("/users/me/onboarding", response_model=MeOut)
async def onboarding(body: OnboardingIn, user: User = Depends(get_user), db: AsyncSession = Depends(get_db)):
    s = get_settings()
    if body.accept_terms_version != s.terms_version:
        raise HTTPException(status.HTTP_409_CONFLICT, "terms_version_outdated")
    if _age_on(body.birth_date, cairo_today()) < 13:
        # Neutral age gate: we store nothing about the birth date. The client also locks the gate locally.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "under_minimum_age")
    if body.favorite_club not in s.clubs:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown_club")
    if user.favorite_club and user.favorite_club != body.favorite_club:
        # Club is locked after onboarding: prevents 'club hopping' to farm club top-10 rewards.
        raise HTTPException(status.HTTP_409_CONFLICT, "club_locked")
    try:
        nick, key = validate_nickname(body.nickname)
    except NicknameError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    user.nickname, user.nickname_key, user.favorite_club, user.locale = nick, key, body.favorite_club, body.locale
    user.age_confirmed, user.terms_version, user.terms_accepted_at = True, s.terms_version, utcnow()
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "nickname_taken") from None
    return await _me(db, user)


@router.patch("/users/me", response_model=MeOut)
async def patch_me(body: ProfilePatch, user: User = Depends(get_user), db: AsyncSession = Depends(get_db)):
    if body.nickname is not None:
        try:
            user.nickname, user.nickname_key = validate_nickname(body.nickname)
        except NicknameError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    if body.locale is not None:
        user.locale = body.locale
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "nickname_taken") from None
    return await _me(db, user)


@router.delete("/users/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(user: User = Depends(get_user), db: AsyncSession = Depends(get_db)):
    """Right to erasure (PDPL Law 151/2020 + Google Play account-deletion policy). Immediate and total:
    sessions, predictions, ledger, scores, intents and season results cascade; Redis + Firebase purged."""
    uid, user_id, club = user.firebase_uid, str(user.id), user.favorite_club
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
    try:
        r = get_redis()
        keys = [k async for k in r.scan_iter(match="lb:*")]
        if keys:
            pipe = r.pipeline()
            for k in keys:
                pipe.zrem(k, user_id)
            await pipe.execute()
    except Exception:  # noqa: BLE001
        log.warning("redis purge failed for deleted user; cache rebuild will drop them", exc_info=True)
    if get_settings().auth_mode == "firebase" and firebase_app() is not None:
        from firebase_admin import auth as fb_auth

        try:
            await run_in_threadpool(fb_auth.delete_user, uid, firebase_app())
        except fb_auth.UserNotFoundError:
            pass
    log.info("user deleted id=%s club=%s", user_id, club)
