"""Server-authoritative trivia rounds.

Modes:  SOLO  = 10 questions, costs a life, a wrong answer ends the streak (one ad revive), 50/50 allowed.
        DAILY = the Daily Challenge: 5 fixed questions for everyone, free, every question is answered.
Flow:   start -> (answer)* -> [AWAITING_REVIVE -> resume | finish] -> COMPLETED | FLAGGED
Timing: the server stamps `current_issued_at` when it releases question i's key and measures the
elapsed time when the answer arrives. Client timers are cosmetic only.
"""

from __future__ import annotations

import math
import secrets
import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GameSession, Question, RewardIntent, User, WeeklySeason
from app.services import economy, lives, points, progression, sealing
from app.services.seasons import cairo_today, get_or_create_season, utcnow
from app.services.topics import VisibleTopic, slug_map, visible_topics

IN_PROGRESS, AWAITING_REVIVE, COMPLETED, FLAGGED = "IN_PROGRESS", "AWAITING_REVIVE", "COMPLETED", "FLAGGED"


def _conflict(code: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, code)


async def _pick_questions(db: AsyncSession, user_id: uuid.UUID, n: int, topic: VisibleTopic | None) -> list[Question]:
    """Random questions, excluding the player's last few rounds. Mixed rounds are balanced across topics."""
    s = get_settings()
    recent_rows = await db.scalars(
        select(GameSession.question_ids)
        .where(GameSession.user_id == user_id)
        .order_by(GameSession.started_at.desc())
        .limit(s.recent_sessions_no_repeat)
    )
    recent = list({qid for ids in recent_rows for qid in ids}) or [-1]
    topic_ids = [topic.id] if topic else [t.id for t in await visible_topics(db)]
    if not topic_ids:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "question_bank_too_small")
    per_topic = math.ceil(n / len(topic_ids))

    async def draw(tid: int, k: int, exclude: list[int]) -> list[Question]:
        return list(
            await db.scalars(
                select(Question)
                .where(Question.is_active, Question.topic_id == tid, Question.id.not_in(exclude))
                .order_by(func.random())
                .limit(k)
            )
        )

    picked: list[Question] = []
    for tid in topic_ids:
        picked += await draw(tid, per_topic, recent)
    secrets.SystemRandom().shuffle(picked)
    picked = picked[:n]
    if len(picked) < n:  # small bank: top up with repeats rather than failing
        have = [q.id for q in picked] or [-1]
        picked += list(
            await db.scalars(
                select(Question)
                .where(Question.is_active, Question.topic_id.in_(topic_ids), Question.id.not_in(have))
                .order_by(func.random())
                .limit(n - len(picked))
            )
        )
    if len(picked) < n:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "question_bank_too_small")
    return sorted(picked, key=lambda q: q.difficulty)  # difficulty ramps up through the round


def _shuffle4() -> list[int]:
    order = [0, 1, 2, 3]
    secrets.SystemRandom().shuffle(order)
    return order


async def _create_session(
    db: AsyncSession,
    user: User,
    qs: list[Question],
    *,
    ranked: bool,
    lang: str,
    mode: str,
    topic: VisibleTopic | None,
    daily_day=None,
    extra: dict | None = None,
) -> dict:
    s = get_settings()
    now = utcnow()
    season = await get_or_create_season(db, now)
    orders = [_shuffle4() for _ in qs]
    keys = [sealing.new_key() for _ in qs]
    gs = GameSession(
        id=uuid.uuid4(),
        user_id=user.id,
        season_id=season.id,
        question_ids=[q.id for q in qs],
        question_topics=[q.topic_id for q in qs],
        topic_id=topic.id if topic else None,
        mode=mode,
        daily_day=daily_day,
        option_orders=orders,
        question_keys=keys,
        current_index=0,
        current_issued_at=now,
        answers=[],
        started_at=now,
        ranked=ranked,
        status=IN_PROGRESS,
    )
    db.add(gs)
    await db.execute(update(Question).where(Question.id.in_([q.id for q in qs])).values(times_served=Question.times_served + 1))
    sid = str(gs.id)
    slugs = await slug_map(db)
    sealed = []
    for i, (q, order) in enumerate(zip(qs, orders, strict=True)):
        text, opts = (q.question_ar, q.options_ar) if lang == "ar" else (q.question_en, q.options_en)
        payload = {"q": text, "o": [opts[j] for j in order], "c": q.category, "d": q.difficulty, "t": slugs.get(q.topic_id)}
        sealed.append({"index": i, **sealing.seal(keys[i], sid, i, payload)})
    await db.flush()  # surfaces the one-Daily-per-day unique index before we answer
    return {
        "session_id": sid,
        "mode": mode,
        "topic": topic.slug if topic else get_settings().mixed_slug,
        "questions": sealed,
        "first_key": keys[0],
        "time_limit_s": s.question_time_limit_s,
        "ranked": ranked,
        "fifty_price": s.price_fifty if mode == "SOLO" else None,
        "server_time": now.isoformat(),
        **(extra or {}),
    }


