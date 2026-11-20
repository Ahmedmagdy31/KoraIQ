"""Single entry point for awarding points: ledger (idempotent) -> season_scores -> users -> Redis.

Redis ZSET score encodes the official tie-break so Redis ranks == PostgreSQL ranks exactly:
    score = points * 1e6 + (999_999 - seconds_since_season_start_of_last_score)
(higher points first; on equal points, whoever reached it EARLIER ranks higher). Max realistic
weekly points (~1e6) * 1e6 = 1e12, far inside a double's exact-integer range (2^53).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PointsLedger, SeasonScore, User, WeeklySeason
from app.redis_client import get_redis

log = logging.getLogger(__name__)
_SCALE = 1_000_000


def lb_key(season_id: int, club: str | None = None, scope: str = "all") -> str:
    """scope = 'all' or a topic slug. Club boards exist for every scope."""
    return f"lb:{season_id}:{scope}:club:{club}" if club else f"lb:{season_id}:{scope}:all"


def zscore(points: int, last_scored_at: datetime, season_start: datetime) -> float:
    secs = min(_SCALE - 1, max(0, int((last_scored_at - season_start).total_seconds())))
    return float(points * _SCALE + (_SCALE - 1 - secs))


def points_from_zscore(score: float) -> int:
    return int(score // _SCALE)


@dataclass
class Award:
    season_id: int
    user_id: uuid.UUID
    club: str | None
    total: int
    zscore: float
    scope: str = "all"


async def award(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    club: str | None,
    season: WeeklySeason,
    source: str,
    ref: str,
    points: int,
    now: datetime,
    topic_points: dict[str, int] | None = None,
) -> list[Award]:
    """Idempotent. `points` goes to the global ('all') board; `topic_points` splits it across topic boards
    (a mixed round credits each topic for its own questions). Caller commits, THEN push_to_cache()."""
    if points <= 0:
        return []
    inserted = await db.scalar(
        insert(PointsLedger)
        .values(user_id=user_id, season_id=season.id, source=source, ref=ref, points=points)
        .on_conflict_do_nothing(constraint="uq_ledger_idempotency")
        .returning(PointsLedger.id)
    )
    if inserted is None:
        return []
    out: list[Award] = []
    for scope, pts in {"all": points, **(topic_points or {})}.items():
        if pts <= 0:
            continue
        stmt = insert(SeasonScore).values(season_id=season.id, user_id=user_id, scope=scope, points=pts, last_scored_at=now)
        total = await db.scalar(
            stmt.on_conflict_do_update(
                index_elements=[SeasonScore.season_id, SeasonScore.user_id, SeasonScore.scope],
                set_={"points": SeasonScore.points + pts, "last_scored_at": now},
            ).returning(SeasonScore.points)
        )
        out.append(Award(season.id, user_id, club, int(total), zscore(int(total), now, season.starts_at), scope))
    await db.execute(update(User).where(User.id == user_id).values(all_time_points=User.all_time_points + points))
    return out


async def push_to_cache(awards: list[Award]) -> None:
    if not awards:
        return
    try:
        pipe = get_redis().pipeline()
        for a in awards:
            keys = [lb_key(a.season_id, None, a.scope)] + ([lb_key(a.season_id, a.club, a.scope)] if a.club else [])
            for k in keys:
                pipe.zadd(k, {str(a.user_id): a.zscore})
                pipe.expire(k, 60 * 60 * 24 * 21)
        await pipe.execute()
    except Exception:  # noqa: BLE001
        log.warning("leaderboard cache update failed; it will be rebuilt", exc_info=True)


async def rebuild_cache(db: AsyncSession, season: WeeklySeason) -> None:
    rows = (
        await db.execute(
            select(SeasonScore.user_id, SeasonScore.points, SeasonScore.last_scored_at, User.favorite_club, SeasonScore.scope)
            .join(User, User.id == SeasonScore.user_id)
            .where(SeasonScore.season_id == season.id, SeasonScore.points > 0, User.is_banned.is_(False))
        )
    ).all()
    r = get_redis()
    keys = [k async for k in r.scan_iter(match=f"lb:{season.id}:*")]
    pipe = r.pipeline()
    if keys:
        pipe.delete(*keys)
    for uid, pts, ts, club, scope in rows:
        z = zscore(pts, ts, season.starts_at)
        pipe.zadd(lb_key(season.id, None, scope), {str(uid): z})
        if club:
            pipe.zadd(lb_key(season.id, club, scope), {str(uid): z})
    pipe.set(f"lb:{season.id}:built", "1", ex=60 * 60 * 24 * 21)
    await pipe.execute()
