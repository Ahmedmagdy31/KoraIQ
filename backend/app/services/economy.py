"""Coins: earned by playing / verified ads, spent in the shop. Never purchasable with money.

Every movement is a coin_ledger row (idempotent per user+reason+ref); users.coins is the cached balance,
guarded by a CHECK (coins >= 0) so a race can never overdraw.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import CoinLedger, User
from app.services import seasons


async def credit(db: AsyncSession, user_id: uuid.UUID, amount: int, reason: str, ref: str) -> bool:
    """Idempotent credit. Returns False if this (reason, ref) was already credited."""
    if amount <= 0:
        return False
    row = await db.scalar(
        insert(CoinLedger)
        .values(user_id=user_id, delta=amount, reason=reason, ref=ref, created_at=seasons.utcnow())
        .on_conflict_do_nothing(constraint="uq_coin_idempotency")
        .returning(CoinLedger.id)
    )
    if row is None:
        return False
    await db.execute(update(User).where(User.id == user_id).values(coins=User.coins + amount))
    return True


async def debit(db: AsyncSession, user_id: uuid.UUID, amount: int, reason: str, ref: str | None = None) -> int:
    """Atomic spend. Returns the new balance or raises 402 insufficient_coins."""
    balance = await db.scalar(
        update(User).where(User.id == user_id, User.coins >= amount).values(coins=User.coins - amount).returning(User.coins)
    )
    if balance is None:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "insufficient_coins")
    db.add(CoinLedger(user_id=user_id, delta=-amount, reason=reason, ref=ref or uuid.uuid4().hex, created_at=seasons.utcnow()))
    return int(balance)


def cairo_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    tz = get_settings().tz
    day = seasons.cairo_today(now)
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


async def count_today(db: AsyncSession, user_id: uuid.UUID, reason: str) -> int:
    start, end = cairo_day_bounds(seasons.utcnow())
    return int(
        await db.scalar(
            select(func.count())
            .select_from(CoinLedger)
            .where(
                CoinLedger.user_id == user_id,
                CoinLedger.reason == reason,
                CoinLedger.created_at >= start,
                CoinLedger.created_at < end,
            )
        )
        or 0
    )
