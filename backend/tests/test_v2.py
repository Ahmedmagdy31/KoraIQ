"""v2: topics, progression (XP/levels/streaks/mastery/badges), coins & shop, 50/50, Daily Challenge,
question reports, digital weekly rewards."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update

from app import worker
from app.db import sessionmaker
from app.models import GameSession, Question, Topic, User, UserBadge, UserCosmetic
from app.services import economy, progression
from tests.conftest import auth, onboard
from tests.test_flows import _correct_and_wrong

API = "/api/v1"


async def _uid(firebase_uid: str) -> uuid.UUID:
    async with sessionmaker()() as db:
        return await db.scalar(select(User.id).where(User.firebase_uid == firebase_uid))


async def _give_coins(firebase_uid: str, n: int) -> None:
    async with sessionmaker()() as db:
        await economy.credit(db, await _uid(firebase_uid), n, "TEST", uuid.uuid4().hex)
        await db.commit()


async def _play_round(client, clock, who: str, *, topic: str = "mixed", correct_upto: int = 10, secs: float = 2.0) -> dict:
    """Answer the first `correct_upto` questions correctly, then one wrong (ends a SOLO round), then finish."""
    sid = (await client.post(f"{API}/game/start", headers=auth(who), json={"topic": topic})).json()["session_id"]
    r = {}
    for i in range(10):
        right, wrong = await _correct_and_wrong(sid, i)
        clock.advance(secs)
        r = (
            await client.post(
                f"{API}/game/{sid}/answer", headers=auth(who), json={"index": i, "selected": right if i < correct_upto else wrong}
            )
        ).json()
        if r["status"] != "IN_PROGRESS":
            break
    if r["status"] == "AWAITING_REVIVE":
        r = (await client.post(f"{API}/game/{sid}/finish", headers=auth(who))).json()
    return r | {"session_id": sid}


# ---------------------------------------------------------------- topics
async def test_topics_visibility_and_topic_rounds(client, clock):
    await onboard(client, "t1", "Topic_Fan")
    body = (await client.get(f"{API}/topics?lang=en", headers=auth("t1"))).json()
    assert [t["slug"] for t in body["topics"]] == ["football", "tourism", "kitchen", "dialects"]
    assert body["topics"][1]["name"] == "Tourism & Places" and body["topics"][0]["mastery"]["tier"] is None

    # A topic below the question threshold disappears by itself (e.g. waiting for reviewers).
    async with sessionmaker()() as db:
        kid = await db.scalar(select(Topic.id).where(Topic.slug == "kitchen"))
        await db.execute(update(Question).where(Question.topic_id == kid).values(is_active=False))
        await db.commit()
    body = (await client.get(f"{API}/topics", headers=auth("t1"))).json()
    assert "kitchen" not in [t["slug"] for t in body["topics"]]
    assert (await client.post(f"{API}/game/start", headers=auth("t1"), json={"topic": "kitchen"})).status_code == 404

    r = await _play_round(client, clock, "t1", topic="tourism", correct_upto=3)
    async with sessionmaker()() as db:
        gs = await db.get(GameSession, uuid.UUID(r["session_id"]))
        tid = await db.scalar(select(Topic.id).where(Topic.slug == "tourism"))
        assert set(gs.question_topics) == {tid}
    lb_topic = (await client.get(f"{API}/leaderboard/weekly?scope=tourism", headers=auth("t1"))).json()
    lb_all = (await client.get(f"{API}/leaderboard/weekly?scope=all", headers=auth("t1"))).json()
    assert lb_topic["global_top"][0]["points"] == lb_all["global_top"][0]["points"] == r["awarded_points"] > 0
    assert (await client.get(f"{API}/leaderboard/weekly?scope=football", headers=auth("t1"))).json()["global_top"] == []
    assert "tourism" in lb_all["scopes"]


async def test_mixed_round_splits_points_across_topic_boards(client, clock):
    await onboard(client, "mx", "Mixed_Player")
    r = await _play_round(client, clock, "mx", topic="mixed", correct_upto=10)
    total = r["awarded_points"]
    per_topic = 0
    for slug in ("football", "tourism", "kitchen", "dialects"):
        top = (await client.get(f"{API}/leaderboard/weekly?scope={slug}", headers=auth("mx"))).json()["global_top"]
        per_topic += top[0]["points"] if top else 0
    assert per_topic == total


# ---------------------------------------------------------------- progression
def test_level_curve():
    assert progression.xp_to_reach(1) == 0 and progression.xp_to_reach(2) == 100 and progression.xp_to_reach(10) == 2700
    assert progression.level_for_xp(99) == 1 and progression.level_for_xp(100) == 2 and progression.level_for_xp(2700) == 10


async def test_perfect_round_rewards_xp_coins_badges_and_streak(client, clock):
    await onboard(client, "pf", "Perfect_One")
    r = await _play_round(client, clock, "pf", correct_upto=10, secs=2.0)
    assert r["status"] == "COMPLETED" and r["correct_count"] == 10
    rw = r["rewards"]
    assert r["round_score"] == 10 * (100 + 13 * 10)  # floor(15 - 2) = 13
    assert rw["xp"] == r["round_score"] // 10 + 20 and rw["level_after"] == progression.level_for_xp(rw["xp"])
    codes = {b["code"] for b in rw["badges"]}
    assert codes == {"PERFECT_10", "LIGHTNING"}
    assert rw["coins"] == 10 + 10 + 50 + 50 and rw["streak"] == 1
    me = (await client.get(f"{API}/users/me", headers=auth("pf"))).json()
    assert me["coins"] == 120 and me["level"] == rw["level_after"] and me["streak_days"] == 1 and me["played_today"]
    prog = (await client.get(f"{API}/me/progress?lang=en", headers=auth("pf"))).json()
    assert sum(m["correct"] for m in prog["mastery"]) == 10
    assert {b["code"] for b in prog["badges"] if b["earned"]} == {"PERFECT_10", "LIGHTNING"}


async def test_zero_correct_round_earns_nothing(client, clock):
    await onboard(client, "zz", "Zero_Hero")
    r = await _play_round(client, clock, "zz", correct_upto=0)
    assert r["rewards"]["xp"] == 0 and r["rewards"]["coins"] == 0
    assert (await client.get(f"{API}/users/me", headers=auth("zz"))).json()["streak_days"] == 0


async def test_streak_continues_with_freeze_and_resets_without(client, clock):
    await onboard(client, "st", "Streaker")
    await _play_round(client, clock, "st", correct_upto=1)
    clock.advance(86400)
    assert (await _play_round(client, clock, "st", correct_upto=1))["rewards"]["streak"] == 2
    await _give_coins("st", 150)
    assert (await client.post(f"{API}/shop/buy", headers=auth("st"), json={"item": "STREAK_FREEZE"})).json()["streak_freezes"] == 1
    clock.advance(2 * 86400)  # missed one day -> the freeze covers it
    rw = (await _play_round(client, clock, "st", correct_upto=1))["rewards"]
    assert rw["streak"] == 3 and rw["freezes_used"] == 1 and rw["coins"] == 10 + 20  # 3-day milestone
    clock.advance(3 * 86400)  # missed two days, no freezes left
    assert (await client.get(f"{API}/users/me", headers=auth("st"))).json()["streak_days"] == 0
    assert (await _play_round(client, clock, "st", correct_upto=1))["rewards"]["streak"] == 1


# ---------------------------------------------------------------- shop, 50/50, coin ads
async def test_shop_cosmetics_and_lives(client, clock):
    await onboard(client, "sh", "Shopper")
    assert (await client.post(f"{API}/shop/buy", headers=auth("sh"), json={"item": "FRAME_GOLD"})).json()["detail"] == "insufficient_coins"
    await _give_coins("sh", 1000)
    assert (await client.post(f"{API}/shop/buy", headers=auth("sh"), json={"item": "FRAME_GOLD"})).json()["coins"] == 700
    assert (await client.post(f"{API}/shop/buy", headers=auth("sh"), json={"item": "FRAME_GOLD"})).status_code == 409
    assert (await client.post(f"{API}/shop/buy", headers=auth("sh"), json={"item": "FRAME_CHAMPION"})).status_code == 404  # exclusive
    r = await client.post(f"{API}/me/equip", headers=auth("sh"), json={"kind": "FRAME", "code": "FRAME_GOLD"})
    assert r.json()["frame"] == "FRAME_GOLD"
    eq = (await client.get(f"{API}/users/me", headers=auth("sh"))).json()["equipped"]
    assert eq["frame"]["asset"]["colors"] == ["#F4B400", "#B8860B"] and eq["theme"] is None
    assert (await client.post(f"{API}/me/equip", headers=auth("sh"), json={"kind": "FRAME", "code": "FRAME_NILE"})).status_code == 409
    shop = (await client.get(f"{API}/shop?lang=en", headers=auth("sh"))).json()
    gold = next(c for c in shop["cosmetics"] if c["code"] == "FRAME_GOLD")
    assert gold["owned"] and gold["equipped"] and not any(c["code"] == "FRAME_CHAMPION" for c in shop["cosmetics"])
    # Extra lives: +1 each, capped per day
    for _ in range(5):
        assert (await client.post(f"{API}/shop/buy", headers=auth("sh"), json={"item": "EXTRA_LIFE"})).status_code == 200
    assert (await client.post(f"{API}/shop/buy", headers=auth("sh"), json={"item": "EXTRA_LIFE"})).status_code == 429
    assert (await client.get(f"{API}/users/me", headers=auth("sh"))).json()["lives"] == 10


async def test_fifty_fifty_costs_coins_and_unranks_the_round(client, clock):
    await onboard(client, "ff", "Fifty_Fan")
    sid = (await client.post(f"{API}/game/start", headers=auth("ff"), json={})).json()["session_id"]
    assert (await client.post(f"{API}/game/{sid}/fifty", headers=auth("ff"), json={"index": 0})).status_code == 402
    await _give_coins("ff", 100)
    r = (await client.post(f"{API}/game/{sid}/fifty", headers=auth("ff"), json={"index": 0})).json()
    right, _ = await _correct_and_wrong(sid, 0)
    assert len(r["remove"]) == 2 and right not in r["remove"] and r["coins"] == 60 and r["ranked"] is False
    assert (await client.post(f"{API}/game/{sid}/fifty", headers=auth("ff"), json={"index": 0})).json()["detail"] == "fifty_already_used"
    clock.advance(3)
    await client.post(f"{API}/game/{sid}/answer", headers=auth("ff"), json={"index": 0, "selected": right})
    done = (await client.post(f"{API}/game/{sid}/finish", headers=auth("ff"))).json()
    assert done["awarded_points"] == 0 and done["rewards"]["xp"] > 0  # progress yes, leaderboard no
    assert (await client.get(f"{API}/leaderboard/weekly", headers=auth("ff"))).json()["global_top"] == []


async def test_coin_bonus_ad_is_capped(client, ssv):
    me = await onboard(client, "cb", "Coin_Bonus")
    for i in range(3):
        intent = (await client.post(f"{API}/rewards/intents", headers=auth("cb"), json={"purpose": "COIN_BONUS"})).json()
        await client.get(ssv(me["id"], intent["intent_id"], tx=f"cb-{i}"))
    assert (await client.get(f"{API}/users/me", headers=auth("cb"))).json()["coins"] == 75
    assert (await client.post(f"{API}/rewards/intents", headers=auth("cb"), json={"purpose": "COIN_BONUS"})).status_code == 429


# ---------------------------------------------------------------- Daily Challenge
async def test_daily_challenge_once_per_day_free_and_full_length(client, clock):
    await onboard(client, "dc", "Daily_Doer")
    await onboard(client, "dc2", "Daily_Two")
    status0 = (await client.get(f"{API}/daily?lang=en", headers=auth("dc"))).json()
    assert status0["questions"] == 5 and not status0["played"] and status0["topic"]["slug"]
    s1 = (await client.post(f"{API}/daily/start", headers=auth("dc"), json={})).json()
    s2 = (await client.post(f"{API}/daily/start", headers=auth("dc2"), json={})).json()
    async with sessionmaker()() as db:
        q1 = (await db.get(GameSession, uuid.UUID(s1["session_id"]))).question_ids
        q2 = (await db.get(GameSession, uuid.UUID(s2["session_id"]))).question_ids
    assert q1 == q2 and len(q1) == 5 and s1["daily_number"] == status0["number"] and s1["fifty_price"] is None
    sid = s1["session_id"]
    for i in range(5):  # wrong answers do NOT end a daily
        right, wrong = await _correct_and_wrong(sid, i)
        clock.advance(4)
        r = (
            await client.post(f"{API}/game/{sid}/answer", headers=auth("dc"), json={"index": i, "selected": right if i != 1 else wrong})
        ).json()
    assert r["status"] == "COMPLETED" and r["correct_count"] == 4 and r["rewards"]["coins"] >= 15
    assert "DAILY_FIRST" in {b["code"] for b in r["rewards"]["badges"]}
    assert (await client.post(f"{API}/daily/start", headers=auth("dc"), json={})).json()["detail"] == "daily_already_played"
    st = (await client.get(f"{API}/daily", headers=auth("dc"))).json()
    assert st["played"] and st["result"]["grid"] == [True, False, True, True, True]
    assert (await client.get(f"{API}/users/me", headers=auth("dc"))).json()["lives"] == 5  # free
    assert (await client.post(f"{API}/game/{sid}/fifty", headers=auth("dc"), json={"index": 0})).status_code == 409
    clock.advance(86400)
    assert (await client.get(f"{API}/daily", headers=auth("dc"))).json()["number"] == status0["number"] + 1


# ---------------------------------------------------------------- reports & weekly rewards
async def test_three_distinct_reports_deactivate_a_question(client):
    sids = {}
    for who in ("r1", "r2", "r3"):
        await onboard(client, who, f"Reporter_{who}")
        sids[who] = (await client.post(f"{API}/daily/start", headers=auth(who), json={})).json()["session_id"]
    for who in ("r1", "r1", "r2", "r3"):  # r1 twice counts once
        r = await client.post(f"{API}/questions/report", headers=auth(who), json={"session_id": sids[who], "index": 0})
        assert r.status_code == 202
    async with sessionmaker()() as db:
        qid = (await db.get(GameSession, uuid.UUID(sids["r1"]))).question_ids[0]
        q = await db.get(Question, qid)
        assert q.reports == 3 and q.is_active is False


async def test_weekly_finalize_gives_digital_rewards(client, clock):
    await onboard(client, "w1", "Champ_One")
    await onboard(client, "w2", "Champ_Two")
    await _play_round(client, clock, "w1", topic="kitchen", correct_upto=5)
    await _play_round(client, clock, "w2", topic="tourism", correct_upto=2)
    coins_before = (await client.get(f"{API}/users/me", headers=auth("w1"))).json()["coins"]
    clock.advance(8 * 86400)
    await worker.finalize_seasons()
    async with sessionmaker()() as db:
        u1 = await _uid("w1")
        assert await db.scalar(select(UserCosmetic.cosmetic_code).where(UserCosmetic.user_id == u1)) == "FRAME_CHAMPION"
        badges = set(await db.scalars(select(UserBadge.badge_code).where(UserBadge.user_id == u1)))
        assert {"WEEKLY_PODIUM", "TOPIC_CHAMPION"} <= badges
        assert await db.scalar(select(func.count()).select_from(UserBadge).where(UserBadge.badge_code == "TOPIC_CHAMPION")) == 2
    assert (await client.get(f"{API}/users/me", headers=auth("w1"))).json()["coins"] == coins_before + 300 + 100
    shop = (await client.get(f"{API}/shop", headers=auth("w1"))).json()
    assert any(c["code"] == "FRAME_CHAMPION" and c["exclusive"] and c["owned"] for c in shop["cosmetics"])
