"""Central configuration. Every value is overridable via environment variables (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "KoraIQ"
    api_prefix: str = "/api/v1"

    # Infrastructure
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/koraiq"
    redis_url: str = "redis://localhost:6379/0"
    db_pool_size: int = 10

    # Auth: "firebase" in every real environment. "dev" accepts `Bearer dev:<uid>[:admin]`
    # and is refused at startup unless env is development/test.
    auth_mode: Literal["firebase", "dev"] = "firebase"
    firebase_credentials: str | None = Field(default=None, description="Path to, or inline JSON of, the Firebase service-account key.")
    firebase_check_revoked: bool = False

    # Play Integrity: off | soft (play allowed, results unranked) | enforce (403)
    integrity_mode: Literal["off", "soft", "enforce"] = "off"
    android_package_name: str = "com.koraiq.app"
    integrity_max_token_age_s: int = 300
    integrity_allowed_cert_sha256: list[str] = Field(default_factory=list)

    # AdMob SSV
    admob_ssv_keys_url: str = "https://www.gstatic.com/admob/reward/verifier-keys.json"
    admob_allowed_ad_units: list[str] = Field(default_factory=list)  # empty = allow any (dev)

    # Game rules
    timezone: str = "Africa/Cairo"
    questions_per_round: int = 10
    question_time_limit_s: int = 15
    answer_grace_s: float = 2.0  # network tolerance on weak 3G links
    base_points: int = 100
    speed_bonus_per_second: int = 10
    min_round_duration_s: float = 8.0
    superhuman_answer_s: float = 0.6  # correct answers faster than this (server-measured) are suspicious
    superhuman_max_per_round: int = 3
    recent_sessions_no_repeat: int = 3
    strikes_before_ban: int = 3
    daily_free_lives: int = 5
    daily_ad_lives_cap: int = 10
    revive_window_s: int = 180
    stale_session_after_s: int = 900

    # Predictions
    prediction_lock_minutes: int = 15
    exact_score_bonus: int = 200

    # Topics
    topic_min_questions: int = 10  # a topic is hidden until it has this many active questions
    mixed_slug: str = "mixed"
    reports_to_deactivate: int = 3

    # Progression (all server-side: change via env + restart, no app release needed)
    xp_per_round_finish: int = 20
    xp_points_divisor: int = 10
    xp_level_base: int = 100
    xp_level_step: int = 50
    mastery_tiers: list[tuple[str, int]] = Field(
        default_factory=lambda: [("BRONZE", 50), ("SILVER", 200), ("GOLD", 600), ("DIAMOND", 1500)]
    )
    streak_milestones: dict[int, int] = Field(default_factory=lambda: {3: 20, 7: 50, 30: 200, 100: 500, 365: 1000})
    lightning_ms: int = 3000
    ramadan_ranges: list[tuple[str, str]] = Field(default_factory=list)  # [("2027-02-08","2027-03-09")] set by admin

    # Economy (coins can be earned, never bought)
    coins_round_finish: int = 10
    coins_perfect_bonus: int = 10
    coins_daily: int = 15
    coins_ad_bonus: int = 25
    coins_ad_bonus_daily_cap: int = 3
    price_streak_freeze: int = 150
    max_streak_freezes: int = 2
    price_extra_life: int = 60
    extra_life_daily_cap: int = 5
    price_fifty: int = 40
    weekly_top3_coins: list[int] = Field(default_factory=lambda: [300, 200, 100])

    # Daily Challenge
    daily_questions: int = 5
    daily_epoch: str = "2026-11-01"  # Daily #1

    # Leaderboard
    leaderboard_top_global: int = 50
    leaderboard_top_club: int = 10
    season_winners_snapshot: int = 100

    # Rate limits (requests / 60s). Egyptian mobile carriers use heavy CGNAT, so IP limits are
    # deliberately generous and the real control is per-user.
    rl_auth_per_ip: int = 60
    rl_auth_per_user: int = 5
    rl_game_per_user: int = 30
    rl_default_per_user: int = 120

    clubs: list[str] = Field(default_factory=lambda: ["AHLY", "ZAMALEK", "PYRAMIDS", "ISMAILY", "ITTIHAD", "MASRY", "OTHER"])
    terms_version: str = "2026-11"
    support_email: str = "privacy@koraiq.app"
    cors_origins: list[str] = Field(default_factory=list)
    trusted_proxy_hops: int = 1

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def max_points_per_question(self) -> int:
        return self.base_points + self.question_time_limit_s * self.speed_bonus_per_second

    @model_validator(mode="after")
    def _guard_prod(self) -> Settings:
        if self.env in ("staging", "production"):
            if self.auth_mode != "firebase":
                raise ValueError("auth_mode must be 'firebase' outside development/test")
            if self.integrity_mode == "off":
                raise ValueError("integrity_mode cannot be 'off' in staging/production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