async def start(db: AsyncSession, user: User, *, ranked: bool, lang: str, topic: VisibleTopic | None = None) -> dict:
    s = get_settings()
    remaining = await lives.consume(db, user.id, cairo_today(utcnow()))
    if remaining is None:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "no_lives")  # client offers rewarded ad / coins
    qs = await _pick_questions(db, user.id, s.questions_per_round, topic)
    out = await _create_session(db, user, qs, ranked=ranked, lang=lang, mode="SOLO", topic=topic, extra={"lives_remaining": remaining})
    await db.commit()
    return out


async def _load_locked(db: AsyncSession, user: User, session_id: uuid.UUID) -> GameSession:
    gs = await db.scalar(select(GameSession).where(GameSession.id == session_id, GameSession.user_id == user.id).with_for_update())
    if gs is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session_not_found")
    return gs


def _round_score(gs: GameSession) -> int:
    return sum(a["points"] for a in gs.answers)


def _view(gs: GameSession, last: dict | None = None, next_key: str | None = None) -> dict:
    n = len(gs.question_ids)
    return {
        "session_id": str(gs.id),
        "status": gs.status,
        "answer": last,
        "round_score": _round_score(gs),
        "awarded_points": gs.score_awarded if gs.status in (COMPLETED, FLAGGED) else None,
        "next": {"index": gs.current_index, "key": next_key} if next_key else None,
        "revive_available": gs.status == AWAITING_REVIVE and not gs.revive_used,
        "correct_count": sum(1 for a in gs.answers if a["correct"]),
        "total_questions": n,
        "ranked": gs.ranked,
        "mode": gs.mode,
        "fifty_used": gs.fifty_used_at is not None,
        "rewards": gs.rewards,
    }


async def _complete(db: AsyncSession, gs: GameSession, user: User, now: datetime) -> list[points.Award]:
    s = get_settings()
    gs.completed_at = now
    duration = (now - gs.started_at).total_seconds()
    n = len(gs.question_ids)
    superhuman = sum(1 for a in gs.answers if a["correct"] and a["elapsed_ms"] < s.superhuman_answer_s * 1000)
    full_round = len(gs.answers) == n
    min_duration = s.min_round_duration_s * n / s.questions_per_round
    if (full_round and duration < min_duration) or superhuman >= s.superhuman_max_per_round:
        gs.status, gs.score_awarded = FLAGGED, 0
        strikes = await db.scalar(update(User).where(User.id == user.id).values(strikes=User.strikes + 1).returning(User.strikes))
        if strikes >= s.strikes_before_ban:
            await db.execute(
                update(User).where(User.id == user.id).values(is_banned=True, ban_reason="auto: repeated non-human answer timing")
            )
        return []
    gs.status = COMPLETED
    score = _round_score(gs)
    # XP, coins, streak, mastery, badges: personal progress, granted even for unranked rounds.
    gs.rewards = await progression.on_round_complete(db, user.id, gs, score)
    if not gs.ranked or score <= 0:
        gs.score_awarded = 0
        return []
    season = await db.get(WeeklySeason, gs.season_id)
    slugs = await slug_map(db)
    topic_points: dict[str, int] = {}
    for a, tid in zip(gs.answers, gs.question_topics, strict=False):
        if a["points"]:
            topic_points[slugs[tid]] = topic_points.get(slugs[tid], 0) + a["points"]
    # Points go to the season in which the round STARTED (a round straddling the reset counts for the old week).
    awards = await points.award(
        db,
        user_id=user.id,
        club=user.favorite_club,
        season=season,
        source="DAILY" if gs.mode == "DAILY" else "TRIVIA",
        ref=str(gs.id),
        points=score,
        now=now,
        topic_points=topic_points,
    )
    gs.score_awarded = score if awards else 0
    return awards


