from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Fixture, Prediction, User
from app.schemas import FixtureOut, PredictionIn
from app.security import integrity, ratelimit
from app.security.auth import get_player, get_user
from app.services import predictions as svc
from app.services.seasons import utcnow

router = APIRouter(tags=["predictions"])


def _pred_dict(p: Prediction | None) -> dict | None:
    if p is None:
        return None
    return {
        "outcome": p.predicted_outcome,
        "home_goals": p.predicted_home_goals,
        "away_goals": p.predicted_away_goals,
        "is_double_points": p.is_double_points,
        "points_earned": p.points_earned,
        "ranked": p.ranked,
    }


def _fixture_out(f: Fixture, lang: str, p: Prediction | None) -> FixtureOut:
    now = utcnow()
    return FixtureOut(
        id=f.id,
        competition=f.competition,
        home_team=f.home_team_ar if lang == "ar" else f.home_team_en,
        away_team=f.away_team_ar if lang == "ar" else f.away_team_en,
        kickoff_time=f.kickoff_time,
        locks_at=svc.lock_time(f),
        locked=svc.is_locked(f, now),
        status=f.status,
        home_goals=f.home_goals,
        away_goals=f.away_goals,
        points_reward=f.points_reward,
        exact_score_bonus=f.exact_score_bonus,
        my_prediction=_pred_dict(p),
    )


@router.get("/fixtures", response_model=list[FixtureOut])
async def list_fixtures(lang: str = Query("ar", pattern="^(ar|en)$"), user: User = Depends(get_user), db: AsyncSession = Depends(get_db)):
    """Upcoming fixtures (next 14 days) plus those finished in the last 3 days, with my prediction."""
    now = utcnow()
    rows = (
        await db.execute(
            select(Fixture, Prediction)
            .outerjoin(Prediction, (Prediction.fixture_id == Fixture.id) & (Prediction.user_id == user.id))
            .where(Fixture.kickoff_time.between(now - timedelta(days=3), now + timedelta(days=14)))
            .order_by(Fixture.kickoff_time)
            .limit(30)
        )
    ).all()
    return [_fixture_out(f, lang, p) for f, p in rows]


@router.post("/predictions", response_model=FixtureOut)
async def submit_prediction(
    body: PredictionIn,
    request: Request,
    lang: str = Query("ar", pattern="^(ar|en)$"),
    user: User = Depends(get_player),
    db: AsyncSession = Depends(get_db),
):
    await ratelimit.hit(f"game:{user.id}", get_settings().rl_game_per_user)
    ranked = await integrity.check(request, "prediction_submit", user.firebase_uid)
    p = await svc.submit(db, user, body.fixture_id, body.outcome, body.home_goals, body.away_goals, ranked)
    f = await db.get(Fixture, body.fixture_id)
    return _fixture_out(f, lang, p)
