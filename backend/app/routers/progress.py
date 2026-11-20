"""v2 endpoints: topics, Daily Challenge, progression, coins/shop/cosmetics, question reports."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Badge, CoinLedger, GameSession, Question, QuestionReport, TopicMastery, User, UserBadge
from app.schemas import BuyIn, EquipIn, ReportIn, StartIn
from app.security import integrity, ratelimit
from app.security.auth import get_player, get_user
from app.services import daily, progression, seasons, shop
from app.services.topics import visible_topics

router = APIRouter(tags=["progress"])
Lang = Query("ar", pattern="^(ar|en)$")


@router.get("/topics")
async def list_topics(lang: str = Lang, user: User = Depends(get_user), db: AsyncSession = Depends(get_db)):
    today = seasons.cairo_today()
    topics = await visible_topics(db, today)
    mastery = dict((await db.execute(select(TopicMastery.topic_id, TopicMastery.correct).where(TopicMastery.user_id == user.id))).all())
    out = []
    for t in topics:
        c = mastery.get(t.id, 0)
        nxt = progression.next_tier(c)
        out.append(
            {
                "slug": t.slug,
                "name": t.name_ar if lang == "ar" else t.name_en,
                "icon": t.icon,
                "color": t.color,
                "question_count": t.question_count,
                "featured": t.featured,
                "mastery": {"correct": c, "tier": progression.tier_for(c), "next_tier": nxt and nxt[0], "next_at": nxt and nxt[1]},
            }
        )
    return {"mixed_slug": get_settings().mixed_slug, "topics": out}


# ---------------------------------------------------------------- Daily Challenge
@router.get("/daily")
async def daily_status(lang: str = Lang, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    return await daily.status_for(db, user, lang)


@router.post("/daily/start")
async def daily_start(body: StartIn, request: Request, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    await ratelimit.hit(f"game:{user.id}", get_settings().rl_game_per_user)
    ranked = await integrity.check(request, "daily_start", user.firebase_uid)
    return await daily.start(db, user, ranked=ranked, lang=body.lang)


# ---------------------------------------------------------------- progression
@router.get("/me/progress")
async def my_progress(lang: str = Lang, user: User = Depends(get_user), db: AsyncSession = Depends(get_db)):
    topics = await visible_topics(db)
    mastery = dict((await db.execute(select(TopicMastery.topic_id, TopicMastery.correct).where(TopicMastery.user_id == user.id))).all())
    earned = dict((await db.execute(select(UserBadge.badge_code, UserBadge.awarded_at).where(UserBadge.user_id == user.id))).all())
    badges = await db.scalars(select(Badge).order_by(Badge.sort_order))
    start, nxt = progression.xp_to_reach(user.level), progression.xp_to_reach(user.level + 1)
    return {
        "level": user.level,
        "xp": user.xp,
        "xp_level_start": start,
        "xp_next_level": nxt,
        "coins": user.coins,
        "streak_days": user.streak_days,
        "streak_last_day": user.streak_last_day,
        "streak_freezes": user.streak_freezes,
        "mastery": [
            {
                "slug": t.slug,
                "name": t.name_ar if lang == "ar" else t.name_en,
                "icon": t.icon,
                "color": t.color,
                "correct": mastery.get(t.id, 0),
                "tier": progression.tier_for(mastery.get(t.id, 0)),
                "next": progression.next_tier(mastery.get(t.id, 0)),
            }
            for t in topics
        ],
        "badges": [
            {
                "code": b.code,
                "name": b.name_ar if lang == "ar" else b.name_en,
                "description": b.description_ar if lang == "ar" else b.description_en,
                "icon": b.icon,
                "coins": b.coins_reward,
                "earned": b.code in earned,
                "awarded_at": earned.get(b.code),
            }
            for b in badges
        ],
        "equipped": {"frame": user.equipped_frame, "title": user.equipped_title, "theme": user.equipped_theme},
    }


# ---------------------------------------------------------------- wallet & shop
@router.get("/me/wallet")
async def wallet(user: User = Depends(get_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(CoinLedger).where(CoinLedger.user_id == user.id).order_by(CoinLedger.id.desc()).limit(30))
    return {"coins": user.coins, "history": [{"delta": r.delta, "reason": r.reason, "at": r.created_at} for r in rows]}


@router.get("/shop")
async def shop_catalogue(lang: str = Lang, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    return await shop.catalogue(db, user, lang)


@router.post("/shop/buy")
async def shop_buy(body: BuyIn, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    return await shop.buy(db, user, body.item)


@router.post("/me/equip")
async def equip(body: EquipIn, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    return await shop.equip(db, user, body.kind, body.code)


# ---------------------------------------------------------------- report a mistake
@router.post("/questions/report", status_code=status.HTTP_202_ACCEPTED)
async def report_question(body: ReportIn, user: User = Depends(get_player), db: AsyncSession = Depends(get_db)):
    """Only questions the player was actually served can be reported; N distinct reports deactivate it."""
    try:
        sid = uuid.UUID(body.session_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session_not_found") from None
    gs = await db.get(GameSession, sid)
    if gs is None or gs.user_id != user.id or body.index >= len(gs.question_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session_not_found")
    qid = gs.question_ids[body.index]
    new = await db.scalar(
        insert(QuestionReport)
        .values(question_id=qid, user_id=user.id, reason=body.reason)
        .on_conflict_do_nothing()
        .returning(QuestionReport.question_id)
    )
    if new is not None:
        reports = await db.scalar(
            update(Question).where(Question.id == qid).values(reports=Question.reports + 1).returning(Question.reports)
        )
        if reports >= get_settings().reports_to_deactivate:
            await db.execute(update(Question).where(Question.id == qid).values(is_active=False))
    await db.commit()
    return {"ok": True}
