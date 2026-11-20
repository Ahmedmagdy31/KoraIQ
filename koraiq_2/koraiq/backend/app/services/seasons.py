"""Weekly seasons in Africa/Cairo time.

A season covers Saturday 00:00 -> Friday 23:59:59.999 Cairo local time (i.e. it *ends* at the
next Saturday 00:00). Egypt re-introduced summer DST in 2023, so boundaries are computed with
zoneinfo, never with a fixed UTC+2 offset.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import WeeklySeason

SATURDAY = 5  # Monday=0


def utcnow() -> datetime:
    return datetime.now(UTC)


def cairo_today(now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(get_settings().tz).date()


def season_bounds(now: datetime) -> tuple[datetime, datetime]:
    tz = get_settings().tz
    local = now.astimezone(tz)
    days_since_sat = (local.weekday() - SATURDAY) % 7
    start_date = local.date() - timedelta(days=days_since_sat)
    start = datetime.combine(start_date, time.min, tzinfo=tz)
    end = datetime.combine(start_date + timedelta(days=7), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


async def get_or_create_season(db: AsyncSession, now: datetime | None = None) -> WeeklySeason:
    now = now or utcnow()
    start, end = season_bounds(now)
    found = await db.scalar(select(WeeklySeason).where(WeeklySeason.starts_at == start))
    if found:
        return found
    label_date = start.astimezone(get_settings().tz).date()
    await db.execute(
        insert(WeeklySeason)
        .values(season_name=f"Week of {label_date.isoformat()}", starts_at=start, ends_at=end)
        .on_conflict_do_nothing(index_elements=["starts_at"])
    )
    return (await db.scalars(select(WeeklySeason).where(WeeklySeason.starts_at == start))).one()
