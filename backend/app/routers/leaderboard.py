from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import SeasonScore, User
from app.security.auth import get_user
from app.services import leaderboard
from app.services.seasons import get_or_create_season, utcnow
from app.services.topics import visible_topics

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("/weekly")
async def weekly(
    lang: str = Query("ar", pattern="^(ar|en)$"),
    scope: str = Query("all", max_length=30, description="'all' or a topic slug"),
    user: User = Depends(get_user),
    db: AsyncSession = Depends(get_db),
):
    s = get_settings()
    topics = await visible_topics(db)
    if scope != "all" and scope not in {t.slug for t in topics}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "topic_not_found")
    season = await get_or_create_season(db)
    club = user.favorite_club
    my_pts = await db.scalar(
        select(SeasonScore.points).where(SeasonScore.season_id == season.id, SeasonScore.user_id == user.id, SeasonScore.scope == scope)
    )
    body = {
        "scope": scope,
        "scopes": ["all", *[t.slug for t in topics]],
        "season": {
            "id": season.id,
            "name": season.season_name,
            "starts_at": season.starts_at,
            "ends_at": season.ends_at,
            "seconds_remaining": max(0, int((season.ends_at - utcnow()).total_seconds())),
            "sponsor": None
            if not season.sponsor_name
            else {
                "name": season.sponsor_name,
                "logo_url": season.sponsor_logo_url,
                "click_url": season.sponsor_click_url,
                "promo_code": season.sponsor_promo_code,
                "message": season.sponsor_message_ar if lang == "ar" else season.sponsor_message_en,
            },
            # Digital-only rewards for the week (no real prizes).
            "rewards": {"top3_coins": s.weekly_top3_coins, "top3_cosmetic": "FRAME_CHAMPION", "topic_winner_badge": "TOPIC_CHAMPION"},
        },
        "global_top": await leaderboard.top(db, season, s.leaderboard_top_global, scope=scope),
        "club": club,
        "club_top": await leaderboard.top(db, season, s.leaderboard_top_club, club, scope=scope) if club else [],
        "me": {
            "points": my_pts or 0,
            "rank": await leaderboard.rank_of(db, season, user.id, scope=scope) if my_pts else None,
            "club_rank": await leaderboard.rank_of(db, season, user.id, club, scope=scope) if my_pts and club else None,
            "is_guest": user.is_guest,  # guests are nudged to link Google so they never lose progress
        },
    }
    await db.commit()
    return body
