"""Leaderboard reads: Redis ZSET hot path with transparent PostgreSQL fallback/rebuild."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SeasonScore, User, WeeklySeason
from app.redis_client import get_redis
from app.services.points import lb_key, points_from_zscore, rebuild_cache

log = logging.getLogger(__name__)


async def _ensure_cache(db: AsyncSession, season: WeeklySeason) -> bool:
    try:
        r = get_redis()
        if not await r.exists(f"lb:{season.id}:built"):
            lock = await r.set(f"lb:{season.id}:rebuilding", "1", nx=True, ex=30)
            if not lock:
                return False
            await rebuild_cache(db, season)
        return True
    except Exception:  # noqa: BLE001
        log.warning("redis unavailable; leaderboard served from postgres", exc_info=True)
        return False


async def _db_top(db: AsyncSession, season_id: int, limit: int, club: str | None, scope: str) -> list[tuple[uuid.UUID, int]]:
    q = (
        select(SeasonScore.user_id, SeasonScore.points)
        .join(User, User.id == SeasonScore.user_id)
        .where(SeasonScore.season_id == season_id, SeasonScore.scope == scope, SeasonScore.points > 0, User.is_banned.is_(False))
    )
    if club:
        q = q.where(User.favorite_club == club)
    q = q.order_by(SeasonScore.points.desc(), SeasonScore.last_scored_at.asc()).limit(limit)
    return [(u, p) for u, p in (await db.execute(q)).all()]


async def top(db: AsyncSession, season: WeeklySeason, limit: int, club: str | None = None, scope: str = "all") -> list[dict]:
    rows: list[tuple[uuid.UUID, int]]
    if await _ensure_cache(db, season):
        raw = await get_redis().zrevrange(lb_key(season.id, club, scope), 0, limit - 1, withscores=True)
        rows = [(uuid.UUID(m), points_from_zscore(s)) for m, s in raw]
    else:
        rows = await _db_top(db, season.id, limit, club, scope)
    if not rows:
        return []
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_([r[0] for r in rows])))}
    out = []
    for uid, pts in rows:
        u = users.get(uid)
        if u is None or u.is_banned:  # deleted/banned between cache rebuilds: hide immediately
            continue
        out.append(
            {
                "rank": len(out) + 1,
                "user_id": str(uid),
                "nickname": u.nickname,
                "club": u.favorite_club,
                "points": pts,
                "level": u.level,
                "frame": u.equipped_frame,
                "title": u.equipped_title,
            }
        )
    return out


async def rank_of(db: AsyncSession, season: WeeklySeason, user_id: uuid.UUID, club: str | None = None, scope: str = "all") -> int | None:
    if await _ensure_cache(db, season):
        r = await get_redis().zrevrank(lb_key(season.id, club, scope), str(user_id))
        return None if r is None else r + 1
    me = await db.scalar(
        select(SeasonScore).where(SeasonScore.season_id == season.id, SeasonScore.user_id == user_id, SeasonScore.scope == scope)
    )
    if me is None or me.points <= 0:
        return None
    q = (
        select(func.count())
        .select_from(SeasonScore)
        .join(User, User.id == SeasonScore.user_id)
        .where(
            SeasonScore.season_id == season.id,
            SeasonScore.scope == scope,
            User.is_banned.is_(False),
            or_(SeasonScore.points > me.points, and_(SeasonScore.points == me.points, SeasonScore.last_scored_at < me.last_scored_at)),
        )
    )
    if club:
        q = q.where(User.favorite_club == club)
    ahead = await db.scalar(q)
    return int(ahead) + 1
