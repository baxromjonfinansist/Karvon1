"""Regex parser uchun unit testlar.

Ishga tushirish:
    python -m pytest tests/test_parser.py        # pytest bo'lsa
    python tests/test_parser.py                  # pytest'siz (standalone)
"""
from __future__ import annotations

import os
import sys

# Loyiha ildizini path'ga qo'shamiz
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# parse_with_regex Settings'ni import qiladi (db.models orqali) — .env bo'lmasa
# ham test ishlashi uchun majburiy env'larni oldindan o'rnatamiz.
os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from bot.services.parser_service import (  # noqa: E402
    extract_note,
    normalize_phone,
    parse_with_regex,
)


# ---------------------------------------------------------------------------
# Yo'nalish (route)
# ---------------------------------------------------------------------------

def test_route_dash_separator():
    r = parse_with_regex(
        "Toshkent-Samarqand, 5 tonna, qurilish materiallari, +998901234567"
    )
    assert r.origin == "Toshkent"
    assert r.destination == "Samarqand"
    assert r.weight_t == 5.0


def test_route_arrow_separator():
    r = parse_with_regex("Toshkent → Buxoro. Oziq-ovqat 3 t.")
    assert r.origin == "Toshkent"
    assert r.destination == "Buxoro"
    assert r.weight_t == 3.0


def test_single_city_only():
    r = parse_with_regex("Samarqanddan yuk bor 5t")
    assert r.origin == "Samarqand"
    assert r.destination is None


def test_no_city_low_confidence():
    r = parse_with_regex("Yuk bor, kelishiladi")
    assert r.origin is None
    assert r.destination is None
    assert r.confidence < 0.7


# ---------------------------------------------------------------------------
# Telefon normalizatsiya — +998XXXXXXXXX (bo'shliqsiz)
# ---------------------------------------------------------------------------

def test_phone_with_plus():
    assert normalize_phone("+998935554433") == "+998935554433"


def test_phone_bare_998():
    assert normalize_phone("998901112233") == "+998901112233"


def test_phone_local_9_digits():
    assert normalize_phone("901234567") == "+998901234567"


def test_phone_spaced_input():
    assert normalize_phone("90 123 45 67") == "+998901234567"


def test_phone_invalid_returns_none():
    assert normalize_phone("12345") is None
    assert normalize_phone("") is None


def test_contact_extracted_and_normalized():
    r = parse_with_regex("Toshkent Nukus don 15t +998935554433")
    assert r.contact == "+998935554433"


# ---------------------------------------------------------------------------
# Izoh (note) — yuk turi/vazn/talab, narx va telefon chiqib ketadi
# ---------------------------------------------------------------------------

def test_note_has_cargo_and_weight():
    note = extract_note("Toshkent → Farg'ona, Un 16 tonna, tent kerak, +998901234567")
    assert note is not None
    assert "un" in note.lower()
    assert "16 tonna" in note.lower()
    assert "tent" in note.lower()


def test_note_excludes_phone_and_price():
    note = extract_note("Toshkent-Samarqand paxta 8t 700ming +998901234567")
    assert "998" not in note
    assert "700" not in note
    assert "paxta" in note.lower()


def test_note_empty_for_bare_route():
    # Faqat yo'nalish — izoh bo'sh bo'lishi mumkin
    note = extract_note("Toshkent → Buxoro")
    assert note is None or note == "" or "buxoro" not in (note or "").lower()


# ---------------------------------------------------------------------------
# Narx umuman parse qilinmaydi — ParsedLoad'da price maydoni yo'q
# ---------------------------------------------------------------------------

def test_no_price_field():
    r = parse_with_regex("Toshkent-Samarqand 5t qurilish 600ming +998901234567")
    assert not hasattr(r, "price")


def test_confidence_range():
    r = parse_with_regex("Toshkent-Samarqand 5t qurilish +998901234567")
    assert 0.0 <= r.confidence <= 1.0


def test_empty_text():
    r = parse_with_regex("")
    assert r.origin is None
    assert r.destination is None
    assert r.weight_t is None
    assert r.confidence == 0.0


# ---------------------------------------------------------------------------
# pytest'siz standalone runner
# ---------------------------------------------------------------------------

def _run_standalone() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✅ {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  💥 {test.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\nNatija: {passed} passed, {failed} failed (jami {len(tests)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
