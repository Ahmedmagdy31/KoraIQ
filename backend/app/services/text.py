"""Nickname validation for a bilingual (Arabic / English / Franco-Arabic) audience.

* `skeleton()` folds Arabic letter variants, diacritics, tatweel, zero-width chars, case and
  common digit substitutions so that "Ahly_Fan", "AHLY FAN" and "4hly-f4n" collide, and
  "أحمد" / "احمد" / "أَحْمَد" collide. The skeleton is stored in a UNIQUE column.
* `is_blocked()` checks the skeleton under BOTH digit interpretations: Latin leet (3->e, 4->a)
  and Franco-Arabic (3->ع, 7->ح, 2->ء), because Egyptian users type both.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

NICK_MIN, NICK_MAX = 3, 20
_ALLOWED = re.compile(r"^[ء-غف-ي٠-٩A-Za-z0-9_ ]+$")
_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_INVISIBLE = re.compile(r"[​-‏‪-‮⁦-⁩﻿ـ]")  # incl. tatweel
_ARABIC_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه"})
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "@": "a", "$": "s"})
_FRANCO = str.maketrans({"2": "ء", "3": "ع", "5": "خ", "7": "ح", "8": "غ", "9": "ق"})
_SEP = re.compile(r"[\s_\-.]+")

# Impersonation guard (substring match on the skeleton).
RESERVED = ("admin", "koraiq", "support", "official", "moderator", "system", "الاداره", "الدعم", "رسمي", "مشرف")


def clean_display(nick: str) -> str:
    """What we store/display: NFKC, invisible chars stripped, whitespace collapsed."""
    nick = unicodedata.normalize("NFKC", nick)
    nick = _INVISIBLE.sub("", nick)
    nick = _TASHKEEL.sub("", nick)
    return re.sub(r"\s+", " ", nick).strip()


def skeleton(nick: str) -> str:
    s = clean_display(nick).casefold().translate(_ARABIC_FOLD).translate(_ARABIC_DIGITS)
    s = _SEP.sub("", s)
    return s.translate(_LEET)


def _variants(nick: str) -> set[str]:
    base = _SEP.sub("", clean_display(nick).casefold().translate(_ARABIC_FOLD).translate(_ARABIC_DIGITS))
    return {base, base.translate(_LEET), base.translate(_FRANCO)}


@lru_cache
def _blocklist() -> tuple[str, ...]:
    path = Path(__file__).resolve().parent.parent / "data" / "blocked_terms.txt"
    terms: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                terms |= _variants(line)
    return tuple(sorted(t for t in terms if len(t) >= 3))


def is_blocked(nick: str) -> bool:
    variants = _variants(nick)
    if any(r in v for v in variants for r in RESERVED):
        return True
    return any(term in v for v in variants for term in _blocklist())


class NicknameError(ValueError):
    pass


def validate_nickname(raw: str) -> tuple[str, str]:
    """Returns (display_nickname, skeleton_key) or raises NicknameError(code)."""
    nick = clean_display(raw)
    if not (NICK_MIN <= len(nick) <= NICK_MAX):
        raise NicknameError("nickname_length")
    if not _ALLOWED.match(nick):
        raise NicknameError("nickname_charset")
    if is_blocked(nick):
        raise NicknameError("nickname_blocked")
    key = skeleton(nick)
    if len(key) < NICK_MIN:
        raise NicknameError("nickname_length")
    return nick, key
