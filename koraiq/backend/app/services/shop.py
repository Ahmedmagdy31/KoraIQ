"""Coin shop: streak freezes, extra lives, cosmetics. All digital; nothing costs the operator money."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Cosmetic, User, UserCosmetic
from app.services import economy, lives, seasons

SLOTS = {"FRAME": "equipped_frame", "TITLE": "equipped_title", "THEME": "equipped_theme"}


def _cosmetic_out(c: Cosmetic, owned: set[str], user: User, lang: str) -> dict:
    return {
        "code": c.code,
        "kind": c.kind,
        "name": c.name_ar if lang == "ar" else c.name_en,
        "price": c.price,
        "exclusive": c.price is None,
        "owned": c.code in owned,
        "equipped": getattr(user, SLOTS[c.kind]) == c.code,
        "asset": c.asset,
    }


async def owned_codes(db: AsyncSession, user: User) -> set[str]:
    return set(await db.scalars(select(UserCosmetic.cosmetic_code).where(UserCosmetic.user_id == user.id)))


async def catalogue(db: AsyncSession, user: User, lang: str) -> dict:
    s = get_settings()
    owned = await owned_codes(db, user)
    cosmetics = await db.scalars(select(Cosmetic).where(Cosmetic.is_active).order_by(Cosmetic.kind, Cosmetic.sort_order))
    lives_bought = await economy.count_today(db, user.id, "BUY_LIFE")
    return {
        "coins": user.coins,
        "items": [
            {"code": "STREAK_FREEZE", "price": s.price_streak_freeze, "owned": user.streak_freezes, "max": s.max_streak_freezes},
            {"code": "EXTRA_LIFE", "price": s.price_extra_life, "bought_today": lives_bought, "max": s.extra_life_daily_cap},
        ],
        # Exclusive cosmetics are shown only once owned (they're trophies, not stock).
        "cosmetics": [_cosmetic_out(c, owned, user, lang) for c in cosmetics if c.price is not None or c.code in owned],
    }


async def buy(db: AsyncSession, user: User, item: str) -> dict:
    s = get_settings()
    locked = await db.scalar(select(User).where(User.id == user.id).with_for_update())
    if item == "STREAK_FREEZE":
        if locked.streak_freezes >= s.max_streak_freezes:
            raise HTTPException(status.HTTP_409_CONFLICT, "max_freezes")
        await economy.debit(db, user.id, s.price_streak_freeze, "BUY_FREEZE")
        locked.streak_freezes += 1
    elif item == "EXTRA_LIFE":
        if await economy.count_today(db, user.id, "BUY_LIFE") >= s.extra_life_daily_cap:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "daily_cap_reached")
        await economy.debit(db, user.id, s.price_extra_life, "BUY_LIFE")
        await db.flush()
        await lives.add_life(db, user.id, seasons.cairo_today())
    else:
        c = await db.get(Cosmetic, item)
        if c is None or not c.is_active or c.price is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "item_not_found")
        if item in await owned_codes(db, user):
            raise HTTPException(status.HTTP_409_CONFLICT, "already_owned")
        await economy.debit(db, user.id, c.price, "BUY_COSMETIC", c.code)
        db.add(UserCosmetic(user_id=user.id, cosmetic_code=c.code, acquired_at=seasons.utcnow()))
    await db.commit()
    await db.refresh(user)
    return {"coins": user.coins, "streak_freezes": user.streak_freezes}


async def grant_exclusive(db: AsyncSession, user_id, code: str) -> bool:
    row = await db.scalar(
        insert(UserCosmetic)
        .values(user_id=user_id, cosmetic_code=code, acquired_at=seasons.utcnow())
        .on_conflict_do_nothing()
        .returning(UserCosmetic.cosmetic_code)
    )
    return row is not None


async def equip(db: AsyncSession, user: User, kind: str, code: str | None) -> dict:
    if kind not in SLOTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_kind")
    if code is not None:
        c = await db.get(Cosmetic, code)
        if c is None or c.kind != kind or code not in await owned_codes(db, user):
            raise HTTPException(status.HTTP_409_CONFLICT, "not_owned")
    await db.execute(update(User).where(User.id == user.id).values({SLOTS[kind]: code}))
    await db.commit()
    await db.refresh(user)
    return {"frame": user.equipped_frame, "title": user.equipped_title, "theme": user.equipped_theme}
