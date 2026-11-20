"""Daily Challenge: 5 questions, identical for every player on a Cairo calendar day, one attempt, free.
The topic rotates daily through the visible topics, which nudges players toward topics they haven't tried."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import DailyChallenge, GameSession, Question, User
from app.services import game, seasons
from app.services.topics import visible_topics


def number_for(day: date) -> int:
    return (day - date.fromisoformat(get_settings().daily_epoch)).days + 1


async def get_or_create(db: AsyncSession, day: date) -> DailyChallenge:
    found = await db.get(DailyChallenge, day)
    if found:
        return found
    s = get_settings()
    topics = await visible_topics(db)
    if not topics:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "question_bank_too_small")
    topic = topics[number_for(day) % len(topics)]
    qs = list(
        await db.scalars(
            select(Question).where(Question.is_active, Question.topic_id == topic.id).order_by(func.random()).limit(s.daily_questions)
        )
    )
    qs.sort(key=lambda q: q.difficulty)
    await db.execute(
        insert(DailyChallenge)
        .values(day=day, number=number_for(day), question_ids=[q.id for q in qs])
        .on_conflict_do_nothing(index_elements=["day"])
    )
    return await db.get(DailyChallenge, day, populate_existing=True)


async def status_for(db: AsyncSession, user: User, lang: str) -> dict:
    now = seasons.utcnow()
    today = seasons.cairo_today(now)
    dc = await get_or_create(db, today)
    first_q = await db.get(Question, dc.question_ids[0])
    topic = next((t for t in await visible_topics(db) if t.id == first_q.topic_id), None)
    played = await db.scalar(
        select(GameSession).where(GameSession.user_id == user.id, GameSession.mode == "DAILY", GameSession.daily_day == today)
    )
    tomorrow = datetime.combine(today + timedelta(days=1), time.min, tzinfo=get_settings().tz)
    result = None
    if played and played.status in ("COMPLETED", "FLAGGED"):
        result = {
            "grid": [a["correct"] for a in played.answers],
            "score": sum(a["points"] for a in played.answers),
            "seconds": round(sum(a["elapsed_ms"] for a in played.answers) / 1000),
        }
    await db.commit()
    return {
        "day": today.isoformat(),
        "number": dc.number,
        "topic": None
        if topic is None
        else {"slug": topic.slug, "name": topic.name_ar if lang == "ar" else topic.name_en, "icon": topic.icon, "color": topic.color},
        "questions": len(dc.question_ids),
        "played": played is not None,
        "in_progress_session": str(played.id) if played and played.status == "IN_PROGRESS" else None,
        "result": result,
        "seconds_until_next": int((tomorrow - now).total_seconds()),
    }


async def start(db: AsyncSession, user: User, *, ranked: bool, lang: str) -> dict:
    today = seasons.cairo_today()
    dc = await get_or_create(db, today)
    by_id = {q.id: q for q in await db.scalars(select(Question).where(Question.id.in_(dc.question_ids)))}
    qs = [by_id[i] for i in dc.question_ids if i in by_id]
    try:
        out = await game._create_session(
            db, user, qs, ranked=ranked, lang=lang, mode="DAILY", topic=None, daily_day=today, extra={"daily_number": dc.number}
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "daily_already_played") from None
    return out
