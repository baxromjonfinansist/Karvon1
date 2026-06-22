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

from bot.services.parser_service import parse_with_regex  # noqa: E402


def test_full_load_high_confidence():
    r = parse_with_regex(
        "Toshkent-Samarqand, 5 tonna, qurilish materiallari, 600ming, +998901234567"
    )
    assert r.origin == "Toshkent"
    assert r.destination == "Samarqand"
    assert r.weight_t == 5.0
    assert r.price == 600_000
    assert r.contact == "+998901234567"
    assert r.cargo_type == "Qurilish materiallari"
    assert r.confidence >= 0.7


def test_arrow_separator():
    r = parse_with_regex("Toshkent → Buxoro. Oziq-ovqat 3 t. Narx 500 000 som.")
    assert r.origin == "Toshkent"
    assert r.destination == "Buxoro"
    assert r.weight_t == 3.0
    assert r.price == 500_000
    assert r.cargo_type == "Oziq-ovqat"


def test_mln_price():
    r = parse_with_regex("Namangan Andijon 10tonna elektronika 1.5mln")
    assert r.origin == "Namangan"
    assert r.destination == "Andijon"
    assert r.weight_t == 10.0
    assert r.price == 1_500_000
    assert r.cargo_type == "Elektronika"


def test_phone_not_parsed_as_price():
    # "kelishamiz" => narx yo'q; telefon raqami narx bo'lib qolmasligi kerak
    r = parse_with_regex(
        "Fura kerak Toshkentdan Qarshiga, sement 20t, kelishamiz, tel 998901112233"
    )
    assert r.price is None
    assert r.contact == "998901112233"
    assert r.weight_t == 20.0
    assert r.cargo_type == "Qurilish materiallari"


def test_ming_multiplier():
    r = parse_with_regex("Jizzax-Navoiy paxta 8t 700ming")
    assert r.price == 700_000
    assert r.cargo_type == "Paxta"


def test_decimal_weight_comma():
    r = parse_with_regex("Buxoro-Termiz mebel 1,5 tonna 300ming")
    assert r.weight_t == 1.5
    assert r.cargo_type == "Mebel"


def test_phone_with_plus():
    r = parse_with_regex("Toshkent Nukus don 15t +998935554433")
    assert r.contact == "+998935554433"
    assert r.cargo_type == "Oziq-ovqat"


def test_no_city_low_confidence():
    r = parse_with_regex("Yuk bor, narxi kelishiladi")
    assert r.origin is None
    assert r.destination is None
    assert r.confidence < 0.7


def test_single_city_only():
    r = parse_with_regex("Samarqanddan yuk bor 5t")
    assert r.origin == "Samarqand"
    assert r.destination is None


def test_cargo_keyword_muzlatilgan():
    r = parse_with_regex("Andijon-Toshkent muzlatilgan gosht 12 tonna 2mln")
    assert r.cargo_type == "Muzlatilgan mahsulot"
    assert r.weight_t == 12.0
    assert r.price == 2_000_000


def test_cargo_stopwords_filtered():
    # Noma'lum yuk turi — stopword'lar ("narx", "tel") chiqib ketishi kerak
    r = parse_with_regex("Toshkent-Samarqand pianino 2t narx 400ming tel +998901234567")
    assert r.cargo_type is not None
    assert "narx" not in r.cargo_type.lower()
    assert "tel" not in r.cargo_type.lower()
    assert "pianino" in r.cargo_type.lower()


def test_weight_kg_not_matched_as_weight():
    # "t" yoki "tonna" bo'lmasa vazn topilmaydi (faqat tonna qo'llab-quvvatlanadi)
    r = parse_with_regex("Toshkent-Buxoro qurilish 600ming +998901234567")
    assert r.weight_t is None
    assert r.price == 600_000


def test_confidence_range():
    r = parse_with_regex("Toshkent-Samarqand 5t qurilish 600ming +998901234567")
    assert 0.0 <= r.confidence <= 1.0


def test_empty_text():
    r = parse_with_regex("")
    assert r.origin is None
    assert r.destination is None
    assert r.weight_t is None
    assert r.price is None
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
