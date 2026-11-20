from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Fixture, Prediction, User
from app.services import points
from app.services.seasons import get_or_create_season, utcnow


def lock_time(f: Fixture) -> datetime:
    return f.kickoff_time - timedelta(minutes=get_settings().prediction_lock_minutes)


def is_locked(f: Fixture, now: datetime) -> bool:
    return f.status != "SCHEDULED" or now >= lock_time(f)


def outcome_of(home: int, away: int) -> str:
    return "HOME" if home > away else "AWAY" if away > home else "DRAW"


async def submit(
    db: AsyncSession, user: User, fixture_id: int, outcome: str, home_goals: int | None, away_goals: int | None, ranked: bool
) -> Prediction:
    now = utcnow()
    f = await db.get(Fixture, fixture_id)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fixture_not_found")
    if is_locked(f, now):  # server UTC clock is the only clock that matters
        raise HTTPException(status.HTTP_423_LOCKED, "prediction_locked")
    if (home_goals is None) != (away_goals is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "exact_score_needs_both_goals")
    if home_goals is not None and outcome_of(home_goals, away_goals) != outcome:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "exact_score_contradicts_outcome")
    stmt = insert(Prediction).values(
        user_id=user.id,
        fixture_id=f.id,
        predicted_outcome=outcome,
        predicted_home_goals=home_goals,
        predicted_away_goals=away_goals,
        ranked=ranked,
    )
    pred = await db.scalar(
        stmt.on_conflict_do_update(
            constraint="uq_prediction_user_fixture",
            set_={
                "predicted_outcome": outcome,
                "predicted_home_goals": home_goals,
                "predicted_away_goals": away_goals,
                "ranked": Prediction.ranked & ranked,  # one unverified edit taints the prediction
                "updated_at": now,
            },
        ).returning(Prediction)
    )
    await db.commit()
    return pred


def score_prediction(p: Prediction, f: Fixture) -> int:
    if p.predicted_outcome != f.actual_result:
        return 0
    pts = f.points_reward
    if p.predicted_home_goals == f.home_goals and p.predicted_away_goals == f.away_goals:
        pts += f.exact_score_bonus
    return pts * 2 if p.is_double_points else pts


async def settle(db: AsyncSession, fixture_id: int) -> list[points.Award]:
    """Idempotent: row lock on the fixture + is_settled flag + ledger uniqueness."""
    now = utcnow()
    f = await db.scalar(select(Fixture).where(Fixture.id == fixture_id).with_for_update())
    if f is None or f.is_settled or f.status not in ("FINISHED", "CANCELLED"):
        return []
    awards: list[points.Award] = []
    if f.status == "FINISHED":
        season = await get_or_create_season(db, now)
        rows = (
            await db.execute(
                select(Prediction, User.favorite_club).join(User, User.id == Prediction.user_id).where(Prediction.fixture_id == f.id)
            )
        ).all()
        for p, club in rows:
            p.points_earned = score_prediction(p, f)
            if p.ranked and p.points_earned:
                a = await points.award(
                    db,
                    user_id=p.user_id,
                    club=club,
                    season=season,
                    source="PREDICTION",
                    ref=str(p.id),
                    points=p.points_earned,
                    now=now,
                    topic_points={"football": p.points_earned},  # predictions also count on the Football board
                )
                awards.extend(a)
    f.is_settled = True
    await db.commit()
    await points.push_to_cache(awards)
    return awards


async def apply_double(db: AsyncSession, user_id: uuid.UUID, fixture_id: int, intent_created: datetime) -> bool:
    f = await db.get(Fixture, fixture_id)
    if f is None or f.status != "SCHEDULED" or intent_created >= lock_time(f):
        return False
    p = await db.scalar(select(Prediction).where(Prediction.user_id == user_id, Prediction.fixture_id == fixture_id).with_for_update())
    if p is None:
        return False
    p.is_double_points = True
    return True
