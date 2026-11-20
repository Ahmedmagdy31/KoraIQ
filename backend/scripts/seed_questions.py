"""Idempotent seed: `python -m scripts.seed_questions` (run from /backend after `alembic upgrade head`).

Upserts topics, badges and cosmetics; inserts questions not yet present (matched by English text);
adds sample fixtures only into an empty fixtures table.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import dispose_engine, sessionmaker
from app.models import Badge, Cosmetic, Fixture, Question, Topic
from app.services.seasons import get_or_create_season, utcnow
from scripts.seed_data import BADGES, COSMETICS, FIXTURES, TOPIC_QUESTIONS, TOPICS


def validate() -> None:
    seen = set()
    for slug, qs in TOPIC_QUESTIONS.items():
        for i, (_cat, diff, en, _ar, oen, oar, correct, _src) in enumerate(qs):
            where = f"{slug}[{i}]"
            assert diff in (1, 2, 3), where
            assert len(oen) == 4 and len(oar) == 4, where
            assert len(set(oen)) == 4 and len(set(oar)) == 4, f"duplicate option in {where}"
            assert 0 <= correct <= 3, where
            assert en not in seen, f"duplicate question {where}"
            seen.add(en)


async def seed_catalogue(db: AsyncSession) -> dict[str, int]:
    for slug, en, ar, icon, color, order in TOPICS:
        values = {"name_en": en, "name_ar": ar, "icon": icon, "color": color, "sort_order": order}
        await db.execute(insert(Topic).values(slug=slug, **values).on_conflict_do_update(index_elements=["slug"], set_=values))
    for code, en, ar, den, dar, icon, coins, order in BADGES:
        values = {
            "name_en": en,
            "name_ar": ar,
            "description_en": den,
            "description_ar": dar,
            "icon": icon,
            "coins_reward": coins,
            "sort_order": order,
        }
        await db.execute(insert(Badge).values(code=code, **values).on_conflict_do_update(index_elements=["code"], set_=values))
    for code, kind, en, ar, price, asset, order in COSMETICS:
        values = {"kind": kind, "name_en": en, "name_ar": ar, "price": price, "asset": asset, "sort_order": order}
        await db.execute(insert(Cosmetic).values(code=code, **values).on_conflict_do_update(index_elements=["code"], set_=values))
    return {s: i for s, i in (await db.execute(select(Topic.slug, Topic.id))).all()}


async def seed_questions(db: AsyncSession, topic_ids: dict[str, int]) -> int:
    existing = set(await db.scalars(select(Question.question_en)))
    added = 0
    for slug, qs in TOPIC_QUESTIONS.items():
        for cat, diff, en, ar, oen, oar, correct, src in qs:
            if en in existing:
                continue
            db.add(
                Question(
                    topic_id=topic_ids[slug],
                    category=cat,
                    difficulty=diff,
                    question_en=en,
                    question_ar=ar,
                    options_en=oen,
                    options_ar=oar,
                    correct_option_index=correct,
                    source_note=src,
                )
            )
            added += 1
    return added


async def main() -> None:
    validate()
    async with sessionmaker()() as db:
        topic_ids = await seed_catalogue(db)
        added_q = await seed_questions(db, topic_ids)
        added_f = 0
        if not await db.scalar(select(Fixture.id).limit(1)):
            base = utcnow().replace(minute=0, second=0, microsecond=0)
            for hen, har, aen, aar, comp, hours in FIXTURES:
                db.add(
                    Fixture(
                        home_team_en=hen,
                        home_team_ar=har,
                        away_team_en=aen,
                        away_team_ar=aar,
                        competition=comp,
                        kickoff_time=base + timedelta(hours=hours),
                    )
                )
                added_f += 1
        await get_or_create_season(db)
        await db.commit()
    await dispose_engine()
    print(f"seeded topics={len(TOPICS)} badges={len(BADGES)} cosmetics={len(COSMETICS)} questions={added_q} fixtures={added_f}")


if __name__ == "__main__":
    asyncio.run(main())
