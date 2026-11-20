"""Solo progression, computed ONLY from completed, server-timed rounds:
XP & levels · daily streak (+ freezes) · topic mastery · badges · round coins.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Badge, Fixture, GameSession, TopicMastery, User, UserBadge
from app.services import economy, seasons
from app.services.topics import visible_topics


# ---------------------------------------------------------------- XP / levels
def xp_to_reach(level: int) -> int:
    """Total XP needed to reach `level` (level 1 = 0). Step L->L+1 costs base + step*(L-1)."""
    s = get_settings()
    n = level - 1
    return n * s.xp_level_base + s.xp_level_step * n * (n - 1) // 2


def level_for_xp(xp: int) -> int:
    level = 1
    while xp >= xp_to_reach(level + 1):
        level += 1
    return level


def round_xp(score: int) -> int:
    s = get_settings()
    return score // s.xp_points_divisor + s.xp_per_round_finish


# ---------------------------------------------------------------- mastery
def tier_for(correct: int) -> str | None:
    tier = None
    for name, need in get_settings().mastery_tiers:
        if correct >= need:
            tier = name
    return tier


def next_tier(correct: int) -> tuple[str, int] | None:
    for name, need in get_settings().mastery_tiers:
        if correct < need:
            return name, need
    return None


# ---------------------------------------------------------------- streak
def advance_streak(user: User, today: date) -> tuple[int, int]:
    """Mutates user. Returns (freezes_used, new_streak). A freeze covers one missed day."""
    last = user.streak_last_day
    if last == today:
        return 0, user.streak_days
    used = 0
    if last is None or last == today - timedelta(days=1):
        user.streak_days += 1
    else:
        missed = (today - last).days - 1
        if 0 < missed <= user.streak_freezes:
            used = missed
            user.streak_freezes -= missed
            user.streak_days += 1
        else:
            user.streak_days = 1
    user.streak_last_day = today
    return used, user.streak_days


# ---------------------------------------------------------------- badges
async def grant_badge(db: AsyncSession, user_id: uuid.UUID, code: str) -> dict | None:
    badge = await db.get(Badge, code)
    if badge is None:
        return None
    new = await db.scalar(
        insert(UserBadge)
        .values(user_id=user_id, badge_code=code, awarded_at=seasons.utcnow())
        .on_conflict_do_nothing()
        .returning(UserBadge.badge_code)
    )
    if new is None:
        return None
    await economy.credit(db, user_id, badge.coins_reward, "BADGE", code)
    return {"code": code, "name_ar": badge.name_ar, "name_en": badge.name_en, "icon": badge.icon, "coins": badge.coins_reward}


def _lightning(answers: list[dict], ms: int) -> bool:
    run = 0
    for a in answers:
        run = run + 1 if a["correct"] and a["elapsed_ms"] < ms else 0
        if run >= 5:
            return True
    return False


async def _is_derby_day(db: AsyncSession, today: date) -> bool:
    start, end = economy.cairo_day_bounds(seasons.utcnow())
    rows = (await db.execute(select(Fixture.home_team_en, Fixture.away_team_en).where(Fixture.kickoff_time.between(start, end)))).all()
    return any({"al ahly", "zamalek"} == {h.lower(), a.lower()} for h, a in rows)


async def _ramadan_dailies(db: AsyncSession, user_id: uuid.UUID, today: date) -> int:
    for lo, hi in get_settings().ramadan_ranges:
        d0, d1 = date.fromisoformat(lo), date.fromisoformat(hi)
        if d0 <= today <= d1:
            return int(
                await db.scalar(
                    select(func.count())
                    .select_from(GameSession)
                    .where(GameSession.user_id == user_id, GameSession.mode == "DAILY", GameSession.daily_day.between(d0, d1))
                )
                or 0
            )
    return 0


# ---------------------------------------------------------------- entry point
async def on_round_complete(db: AsyncSession, user_id: uuid.UUID, gs: GameSession, score: int) -> dict:
    """Grant XP, coins, streak, mastery and badges for a completed (non-flagged) round. Idempotent per session
    (coins use the session id as ledger ref; the caller stores the result in gs.rewards and never re-runs)."""
    s = get_settings()
    today = seasons.cairo_today()
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    correct_n = sum(1 for a in gs.answers if a["correct"])
    rewards: dict = {"xp": 0, "coins": 0, "level_before": user.level, "level_after": user.level, "badges": [], "mastery_up": []}
    if correct_n == 0:  # a round with no correct answer earns nothing (prevents 'start-and-quit' farming)
        rewards.update(streak=user.streak_days)
        return rewards

    # XP & level
    xp = round_xp(score)
    user.xp += xp
    user.level = level_for_xp(user.xp)
    rewards.update(xp=xp, level_after=user.level)

    # Coins for the round
    perfect = gs.mode == "SOLO" and correct_n == len(gs.question_ids) == 10
    coins = s.coins_daily if gs.mode == "DAILY" else s.coins_round_finish + (s.coins_perfect_bonus if perfect else 0)
    if await economy.credit(db, user_id, coins, "ROUND", str(gs.id)):
        rewards["coins"] += coins

    # Streak
    before = user.streak_days
    freezes_used, streak = advance_streak(user, today)
    rewards.update(streak=streak, freezes_used=freezes_used)
    if streak != before and streak in s.streak_milestones:
        if await economy.credit(db, user_id, s.streak_milestones[streak], "STREAK", str(streak)):
            rewards["coins"] += s.streak_milestones[streak]

    # Mastery per topic (mixed rounds credit every topic they touched)
    per_topic = Counter(t for a, t in zip(gs.answers, gs.question_topics, strict=False) if a["correct"])
    for topic_id, n in per_topic.items():
        new_total = await db.scalar(
            insert(TopicMastery)
            .values(user_id=user_id, topic_id=topic_id, correct=n)
            .on_conflict_do_update(index_elements=["user_id", "topic_id"], set_={"correct": TopicMastery.correct + n})
            .returning(TopicMastery.correct)
        )
        if tier_for(new_total) != tier_for(new_total - n):
            rewards["mastery_up"].append({"topic_id": topic_id, "tier": tier_for(new_total)})

    # Badges
    candidates = []
    if perfect:
        candidates.append("PERFECT_10")
    if _lightning(gs.answers, s.lightning_ms):
        candidates.append("LIGHTNING")
    candidates += [f"STREAK_{n}" for n in (7, 30, 100) if streak >= n]
    if gs.mode == "DAILY":
        candidates.append("DAILY_FIRST")
        if await _ramadan_dailies(db, user_id, today) >= 20:
            candidates.append("RAMADAN_KAREEM")
    if await _is_derby_day(db, today):
        candidates.append("DERBY_DAY")
    if rewards["mastery_up"]:
        topics = await visible_topics(db)
        bronze = get_settings().mastery_tiers[0][1]
        have = {
            t
            for (t,) in (
                await db.execute(select(TopicMastery.topic_id).where(TopicMastery.user_id == user_id, TopicMastery.correct >= bronze))
            ).all()
        }
        if topics and len(topics) > 1 and {t.id for t in topics} <= have:
            candidates.append("GLOBETROTTER")
    for code in candidates:
        b = await grant_badge(db, user_id, code)
        if b:
            rewards["badges"].append(b)
            rewards["coins"] += b["coins"]
    return rewards
