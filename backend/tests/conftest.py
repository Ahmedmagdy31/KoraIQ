"""Integration tests against REAL PostgreSQL + Redis (no SQLite fakes: we rely on ON CONFLICT,
JSONB, ARRAY, row locks and gen_random_uuid()).

    TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/koraiq_test
    TEST_REDIS_URL=redis://localhost:6379/15
"""

from __future__ import annotations

import base64
import os
import time
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta

os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://postgres@127.0.0.1:5432/koraiq_test")
os.environ["REDIS_URL"] = os.getenv("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
os.environ["ENV"] = "test"
os.environ["AUTH_MODE"] = "dev"
os.environ["INTEGRITY_MODE"] = "off"

import pytest  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, get_engine, sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.redis_client import get_redis  # noqa: E402
from app.security import admob_ssv  # noqa: E402
from scripts.seed_questions import seed_catalogue, seed_questions  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture(autouse=True)
async def fresh_state():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await get_redis().flushdb()
    async with sessionmaker()() as db:
        topic_ids = await seed_catalogue(db)
        await seed_questions(db, topic_ids)
        await db.commit()
    yield


@pytest.fixture
def clock(monkeypatch) -> Clock:
    c = Clock()
    for mod in (
        "app.services.game",
        "app.services.predictions",
        "app.services.rewards",
        "app.services.seasons",
        "app.routers.users",
        "app.routers.predictions",
        "app.routers.leaderboard",
        "app.worker",
    ):
        monkeypatch.setattr(f"{mod}.utcnow", c, raising=False)
    return c


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def auth(uid: str, *extra: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + ":".join(["dev", uid, *extra])}


async def onboard(client: AsyncClient, uid: str, nick: str, club: str = "AHLY") -> dict:
    r = await client.post("/api/v1/auth/sync", headers=auth(uid))
    assert r.status_code == 200, r.text
    r = await client.post(
        "/api/v1/users/me/onboarding",
        headers=auth(uid),
        json={"nickname": nick, "favorite_club": club, "birth_date": "2000-01-01", "accept_terms_version": "2026-11"},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---- AdMob SSV test signer -------------------------------------------------
_SSV_KEY = ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def ssv(monkeypatch):
    monkeypatch.setattr(admob_ssv, "_KEYS", {"9999": _SSV_KEY.public_key()})
    monkeypatch.setattr(admob_ssv, "_KEYS_FETCHED_AT", time.time())

    def build(user_id: str, custom_data: str, tx: str | None = None, tamper: bool = False) -> str:
        params = [
            ("ad_network", "5450213213286189855"),
            ("ad_unit", "1234567890"),
            ("custom_data", custom_data),
            ("reward_amount", "1"),
            ("reward_item", "Reward"),
            ("timestamp", str(int(time.time() * 1000))),
            ("transaction_id", tx or uuid.uuid4().hex),
            ("user_id", user_id),
        ]
        msg = urllib.parse.urlencode(params)
        sig = base64.urlsafe_b64encode(_SSV_KEY.sign(msg.encode(), ec.ECDSA(hashes.SHA256()))).decode().rstrip("=")
        if tamper:
            msg = msg.replace("reward_amount=1", "reward_amount=9")
        return f"/api/v1/webhooks/admob-ssv?{msg}&signature={sig}&key_id=9999"

    return build
