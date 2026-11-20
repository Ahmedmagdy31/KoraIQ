from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.db import sessionmaker
from app.models import Fixture, GameSession, PointsLedger, Prediction, Question, User
from app.services import sealing
from tests.conftest import auth, onboard

API = "/api/v1"


async def _correct_and_wrong(session_id: str, index: int) -> tuple[int, int]:
    async with sessionmaker()() as db:
        gs = await db.get(GameSession, uuid.UUID(session_id))
        q = await db.get(Question, gs.question_ids[index])
        right = gs.option_orders[index].index(q.correct_option_index)
        return right, (right + 1) % 4


# ---------------------------------------------------------------------------
async def test_onboarding_rules(client):
    await client.post(f"{API}/auth/sync", headers=auth("kid"))
    r = await client.post(
        f"{API}/users/me/onboarding",
        headers=auth("kid"),
        json={"nickname": "Kiddo", "favorite_club": "AHLY", "birth_date": "2020-01-01", "accept_terms_version": "2026-11"},
    )
    assert r.status_code == 403 and r.json()["detail"] == "under_minimum_age"
    r = await client.post(f"{API}/game/start", headers=auth("kid"), json={})
    assert r.status_code == 428

    await onboard(client, "u1", "Ahmed_Fan")
    await client.post(f"{API}/auth/sync", headers=auth("u2"))
    r = await client.post(
        f"{API}/users/me/onboarding",
        headers=auth("u2"),
        json={"nickname": "ahmed fan", "favorite_club": "ZAMALEK", "birth_date": "2001-05-05", "accept_terms_version": "2026-11"},
    )
    assert r.status_code == 409 and r.json()["detail"] == "nickname_taken"  # look-alike blocked
    r = await client.post(
        f"{API}/users/me/onboarding",
        headers=auth("u1"),
        json={"nickname": "Ahmed_Fan", "favorite_club": "ZAMALEK", "birth_date": "2000-01-01", "accept_terms_version": "2026-11"},
    )
    assert r.json()["detail"] == "club_locked"


async def test_full_round_with_sealed_questions_revive_and_leaderboard(client, clock, ssv):
    me = await onboard(client, "p1", "Salah_Fan")
    r = await client.post(f"{API}/game/start", headers=auth("p1"), json={"lang": "en"})
    assert r.status_code == 200, r.text
    start = r.json()
    sid = start["session_id"]
    assert "correct" not in r.text and "correct_option_index" not in r.text
    assert len(start["questions"]) == 10 and start["lives_remaining"] == 4

    # q0: decrypt with first key, answer correctly after 3s => 100 + 12*10
    q0 = sealing.unseal(start["first_key"], sid, 0, start["questions"][0])
    assert len(q0["o"]) == 4
    right, wrong = await _correct_and_wrong(sid, 0)
    clock.advance(3)
    r = (await client.post(f"{API}/game/{sid}/answer", headers=auth("p1"), json={"index": 0, "selected": right})).json()
    assert r["answer"]["correct"] and r["answer"]["points"] == 220 and r["next"]["index"] == 1
    # Without key 1, question 1 is unreadable; with it, readable.
    sealing.unseal(r["next"]["key"], sid, 1, start["questions"][1])

    # Retry of the same answer (lost response) is idempotent.
    again = (await client.post(f"{API}/game/{sid}/answer", headers=auth("p1"), json={"index": 0, "selected": wrong})).json()
    assert again["answer"]["correct"] and again["round_score"] == 220

    # q1 wrong -> AWAITING_REVIVE
    _, wrong1 = await _correct_and_wrong(sid, 1)
    clock.advance(4)
    r = (await client.post(f"{API}/game/{sid}/answer", headers=auth("p1"), json={"index": 1, "selected": wrong1})).json()
    assert r["status"] == "AWAITING_REVIVE" and r["revive_available"]

    # Resume without a verified ad -> 402
    intent = (await client.post(f"{API}/rewards/intents", headers=auth("p1"), json={"purpose": "REVIVE", "ref": sid})).json()
    r = await client.post(f"{API}/game/{sid}/resume", headers=auth("p1"), json={"intent_id": intent["intent_id"]})
    assert r.status_code == 402

    # Google SSV callback (signed) grants it; tampered callback is rejected.
    assert (await client.get(ssv(me["id"], intent["intent_id"], tamper=True))).status_code == 400
    assert (await client.get(ssv(me["id"], intent["intent_id"], tx="tx-1"))).status_code == 200
    clock.advance(20)  # time spent watching the ad does not count
    r = (await client.post(f"{API}/game/{sid}/resume", headers=auth("p1"), json={"intent_id": intent["intent_id"]})).json()
    assert r["status"] == "IN_PROGRESS" and r["next"]["index"] == 2

    # q2 correct after 14.5s -> 100 + 0*10 ... floor(15-14.5)=0
    right2, _ = await _correct_and_wrong(sid, 2)
    clock.advance(14.5)
    r = (await client.post(f"{API}/game/{sid}/answer", headers=auth("p1"), json={"index": 2, "selected": right2})).json()
    assert r["answer"]["points"] == 100

    # q3 answered too late (beyond 15s + 2s grace) => timed out, no second revive => round ends
    right3, _ = await _correct_and_wrong(sid, 3)
    clock.advance(18)
    r = (await client.post(f"{API}/game/{sid}/answer", headers=auth("p1"), json={"index": 3, "selected": right3})).json()
    assert r["answer"]["timed_out"] and r["status"] == "COMPLETED" and r["awarded_points"] == 320

    lb = (await client.get(f"{API}/leaderboard/weekly", headers=auth("p1"))).json()
    assert lb["global_top"][0]["nickname"] == "Salah_Fan" and lb["global_top"][0]["points"] == 320
    assert lb["me"]["rank"] == 1 and lb["me"]["club_rank"] == 1 and lb["season"]["seconds_remaining"] > 0


