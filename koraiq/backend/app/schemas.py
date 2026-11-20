from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Outcome = Literal["HOME", "DRAW", "AWAY"]
Lang = Literal["ar", "en"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---- users -----------------------------------------------------------------
class OnboardingIn(Strict):
    nickname: str = Field(min_length=3, max_length=40)
    favorite_club: str
    birth_date: date = Field(description="Used once for the 13+ neutral age gate; NEVER stored.")
    accept_terms_version: str
    locale: Lang = "ar"


class ProfilePatch(Strict):
    nickname: str | None = Field(default=None, min_length=3, max_length=40)
    locale: Lang | None = None


class MeOut(BaseModel):
    id: str
    nickname: str | None
    favorite_club: str | None
    locale: str
    is_guest: bool
    lives: int
    ad_lives_left_today: int
    all_time_points: int
    season_points: int
    season_rank: int | None
    needs_onboarding: bool
    terms_version_current: str
    is_banned: bool
    level: int
    xp: int
    xp_level_start: int
    xp_next_level: int
    coins: int
    streak_days: int
    streak_freezes: int
    played_today: bool
    equipped: dict


# ---- game ------------------------------------------------------------------
class StartIn(Strict):
    lang: Lang = "ar"
    topic: str = Field(default="mixed", max_length=30, description="topic slug, or 'mixed'")


class FiftyIn(Strict):
    index: int = Field(ge=0, le=49)


class BuyIn(Strict):
    item: str = Field(max_length=40)


class EquipIn(Strict):
    kind: Literal["FRAME", "TITLE", "THEME"]
    code: str | None = Field(default=None, max_length=40)


class ReportIn(Strict):
    session_id: str
    index: int = Field(ge=0, le=49)
    reason: str | None = Field(default=None, max_length=200)


class AnswerIn(Strict):
    index: int = Field(ge=0, le=49)
    selected: int | None = Field(default=None, ge=0, le=3, description="null = timer expired on device")


class ResumeIn(Strict):
    intent_id: str


# ---- predictions -----------------------------------------------------------
class PredictionIn(Strict):
    fixture_id: int
    outcome: Outcome
    home_goals: int | None = Field(default=None, ge=0, le=20)
    away_goals: int | None = Field(default=None, ge=0, le=20)


class FixtureOut(BaseModel):
    id: int
    competition: str
    home_team: str
    away_team: str
    kickoff_time: datetime
    locks_at: datetime
    locked: bool
    status: str
    home_goals: int | None
    away_goals: int | None
    points_reward: int
    exact_score_bonus: int
    my_prediction: dict | None


# ---- rewards ---------------------------------------------------------------
class IntentIn(Strict):
    purpose: Literal["REVIVE", "DOUBLE_PREDICTION", "EXTRA_LIFE", "COIN_BONUS"]
    ref: str | None = Field(default=None, max_length=64)


class IntentOut(BaseModel):
    intent_id: str
    status: str
    ssv_user_id: str
    ssv_custom_data: str


# ---- admin -----------------------------------------------------------------
class FixtureIn(Strict):
    competition: str = "EPL_EGYPT"
    home_team_ar: str
    home_team_en: str
    away_team_ar: str
    away_team_en: str
    kickoff_time: datetime
    points_reward: int = Field(default=300, ge=0, le=5000)
    exact_score_bonus: int = Field(default=200, ge=0, le=5000)

    @field_validator("kickoff_time")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("kickoff_time must include a timezone offset")
        return v


class FixtureResultIn(Strict):
    status: Literal["FINISHED", "POSTPONED", "CANCELLED"]
    home_goals: int | None = Field(default=None, ge=0, le=30)
    away_goals: int | None = Field(default=None, ge=0, le=30)
    new_kickoff_time: datetime | None = None


class QuestionIn(Strict):
    topic: str = Field(max_length=30, description="topic slug")
    category: str = Field(max_length=50)
    difficulty: int = Field(ge=1, le=3)
    question_ar: str = Field(min_length=5, max_length=300)
    question_en: str = Field(min_length=5, max_length=300)
    options_ar: list[str] = Field(min_length=4, max_length=4)
    options_en: list[str] = Field(min_length=4, max_length=4)
    correct_option_index: int = Field(ge=0, le=3)
    source_note: str | None = None
    reviewed_by: str | None = Field(default=None, max_length=100)
    is_active: bool = True


class TopicIn(Strict):
    name_ar: str = Field(max_length=60)
    name_en: str = Field(max_length=60)
    icon: str = Field(default="quiz", max_length=30)
    color: str = Field(default="#0B8F4D", pattern=r"^#[0-9A-Fa-f]{6}$")
    sort_order: int = 0
    is_active: bool = True
    featured_from: date | None = None
    featured_to: date | None = None


class SponsorIn(Strict):
    sponsor_name: str | None = Field(default=None, max_length=100)
    sponsor_logo_url: str | None = Field(default=None, pattern=r"^https://")
    sponsor_click_url: str | None = Field(default=None, pattern=r"^https://")
    sponsor_promo_code: str | None = Field(default=None, max_length=50)
    sponsor_message_ar: str | None = Field(default=None, max_length=300)
    sponsor_message_en: str | None = Field(default=None, max_length=300)


class BanIn(Strict):
    banned: bool
    reason: str | None = None