async def answer(db: AsyncSession, user: User, session_id: uuid.UUID, index: int, selected: int | None) -> dict:
    s = get_settings()
    now = utcnow()
    gs = await _load_locked(db, user, session_id)

    # Idempotent retry (response lost on a flaky connection): replay the stored result.
    if index < len(gs.answers):
        prev = gs.answers[index]
        nxt = gs.question_keys[gs.current_index] if gs.status == IN_PROGRESS and gs.current_index == index + 1 else None
        view = _view(gs, prev, nxt)
        await db.rollback()  # release the row lock
        return view
    if gs.status != IN_PROGRESS:
        raise _conflict(f"session_{gs.status.lower()}")
    if index != gs.current_index:
        raise _conflict("wrong_question_index")

    elapsed = (now - gs.current_issued_at).total_seconds()
    timed_out = selected is None or elapsed > s.question_time_limit_s + s.answer_grace_s
    q = await db.get(Question, gs.question_ids[index])
    correct_display = gs.option_orders[index].index(q.correct_option_index)
    correct = (not timed_out) and selected == correct_display
    remaining = max(0, math.floor(s.question_time_limit_s - elapsed))
    pts = s.base_points + remaining * s.speed_bonus_per_second if correct else 0
    result = {
        "index": index,
        "selected": selected,
        "correct": correct,
        "correct_option": correct_display,
        "timed_out": timed_out,
        "elapsed_ms": int(elapsed * 1000),
        "points": pts,
    }
    gs.answers = [*gs.answers, result]  # reassign so SQLAlchemy detects the JSONB change
    await db.execute(update(Question).where(Question.id == q.id).values(times_correct=Question.times_correct + (1 if correct else 0)))

    awards: list[points.Award] = []
    next_key = None
    is_last = index == len(gs.question_ids) - 1
    if not is_last and (correct or gs.mode == "DAILY"):
        gs.current_index, gs.current_issued_at = index + 1, now
        next_key = gs.question_keys[index + 1]
    elif not correct and not is_last and not gs.revive_used:
        gs.status, gs.current_issued_at = AWAITING_REVIVE, now  # revive window starts now
    else:
        awards = await _complete(db, gs, user, now)
    view = _view(gs, result, next_key)
    await db.commit()
    await points.push_to_cache(awards)
    return view


async def resume_after_revive(db: AsyncSession, user: User, session_id: uuid.UUID, intent_id: uuid.UUID) -> dict:
    s = get_settings()
    now = utcnow()
    gs = await _load_locked(db, user, session_id)
    if gs.status != AWAITING_REVIVE or gs.revive_used:
        raise _conflict("revive_not_available")
    if (now - gs.current_issued_at).total_seconds() > s.revive_window_s:
        raise _conflict("revive_window_expired")
    consumed = await db.scalar(
        update(RewardIntent)
        .where(
            RewardIntent.id == intent_id,
            RewardIntent.user_id == user.id,
            RewardIntent.purpose == "REVIVE",
            RewardIntent.ref == str(gs.id),
            RewardIntent.status == "GRANTED",
        )
        .values(status="CONSUMED")
        .returning(RewardIntent.id)
    )
    if consumed is None:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "reward_not_verified_yet")  # client polls
    gs.revive_used = True
    gs.status = IN_PROGRESS
    gs.current_index += 1  # the missed question is skipped (0 pts), the streak continues
    gs.current_issued_at = now  # fresh clock AFTER the ad closed
    view = _view(gs, None, gs.question_keys[gs.current_index])
    await db.commit()
    return view


async def finish(db: AsyncSession, user: User, session_id: uuid.UUID) -> dict:
    gs = await _load_locked(db, user, session_id)
    awards: list[points.Award] = []
    if gs.status in (IN_PROGRESS, AWAITING_REVIVE):
        awards = await _complete(db, gs, user, utcnow())
    view = _view(gs)
    await db.commit()
    await points.push_to_cache(awards)
    return view


async def fifty_fifty(db: AsyncSession, user: User, session_id: uuid.UUID, index: int) -> dict:
    """Removes two wrong options from the CURRENT question for coins. Solo rounds only, once per round,
    and the round becomes unranked: coins must never buy leaderboard position."""
    s = get_settings()
    gs = await _load_locked(db, user, session_id)
    if gs.mode != "SOLO" or gs.status != IN_PROGRESS:
        raise _conflict("fifty_not_allowed")
    if gs.fifty_used_at is not None:
        raise _conflict("fifty_already_used")
    if index != gs.current_index:
        raise _conflict("wrong_question_index")
    balance = await economy.debit(db, user.id, s.price_fifty, "FIFTY", f"{gs.id}:{index}")
    q = await db.get(Question, gs.question_ids[index])
    correct_display = gs.option_orders[index].index(q.correct_option_index)
    wrong = [i for i in range(4) if i != correct_display]
    remove = sorted(secrets.SystemRandom().sample(wrong, 2))
    gs.fifty_used_at = index
    gs.ranked = False
    await db.commit()
    return {"remove": remove, "coins": balance, "ranked": False}
