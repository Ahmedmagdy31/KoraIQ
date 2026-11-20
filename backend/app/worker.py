"""Background worker: `python -m app.worker`.

Runs as its OWN process/container (never inside API workers, which would run every job N times).
A PostgreSQL advisory lock makes it a singleton, so you can run 2 replicas for HA: one is active,
the other waits as hot standby.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, text

from app.config import get_settings
from app.db import get_engine, sessionmaker
from app.models import Fixture, GameSession, SeasonResult, SeasonScore, User, WeeklySeason
from app.services import economy, game, points, predictions, progression, push, shop
from app.services.seasons import get_or_create_season, utcnow

log = logging.getLogger("worker")
LOCK_KEY = 0x4B6F7261  # "Kora"


async def settle_pending() -> None:
    async with sessionmaker()() as db:
        ids = list(await db.scalars(select(Fixture.id).where(Fixture.status.in_(["FINISHED", "CANCELLED"]), Fixture.is_settled.is_(False))))
    for fid in ids:
        async with sessionmaker()() as db:
            n = await predictions.settle(db, fid)
            log.info("settled fixture=%s scorers=%s", fid, len({a.user_id for a in n}))


async def finalize_seasons() -> None:
    s = get_settings()
    async with sessionmaker()() as db:
        await get_or_create_season(db)  # make sure the new week exists the moment it starts
        await db.commit()
        due = list(
            await db.scalars(
                select(WeeklySeason)
                .where(WeeklySeason.ends_at <= utcnow(), WeeklySeason.finalized.is_(False))
                .with_for_update(skip_locked=True)
            )
        )
        for season in due:
            ordered = (SeasonScore.points.desc(), SeasonScore.last_scored_at.asc())
            rows = (
                await db.execute(
                    select(SeasonScore.user_id, SeasonScore.points, User.nickname, User.favorite_club)
                    .join(User, User.id == SeasonScore.user_id)
                    .where(
                        SeasonScore.season_id == season.id,
                        SeasonScore.scope == "all",
                        SeasonScore.points > 0,
                        User.is_banned.is_(False),
                    )
                    .order_by(*ordered)
                    .limit(s.season_winners_snapshot)
                )
            ).all()
            for rank, (uid, pts, nick, club) in enumerate(rows, start=1):
                podium = rank <= len(s.weekly_top3_coins)
                db.add(
                    SeasonResult(
                        season_id=season.id,
                        rank=rank,
                        user_id=uid,
                        nickname=nick or "?",
                        favorite_club=club,
                        points=pts,
                        reward_cosmetic="FRAME_CHAMPION" if podium else None,
                    )
                )
                if podium:  # digital rewards only: coins + an exclusive frame + a badge
                    await economy.credit(db, uid, s.weekly_top3_coins[rank - 1], "WEEKLY_PODIUM", str(season.id))
                    await shop.grant_exclusive(db, uid, "FRAME_CHAMPION")
                    await progression.grant_badge(db, uid, "WEEKLY_PODIUM")
            # #1 of every topic board gets the Topic Champion badge (+ its coins, once ever per badge).
            for (scope,) in (
                await db.execute(select(SeasonScore.scope).where(SeasonScore.season_id == season.id, SeasonScore.scope != "all").distinct())
            ).all():
                winner = await db.scalar(
                    select(SeasonScore.user_id)
                    .join(User, User.id == SeasonScore.user_id)
                    .where(SeasonScore.season_id == season.id, SeasonScore.scope == scope, User.is_banned.is_(False))
                    .order_by(*ordered)
                    .limit(1)
                )
                if winner:
                    await economy.credit(db, winner, 100, "TOPIC_WIN", f"{season.id}:{scope}")
                    await progression.grant_badge(db, winner, "TOPIC_CHAMPION")
            season.finalized = True
            log.info("finalized season=%s ranked=%s", season.id, len(rows))
        await db.commit()
    if due:
        await push.send_topic(
            "season_results",
            {"ar": "🏆 نتايج الأسبوع ظهرت!", "en": "🏆 Weekly results are in!"},
            {"ar": "شوف ترتيبك… والأسبوع الجديد بدأ دلوقتي", "en": "See where you finished — a new week just started."},
            {"route": "/leaderboard"},
        )


async def expire_stale_sessions() -> None:
    s = get_settings()
    now = utcnow()
    async with sessionmaker()() as db:
        stale = (
            await db.execute(
                select(GameSession.id, User)
                .join(User, User.id == GameSession.user_id)
                .where(
                    (
                        (GameSession.status == "IN_PROGRESS")
                        & (GameSession.current_issued_at < now - timedelta(seconds=s.stale_session_after_s))
                    )
                    | (
                        (GameSession.status == "AWAITING_REVIVE")
                        & (GameSession.current_issued_at < now - timedelta(seconds=s.revive_window_s))
                    )
                )
                .limit(500)
            )
        ).all()
    for sid, user in stale:
        async with sessionmaker()() as db:
            await game.finish(db, user, sid)


async def kickoff_reminders() -> None:
    now = utcnow()
    async with sessionmaker()() as db:
        due = list(
            await db.scalars(
                select(Fixture)
                .where(
                    Fixture.status == "SCHEDULED",
                    Fixture.reminder_sent.is_(False),
                    Fixture.kickoff_time.between(now, now + timedelta(minutes=75)),
                )
                .with_for_update(skip_locked=True)
            )
        )
        for f in due:
            f.reminder_sent = True
        await db.commit()
    for f in due:
        await push.send_topic(
            "kickoff",
            {"ar": f"⏰ {f.home_team_ar} × {f.away_team_ar}", "en": f"⏰ {f.home_team_en} vs {f.away_team_en}"},
            {"ar": "التوقعات بتقفل قبل الماتش بربع ساعة — الحق توقّع!", "en": "Predictions lock 15 min before kickoff — get yours in!"},
            {"route": "/predictor", "fixture_id": str(f.id)},
        )


async def refresh_leaderboard_cache() -> None:
    async with sessionmaker()() as db:
        season = await get_or_create_season(db)
        await db.commit()
        await points.rebuild_cache(db, season)


async def daily_lives_push() -> None:
    await push.send_topic(
        "daily_lives",
        {"ar": "⚡ طاقتك اتملت!", "en": "⚡ Your lives are refilled!"},
        {"ar": "٥ جولات جديدة مستنياك النهارده", "en": "5 fresh rounds are waiting for you today."},
        {"route": "/"},
    )


async def main() -> None:
    s = get_settings()
    engine = get_engine()
    async with engine.connect() as lock_conn:
        while not (await lock_conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})):
            log.info("another worker holds the lock; standing by")
            await asyncio.sleep(30)
        log.info("worker lock acquired")
        sched = AsyncIOScheduler(timezone=s.tz)
        sched.add_job(settle_pending, "interval", minutes=1, max_instances=1, coalesce=True)
        sched.add_job(finalize_seasons, "interval", minutes=1, max_instances=1, coalesce=True)
        sched.add_job(expire_stale_sessions, "interval", minutes=5, max_instances=1, coalesce=True)
        sched.add_job(kickoff_reminders, "interval", minutes=5, max_instances=1, coalesce=True)
        sched.add_job(refresh_leaderboard_cache, "interval", minutes=10, max_instances=1, coalesce=True)
        sched.add_job(daily_lives_push, CronTrigger(hour=17, minute=0, timezone=s.tz), max_instances=1)
        sched.start()
        try:
            while True:
                await asyncio.sleep(60)
                await lock_conn.scalar(text("SELECT 1"))  # keep the lock-holding connection alive
        finally:
            sched.shutdown(wait=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
