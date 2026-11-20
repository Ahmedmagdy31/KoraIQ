"""Admin API (Firebase custom claim `admin: true`). Set it once with:
firebase_admin.auth.set_custom_user_claims(uid, {"admin": True})
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Fixture, Question, SeasonResult, Topic, User, WeeklySeason
from app.redis_client import get_redis
from app.schemas import BanIn, FixtureIn, FixtureResultIn, QuestionIn, SponsorIn, TopicIn
from app.security.auth import require_admin
from app.services import predictions
from app.services.seasons import get_or_create_season, utcnow

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/fixtures", status_code=201)
async def create_fixture(body: FixtureIn, db: AsyncSession = Depends(get_db)):
    f = Fixture(**body.model_dump())
    db.add(f)
    await db.commit()
    return {"id": f.id}


@router.post("/fixtures/{fixture_id}/result")
async def set_result(fixture_id: int, body: FixtureResultIn, db: AsyncSession = Depends(get_db)):
    f = await db.scalar(select(Fixture).where(Fixture.id == fixture_id).with_for_update())
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fixture_not_found")
    if f.is_settled:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_settled")  # corrections go via ADJUSTMENT ledger rows
    if body.status == "FINISHED":
        if body.home_goals is None or body.away_goals is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "goals_required")
        f.home_goals, f.away_goals = body.home_goals, body.away_goals
        f.actual_result = predictions.outcome_of(body.home_goals, body.away_goals)
    elif body.status == "POSTPONED":
        if body.new_kickoff_time is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "new_kickoff_required")
        # Predictions stay valid and re-open until the new lock time.
        f.kickoff_time, f.reminder_sent, f.status = body.new_kickoff_time, False, "SCHEDULED"
        await db.commit()
        return {"status": f.status, "settled": 0}
    f.status = body.status
    await db.commit()
    awards = await predictions.settle(db, fixture_id)
    return {"status": body.status, "settled": len({a.user_id for a in awards})}  # players who scored


async def _topic_id(db: AsyncSession, slug: str) -> int:
    tid = await db.scalar(select(Topic.id).where(Topic.slug == slug))
    if tid is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown_topic")
    return tid


def _question_fields(body: QuestionIn) -> dict:
    data = body.model_dump(exclude={"topic"})
    if body.reviewed_by:
        data["reviewed_at"] = utcnow()
    return data


@router.post("/questions", status_code=201)
async def create_question(body: QuestionIn, db: AsyncSession = Depends(get_db)):
    q = Question(topic_id=await _topic_id(db, body.topic), **_question_fields(body))
    db.add(q)
    await db.commit()
    return {"id": q.id}


@router.put("/questions/{qid}")
async def update_question(qid: int, body: QuestionIn, db: AsyncSession = Depends(get_db)):
    q = await db.get(Question, qid)
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    q.topic_id = await _topic_id(db, body.topic)
    for k, v in _question_fields(body).items():
        setattr(q, k, v)
    await db.commit()
    return {"id": q.id}


@router.get("/questions/reported")
async def reported(db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(Question).where(Question.reports > 0).order_by(Question.reports.desc()).limit(100))
    return [{"id": q.id, "reports": q.reports, "is_active": q.is_active, "question_en": q.question_en} for q in rows]


@router.put("/topics/{slug}")
async def upsert_topic(slug: str, body: TopicIn, db: AsyncSession = Depends(get_db)):
    t = await db.scalar(select(Topic).where(Topic.slug == slug))
    if t is None:
        t = Topic(slug=slug)
        db.add(t)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    await db.commit()
    return {"slug": t.slug, "id": t.id}


@router.get("/questions/calibration")
async def calibration(db: AsyncSession = Depends(get_db)):
    """Questions whose real correct-rate disagrees with their rated difficulty (min 50 plays)."""
    expected = {1: (0.6, 1.0), 2: (0.35, 0.75), 3: (0.0, 0.5)}
    out = []
    for q in await db.scalars(select(Question).where(Question.times_served >= 50)):
        rate = q.times_correct / q.times_served
        lo, hi = expected[q.difficulty]
        if not lo <= rate <= hi:
            out.append({"id": q.id, "difficulty": q.difficulty, "correct_rate": round(rate, 3), "served": q.times_served})
    return out


@router.put("/seasons/current/sponsor")
async def set_sponsor(body: SponsorIn, db: AsyncSession = Depends(get_db)):
    season = await get_or_create_season(db)
    for k, v in body.model_dump().items():
        setattr(season, k, v)
    await db.commit()
    return {"season_id": season.id}


@router.get("/seasons/{season_id}/winners")
async def winners(season_id: int, db: AsyncSession = Depends(get_db)):
    s = await db.get(WeeklySeason, season_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    rows = await db.scalars(select(SeasonResult).where(SeasonResult.season_id == season_id).order_by(SeasonResult.rank))
    return {
        "finalized": s.finalized,
        "results": [
            {
                "rank": r.rank,
                "user_id": str(r.user_id),
                "nickname": r.nickname,
                "club": r.favorite_club,
                "points": r.points,
                "reward_cosmetic": r.reward_cosmetic,
            }
            for r in rows
        ],
    }


@router.post("/users/{user_id}/ban")
async def ban(user_id: uuid.UUID, body: BanIn, db: AsyncSession = Depends(get_db)):
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    u.is_banned, u.ban_reason = body.banned, body.reason
    await db.commit()
    r = get_redis()
    keys = [k async for k in r.scan_iter(match="lb:*:built")]
    if keys:
        await r.delete(*keys)  # force rebuild so ranks renumber without the banned user
    return {"id": str(u.id), "is_banned": u.is_banned}