async def test_bot_timing_is_flagged_and_awards_nothing(client, clock):
    await onboard(client, "bot", "Robo_Kora")
    sid = (await client.post(f"{API}/game/start", headers=auth("bot"), json={})).json()["session_id"]
    for i in range(10):
        right, _ = await _correct_and_wrong(sid, i)
        clock.advance(0.2)
        r = (await client.post(f"{API}/game/{sid}/answer", headers=auth("bot"), json={"index": i, "selected": right})).json()
    assert r["status"] == "FLAGGED" and r["awarded_points"] == 0
    async with sessionmaker()() as db:
        u = await db.scalar(select(User).where(User.firebase_uid == "bot"))
        assert u.strikes == 1 and u.all_time_points == 0
        assert await db.scalar(select(func.count()).select_from(PointsLedger)) == 0


async def test_lives_exhaust_then_ad_life(client, clock, ssv):
    me = await onboard(client, "l1", "Lives_Guy")
    for _ in range(5):
        sid = (await client.post(f"{API}/game/start", headers=auth("l1"), json={})).json()["session_id"]
        await client.post(f"{API}/game/{sid}/finish", headers=auth("l1"))
    r = await client.post(f"{API}/game/start", headers=auth("l1"), json={})
    assert r.status_code == 402 and r.json()["detail"] == "no_lives"
    intent = (await client.post(f"{API}/rewards/intents", headers=auth("l1"), json={"purpose": "EXTRA_LIFE"})).json()
    # SSV with the wrong user_id is rejected (intent bound to its owner)
    await client.get(ssv(str(uuid.uuid4()), intent["intent_id"]))
    assert (await client.get(f"{API}/rewards/intents/{intent['intent_id']}", headers=auth("l1"))).json()["status"] == "REJECTED"
    intent = (await client.post(f"{API}/rewards/intents", headers=auth("l1"), json={"purpose": "EXTRA_LIFE"})).json()
    await client.get(ssv(me["id"], intent["intent_id"], tx="life-1"))
    await client.get(ssv(me["id"], intent["intent_id"], tx="life-1"))  # Google retry: no double grant
    assert (await client.get(f"{API}/users/me", headers=auth("l1"))).json()["lives"] == 1
    assert (await client.post(f"{API}/game/start", headers=auth("l1"), json={})).status_code == 200
    # Next Cairo day: lazy reset to 5
    clock.advance(86400)
    assert (await client.get(f"{API}/users/me", headers=auth("l1"))).json()["lives"] == 5


