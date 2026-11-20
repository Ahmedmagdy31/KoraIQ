from __future__ import annotations

import time
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import worker
from app.db import sessionmaker
from app.models import GameSession, SeasonResult, WeeklySeason
from app.security import integrity, ratelimit
from tests.conftest import auth, onboard
from tests.test_flows import _correct_and_wrong

API = "/api/v1"


def _payload(**over):
    p = {
        "requestDetails": {
            "requestPackageName": "com.koraiq.app",
            "requestHash": integrity.request_hash("game_start", "u", "n" * 32),
            "timestampMillis": str(int(time.time() * 1000)),
        },
        "appIntegrity": {"appRecognitionVerdict": "PLAY_RECOGNIZED", "packageName": "com.koraiq.app", "certificateSha256Digest": ["abc"]},
        "deviceIntegrity": {"deviceRecognitionVerdict": ["MEETS_DEVICE_INTEGRITY"]},
    }
    p.update(over)
    return p


def test_integrity_verdicts():
    h = integrity.request_hash("game_start", "u", "n" * 32)
    assert integrity.evaluate(_payload(), h).ok
    assert integrity.evaluate(_payload(), integrity.request_hash("game_start", "OTHER", "n" * 32)).reason == "request_hash"
    assert integrity.evaluate(_payload(deviceIntegrity={"deviceRecognitionVerdict": []}), h).reason == "device"
    assert integrity.evaluate(_payload(appIntegrity={"appRecognitionVerdict": "UNRECOGNIZED_VERSION"}), h).reason == "app_not_recognized"


async def test_rate_limiter_blocks_and_reports_retry_after():
    bucket = f"t:{uuid.uuid4()}"
    for _ in range(3):
        await ratelimit.hit(bucket, 3)
    with pytest.raises(HTTPException) as e:
        await ratelimit.hit(bucket, 3)
    assert e.value.status_code == 429 and int(e.value.headers["Retry-After"]) >= 1


async def test_season_finalization_and_stale_sessions(client, clock, monkeypatch):
    await onboard(client, "w1", "Winner_One")
    sid = (await client.post(f"{API}/game/start", headers=auth("w1"), json={})).json()["session_id"]
    right, _ = await _correct_and_wrong(sid, 0)
    clock.advance(5)
    await client.post(f"{API}/game/{sid}/answer", headers=auth("w1"), json={"index": 0, "selected": right})

    # Abandoned mid-round -> the worker closes it and still credits the earned points.
    clock.advance(3600)
    await worker.expire_stale_sessions()
    async with sessionmaker()() as db:
        gs = await db.get(GameSession, uuid.UUID(sid))
        assert gs.status == "COMPLETED" and gs.score_awarded == 200

    clock.advance(8 * 86400)  # the week is over
    await worker.finalize_seasons()
    await worker.finalize_seasons()  # idempotent
    async with sessionmaker()() as db:
        seasons = list(await db.scalars(select(WeeklySeason).order_by(WeeklySeason.starts_at)))
        assert seasons[0].finalized and not seasons[-1].finalized
        res = list(await db.scalars(select(SeasonResult)))
        assert len(res) == 1 and res[0].rank == 1 and res[0].points == 200 and res[0].reward_cosmetic == "FRAME_CHAMPION"
        assert seasons[-1].starts_at - seasons[0].starts_at >= timedelta(days=7)
