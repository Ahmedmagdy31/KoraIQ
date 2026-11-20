"""Topic catalogue. A topic is *visible* only when it is active AND has enough active questions, so a
new topic (e.g. Dialects, waiting for regional reviewers) can be created early and appears by itself
once its question bank is ready."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Question, Topic


@dataclass(frozen=True)
class VisibleTopic:
    id: int
    slug: str
    name_ar: str
    name_en: str
    icon: str
    color: str
    question_count: int
    featured: bool


async def visible_topics(db: AsyncSession, today: date | None = None) -> list[VisibleTopic]:
    s = get_settings()
    rows = (
        await db.execute(
            select(Topic, func.count(Question.id))
            .join(Question, (Question.topic_id == Topic.id) & Question.is_active, isouter=True)
            .where(Topic.is_active)
            .group_by(Topic.id)
            .order_by(Topic.sort_order, Topic.id)
        )
    ).all()
    out = []
    for t, n in rows:
        if n < s.topic_min_questions:
            continue
        featured = bool(today and t.featured_from and t.featured_to and t.featured_from <= today <= t.featured_to)
        out.append(VisibleTopic(t.id, t.slug, t.name_ar, t.name_en, t.icon, t.color, int(n), featured))
    return out


async def resolve(db: AsyncSession, slug: str | None) -> VisibleTopic | None:
    """None = mixed round. Raises 404 for unknown/hidden topics."""
    if slug in (None, "", get_settings().mixed_slug):
        return None
    for t in await visible_topics(db):
        if t.slug == slug:
            return t
    raise HTTPException(status.HTTP_404_NOT_FOUND, "topic_not_found")


async def slug_map(db: AsyncSession) -> dict[int, str]:
    return {i: s for i, s in (await db.execute(select(Topic.id, Topic.slug))).all()}