async def test_predictions_lock_double_and_settle(client, clock, ssv):
    me = await onboard(client, "f1", "Predictor")
    async with sessionmaker()() as db:
        soon = Fixture(
            home_team_en="Al Ahly",
            home_team_ar="الأهلي",
            away_team_en="Zamalek",
            away_team_ar="الزمالك",
            kickoff_time=clock.now + timedelta(minutes=10),
        )
        later = Fixture(
            home_team_en="Pyramids",
            home_team_ar="بيراميدز",
            away_team_en="Al Masry",
            away_team_ar="المصري",
            kickoff_time=clock.now + timedelta(hours=3),
        )
        db.add_all([soon, later])
        await db.commit()
        soon_id, later_id = soon.id, later.id

    r = await client.post(f"{API}/predictions", headers=auth("f1"), json={"fixture_id": soon_id, "outcome": "HOME"})
    assert r.status_code == 423
    r = await client.post(
        f"{API}/predictions", headers=auth("f1"), json={"fixture_id": later_id, "outcome": "AWAY", "home_goals": 2, "away_goals": 1}
    )
    assert r.status_code == 422  # score contradicts outcome
    r = await client.post(
        f"{API}/predictions", headers=auth("f1"), json={"fixture_id": later_id, "outcome": "HOME", "home_goals": 2, "away_goals": 1}
    )
    assert r.status_code == 200 and r.json()["my_prediction"]["outcome"] == "HOME"

    intent = (
        await client.post(f"{API}/rewards/intents", headers=auth("f1"), json={"purpose": "DOUBLE_PREDICTION", "ref": str(later_id)})
    ).json()
    await client.get(ssv(me["id"], intent["intent_id"]))

    clock.advance(3 * 3600 - 14 * 60)  # inside the 15-minute lock window
    assert (
        await client.post(f"{API}/predictions", headers=auth("f1"), json={"fixture_id": later_id, "outcome": "DRAW"})
    ).status_code == 423

    assert (
        await client.post(
            f"{API}/admin/fixtures/{later_id}/result", headers=auth("f1"), json={"status": "FINISHED", "home_goals": 2, "away_goals": 1}
        )
    ).status_code == 403
    r = await client.post(
        f"{API}/admin/fixtures/{later_id}/result",
        headers=auth("adm", "admin"),
        json={"status": "FINISHED", "home_goals": 2, "away_goals": 1},
    )
    assert r.status_code == 200 and r.json()["settled"] == 1
    async with sessionmaker()() as db:
        p = await db.scalar(select(Prediction).where(Prediction.fixture_id == later_id))
        assert p.is_double_points and p.points_earned == (300 + 200) * 2
    me2 = (await client.get(f"{API}/users/me", headers=auth("f1"))).json()
    assert me2["season_points"] == 1000 and me2["season_rank"] == 1
    # Settling twice is a no-op
    r = await client.post(
        f"{API}/admin/fixtures/{later_id}/result",
        headers=auth("adm", "admin"),
        json={"status": "FINISHED", "home_goals": 2, "away_goals": 1},
    )
    assert r.status_code == 409


async def test_account_deletion_is_total(client, clock):
    await onboard(client, "d1", "Delete_Me")
    sid = (await client.post(f"{API}/game/start", headers=auth("d1"), json={})).json()["session_id"]
    right, _ = await _correct_and_wrong(sid, 0)
    clock.advance(9)
    await client.post(f"{API}/game/{sid}/answer", headers=auth("d1"), json={"index": 0, "selected": right})
    await client.post(f"{API}/game/{sid}/finish", headers=auth("d1"))
    assert (await client.delete(f"{API}/users/me", headers=auth("d1"))).status_code == 204
    async with sessionmaker()() as db:
        for model in (User, GameSession, PointsLedger):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
    lb = await client.get(f"{API}/leaderboard/weekly", headers=auth("d1"))
    assert lb.status_code == 409  # user no longer exists
    page = await client.get("/account-deletion")
    assert page.status_code == 200 and "Delete your" in page.text


async def test_ssv_console_ping_without_custom_data_is_200(client, ssv):
    url = ssv("", "")
    assert (await client.get(url)).status_code == 200


async def test_dev_ssv_simulator_only_in_dev(client):
    me = await onboard(client, "dv", "Dev_Tester")
    intent = (await client.post(f"{API}/rewards/intents", headers=auth("dv"), json={"purpose": "EXTRA_LIFE"})).json()
    r = await client.post(f"{API}/dev/ssv-simulate", headers=auth("dv"), json={"intent_id": intent["intent_id"]})
    assert r.json()["outcome"] == "life_added" and me["lives"] == 5
    import pytest

    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(env="production", auth_mode="dev")
