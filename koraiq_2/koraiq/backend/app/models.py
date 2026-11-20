"""ORM models. Source of truth = PostgreSQL. Redis is a rebuildable cache for leaderboards/rate limits."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True)
    # Nullable until onboarding completes (Google sign-in happens before a nickname exists).
    nickname: Mapped[str | None] = mapped_column(String(20))
    # Normalised skeleton (Arabic letter folding, case folding, leet folding) -> blocks look-alike impersonation.
    nickname_key: Mapped[str | None] = mapped_column(String(40), unique=True)
    favorite_club: Mapped[str | None] = mapped_column(String(20))
    locale: Mapped[str] = mapped_column(String(5), server_default="ar")
    is_guest: Mapped[bool] = mapped_column(Boolean, server_default="true")

    daily_lives: Mapped[int] = mapped_column(SmallInteger, server_default="5")
    lives_day: Mapped[date | None] = mapped_column(Date)  # Cairo calendar day the counters belong to
    ad_lives_today: Mapped[int] = mapped_column(SmallInteger, server_default="0")

    all_time_points: Mapped[int] = mapped_column(BigInteger, server_default="0")
    # Progression & economy (v2). coins = cached balance of coin_ledger.
    xp: Mapped[int] = mapped_column(BigInteger, server_default="0")
    level: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    coins: Mapped[int] = mapped_column(Integer, server_default="0")
    streak_days: Mapped[int] = mapped_column(Integer, server_default="0")
    streak_last_day: Mapped[date | None] = mapped_column(Date)
    streak_freezes: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    equipped_frame: Mapped[str | None] = mapped_column(String(40))
    equipped_title: Mapped[str | None] = mapped_column(String(40))
    equipped_theme: Mapped[str | None] = mapped_column(String(40))
    strikes: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_banned: Mapped[bool] = mapped_column(Boolean, server_default="false")
    ban_reason: Mapped[str | None] = mapped_column(Text)

    terms_version: Mapped[str | None] = mapped_column(String(20))
    terms_accepted_at: Mapped[datetime | None] = mapped_column(TS)
    age_confirmed: Mapped[bool] = mapped_column(Boolean, server_default="false")  # 13+ via neutral age screen

    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("daily_lives >= 0", name="ck_users_lives_nonneg"),
        CheckConstraint("coins >= 0", name="ck_users_coins_nonneg"),
    )


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(30), unique=True)
    name_ar: Mapped[str] = mapped_column(String(60))
    name_en: Mapped[str] = mapped_column(String(60))
    icon: Mapped[str] = mapped_column(String(30), server_default="quiz")  # Material icon name used by the app
    color: Mapped[str] = mapped_column(String(7), server_default="#0B8F4D")
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    featured_from: Mapped[date | None] = mapped_column(Date)
    featured_to: Mapped[date | None] = mapped_column(Date)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), index=True)
    category: Mapped[str] = mapped_column(String(50))  # subtopic inside the topic
    difficulty: Mapped[int] = mapped_column(SmallInteger)
    question_ar: Mapped[str] = mapped_column(Text)
    question_en: Mapped[str] = mapped_column(Text)
    options_ar: Mapped[list[str]] = mapped_column(JSONB)
    options_en: Mapped[list[str]] = mapped_column(JSONB)
    correct_option_index: Mapped[int] = mapped_column(SmallInteger)
    source_note: Mapped[str | None] = mapped_column(Text)  # fact-check provenance for editors
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[datetime | None] = mapped_column(TS)
    reports: Mapped[int] = mapped_column(Integer, server_default="0")  # "report a mistake" counter
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Live difficulty calibration: editors can re-rate questions from real answer rates.
    times_served: Mapped[int] = mapped_column(Integer, server_default="0")
    times_correct: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    __table_args__ = (
        CheckConstraint("difficulty BETWEEN 1 AND 3", name="ck_q_difficulty"),
        CheckConstraint("correct_option_index BETWEEN 0 AND 3", name="ck_q_correct"),
        CheckConstraint("jsonb_array_length(options_ar) = 4 AND jsonb_array_length(options_en) = 4", name="ck_q_4opts"),
        Index("ix_questions_active_cat", "is_active", "category"),
    )


class WeeklySeason(Base):
    __tablename__ = "weekly_seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_name: Mapped[str] = mapped_column(String(100))
    starts_at: Mapped[datetime] = mapped_column(TS, unique=True)
    ends_at: Mapped[datetime] = mapped_column(TS)
    sponsor_name: Mapped[str | None] = mapped_column(String(100))
    sponsor_logo_url: Mapped[str | None] = mapped_column(Text)
    sponsor_promo_code: Mapped[str | None] = mapped_column(String(50))
    sponsor_click_url: Mapped[str | None] = mapped_column(Text)
    sponsor_message_ar: Mapped[str | None] = mapped_column(Text)
    sponsor_message_en: Mapped[str | None] = mapped_column(Text)
    finalized: Mapped[bool] = mapped_column(Boolean, server_default="false")


class GameSession(Base):
    __tablename__ = "game_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("weekly_seasons.id"))
    question_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    question_topics: Mapped[list[int]] = mapped_column(ARRAY(Integer))  # topic id per question (mixed rounds)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"))  # NULL = mixed
    mode: Mapped[str] = mapped_column(String(12), server_default="SOLO")  # SOLO | DAILY
    daily_day: Mapped[date | None] = mapped_column(Date)
    fifty_used_at: Mapped[int | None] = mapped_column(SmallInteger)  # question index where 50/50 was used
    rewards: Mapped[dict | None] = mapped_column(JSONB)  # XP/coins/badges granted at completion (for replay)
    option_orders: Mapped[list[list[int]]] = mapped_column(JSONB)  # per-session shuffle of the 4 options
    question_keys: Mapped[list[str]] = mapped_column(JSONB)  # base64 AES-256-GCM keys, never leave server unsolicited
    current_index: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    current_issued_at: Mapped[datetime | None] = mapped_column(TS)
    answers: Mapped[list[dict]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    started_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(TS)
    score_awarded: Mapped[int] = mapped_column(Integer, server_default="0")
    revive_used: Mapped[bool] = mapped_column(Boolean, server_default="false")
    ranked: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # IN_PROGRESS | AWAITING_REVIVE | COMPLETED | FLAGGED
    status: Mapped[str] = mapped_column(String(20), server_default="IN_PROGRESS")

    __table_args__ = (
        Index("ix_sessions_status_started", "status", "started_at"),
        # One Daily Challenge attempt per user per day, enforced by the database.
        Index("uq_daily_attempt", "user_id", "daily_day", unique=True, postgresql_where=text("mode = 'DAILY'")),
    )


class Fixture(Base):
    __tablename__ = "fixtures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competition: Mapped[str] = mapped_column(String(50), server_default="EPL_EGYPT")
    home_team_ar: Mapped[str] = mapped_column(String(100))
    home_team_en: Mapped[str] = mapped_column(String(100))
    away_team_ar: Mapped[str] = mapped_column(String(100))
    away_team_en: Mapped[str] = mapped_column(String(100))
    kickoff_time: Mapped[datetime] = mapped_column(TS, index=True)
    # SCHEDULED | FINISHED | POSTPONED | CANCELLED
    status: Mapped[str] = mapped_column(String(12), server_default="SCHEDULED")
    home_goals: Mapped[int | None] = mapped_column(SmallInteger)
    away_goals: Mapped[int | None] = mapped_column(SmallInteger)
    actual_result: Mapped[str | None] = mapped_column(String(10))  # HOME | DRAW | AWAY
    points_reward: Mapped[int] = mapped_column(Integer, server_default="300")
    exact_score_bonus: Mapped[int] = mapped_column(Integer, server_default="200")
    is_settled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    reminder_sent: Mapped[bool] = mapped_column(Boolean, server_default="false")


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id", ondelete="CASCADE"), index=True)
    predicted_outcome: Mapped[str] = mapped_column(String(10))
    predicted_home_goals: Mapped[int | None] = mapped_column(SmallInteger)
    predicted_away_goals: Mapped[int | None] = mapped_column(SmallInteger)
    is_double_points: Mapped[bool] = mapped_column(Boolean, server_default="false")
    ranked: Mapped[bool] = mapped_column(Boolean, server_default="true")
    points_earned: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "fixture_id", name="uq_prediction_user_fixture"),
        CheckConstraint("predicted_outcome IN ('HOME','DRAW','AWAY')", name="ck_pred_outcome"),
    )


class SeasonScore(Base):
    """Per-season points per scope ('all' or a topic slug). No destructive weekly reset."""

    __tablename__ = "season_scores"

    season_id: Mapped[int] = mapped_column(ForeignKey("weekly_seasons.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    scope: Mapped[str] = mapped_column(String(30), primary_key=True, server_default="all")
    points: Mapped[int] = mapped_column(Integer, server_default="0")
    last_scored_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())  # tie-break: earlier wins

    __table_args__ = (Index("ix_season_scores_rank", "season_id", "scope", text("points DESC"), "last_scored_at"),)


class PointsLedger(Base):
    """Append-only, idempotent audit trail of every point awarded (score disputes, fraud review)."""

    __tablename__ = "points_ledger"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("weekly_seasons.id"))
    source: Mapped[str] = mapped_column(String(20))  # TRIVIA | PREDICTION | ADJUSTMENT
    ref: Mapped[str] = mapped_column(String(64))
    points: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "source", "ref", name="uq_ledger_idempotency"),)


class RewardIntent(Base):
    """Server-issued nonce passed as AdMob SSV custom_data. Binds an ad view to (user, purpose, ref)."""

    __tablename__ = "reward_intents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(24))  # REVIVE | DOUBLE_PREDICTION | EXTRA_LIFE
    ref: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), server_default="PENDING")  # PENDING | GRANTED | CONSUMED | REJECTED
    transaction_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    granted_at: Mapped[datetime | None] = mapped_column(TS)


class SeasonResult(Base):
    __tablename__ = "season_results"

    season_id: Mapped[int] = mapped_column(ForeignKey("weekly_seasons.id"), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    nickname: Mapped[str] = mapped_column(String(20))
    favorite_club: Mapped[str | None] = mapped_column(String(20))
    points: Mapped[int] = mapped_column(Integer)
    reward_cosmetic: Mapped[str | None] = mapped_column(String(40))  # exclusive digital reward, no real prizes


class TopicMastery(Base):
    __tablename__ = "topic_mastery"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), primary_key=True)
    correct: Mapped[int] = mapped_column(Integer, server_default="0")


class CoinLedger(Base):
    """Append-only coin earn/spend log; users.coins is its cached sum. Idempotent per (user, reason, ref)."""

    __tablename__ = "coin_ledger"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(30))
    ref: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "reason", "ref", name="uq_coin_idempotency"),)


class Badge(Base):
    __tablename__ = "badges"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name_ar: Mapped[str] = mapped_column(String(60))
    name_en: Mapped[str] = mapped_column(String(60))
    description_ar: Mapped[str] = mapped_column(Text)
    description_en: Mapped[str] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(String(30), server_default="military_tech")
    coins_reward: Mapped[int] = mapped_column(Integer, server_default="0")
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")


class UserBadge(Base):
    __tablename__ = "user_badges"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    badge_code: Mapped[str] = mapped_column(ForeignKey("badges.code"), primary_key=True)
    awarded_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Cosmetic(Base):
    __tablename__ = "cosmetics"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # FRAME | THEME | TITLE
    name_ar: Mapped[str] = mapped_column(String(60))
    name_en: Mapped[str] = mapped_column(String(60))
    price: Mapped[int | None] = mapped_column(Integer)  # NULL = exclusive (earned, never sold)
    asset: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))  # e.g. {"colors": ["#...", "#..."]}
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class UserCosmetic(Base):
    __tablename__ = "user_cosmetics"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    cosmetic_code: Mapped[str] = mapped_column(ForeignKey("cosmetics.code"), primary_key=True)
    acquired_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class DailyChallenge(Base):
    __tablename__ = "daily_challenges"

    day: Mapped[date] = mapped_column(Date, primary_key=True)  # Cairo calendar day
    number: Mapped[int] = mapped_column(Integer)  # "KoraIQ #142"
    question_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer))


class QuestionReport(Base):
    """'Report a mistake'. One report per user per question; N distinct reports auto-deactivate a question."""

    __tablename__ = "question_reports"

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
