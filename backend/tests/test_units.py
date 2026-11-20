from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cryptography.exceptions import InvalidTag

from app.services import sealing
from app.services.points import points_from_zscore, zscore
from app.services.seasons import season_bounds
from app.services.text import NicknameError, skeleton, validate_nickname


def test_skeleton_collapses_lookalikes():
    assert skeleton("Ahly_Fan") == skeleton("AHLY FAN") == skeleton("4hly-f4n")
    assert skeleton("أحمد") == skeleton("احمد") == skeleton("أَحْمَد") == skeleton("احـــمد")
    assert skeleton("كورة") == skeleton("كوره")


@pytest.mark.parametrize("bad", ["admin", "Adm1n", "f u c k", "sh1t_head", "x", "a" * 21, "<script>", "ahly\u202eadmin"])
def test_nickname_rejections(bad):
    with pytest.raises(NicknameError):
        validate_nickname(bad)


def test_nickname_accepts_arabic_english_digits():
    assert validate_nickname("  صقر الأهلي ٧ ")[0] == "صقر الأهلي ٧"
    assert validate_nickname("Zamalkawy_99")[0] == "Zamalkawy_99"
    assert validate_nickname("Bo\u200bb\u202e")[0] == "Bob"  # bidi/zero-width spoofing stripped


def test_season_boundaries_cairo_friday_2359_with_dst():
    # Friday 23:59 Cairo (summer, UTC+3) still belongs to the week that started the previous Saturday.
    fri = datetime(2026, 7, 10, 20, 59, tzinfo=UTC)  # 23:59 EEST
    sat = datetime(2026, 7, 10, 21, 0, tzinfo=UTC)  # 00:00 Saturday EEST
    s1, e1 = season_bounds(fri)
    s2, _ = season_bounds(sat)
    assert e1 == s2 == sat and s1 < fri < e1
    # Winter (UTC+2)
    s3, e3 = season_bounds(datetime(2026, 11, 20, 21, 59, tzinfo=UTC))  # Fri 23:59 EET
    assert e3 == datetime(2026, 11, 20, 22, 0, tzinfo=UTC)
    assert (e3 - s3).days == 7


def test_sealing_roundtrip_and_binding():
    k = sealing.new_key()
    box = sealing.seal(k, "sid", 3, {"q": "سؤال", "o": ["a", "b", "c", "d"]})
    assert sealing.unseal(k, "sid", 3, box)["q"] == "سؤال"
    with pytest.raises(InvalidTag):
        sealing.unseal(k, "sid", 4, box)  # ciphertext is bound to its slot
    with pytest.raises(InvalidTag):
        sealing.unseal(sealing.new_key(), "sid", 3, box)


def test_zscore_tiebreak_earlier_wins():
    start = datetime(2026, 11, 14, tzinfo=UTC)
    early = zscore(500, datetime(2026, 11, 15, tzinfo=UTC), start)
    late = zscore(500, datetime(2026, 11, 16, tzinfo=UTC), start)
    more = zscore(501, datetime(2026, 11, 20, tzinfo=UTC), start)
    assert more > early > late
    assert points_from_zscore(early) == 500


def test_sealing_cross_language_vector():
    """Same vector as mobile/test/sealed_contract_test.dart: locks the wire format on both sides."""
    box = {
        "nonce": "T+LLG43zAwJmWI25",
        "ciphertext": "01z4mDnxG7rs+iVt3odw2swjSNJVYMD6EKfINJzRA2L/9IAQOvQalsy8hikvIHURCXI8pCpg2UX+KP7jDWO1KArfnmNnYr+j8z6RV4qglg4vqHwM86GtJmzjgb4dG+0VooZcvygbMg==",  # noqa: E501
    }
    q = sealing.unseal("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=", "11111111-2222-3333-4444-555555555555", 3, box)
    assert q == {"q": "مين سجّل؟", "o": ["أ", "ب", "ج", "د"], "c": "national_team", "d": 2}
