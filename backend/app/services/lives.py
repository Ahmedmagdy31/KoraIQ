"""Daily lives with lazy reset at Cairo midnight (no cron needed, no thundering-herd UPDATE)."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import case, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import User


def effective_lives(user: User, today: date) -> tuple[int, int]:
    """(lives, ad_lives_used_today) as they are *now*, applying a pending daily reset."""
    if user.lives_day != today:
        return get_settings().daily_free_lives, 0
    return user.daily_lives, user.ad_lives_today


async def consume(db: AsyncSession, user_id: uuid.UUID, today: date) -> int | None:
    """Atomically take one life. Returns remaining lives or None if none left."""
    free = get_settings().daily_free_lives
    new_day = User.lives_day.is_distinct_from(today)
    return await db.scalar(
        update(User)
        .where(User.id == user_id, new_day | (User.daily_lives > 0))
        .values(
            daily_lives=case((new_day, free - 1), else_=User.daily_lives - 1),
            ad_lives_today=case((new_day, 0), else_=User.ad_lives_today),
            lives_day=today,
        )
        .returning(User.daily_lives)
    )


async def grant_ad_life(db: AsyncSession, user_id: uuid.UUID, today: date) -> int | None:
    """+1 life from a verified rewarded ad, capped per Cairo day. Returns lives or None if capped."""
    s = get_settings()
    new_day = User.lives_day.is_distinct_from(today)
    return await db.scalar(
        update(User)
        .where(User.id == user_id, new_day | (User.ad_lives_today < s.daily_ad_lives_cap))
        .values(
            daily_lives=case((new_day, s.daily_free_lives + 1), else_=User.daily_lives + 1),
            ad_lives_today=case((new_day, 1), else_=User.ad_lives_today + 1),
            lives_day=today,
        )
        .returning(User.daily_lives)
    )


async def add_life(db: AsyncSession, user_id: uuid.UUID, today: date) -> int:
    """+1 life bought with coins (cap enforced by the shop)."""
    s = get_settings()
    new_day = User.lives_day.is_distinct_from(today)
    return await db.scalar(
        update(User)
        .where(User.id == user_id)
        .values(
            daily_lives=case((new_day, s.daily_free_lives + 1), else_=User.daily_lives + 1),
            ad_lives_today=case((new_day, 0), else_=User.ad_lives_today),
            lives_day=today,
        )
        .returning(User.daily_lives)
    )
