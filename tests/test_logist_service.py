"""LORRY logist aniqlash (V1 route diversity) — sof funksiya testlari.

Ishga tushirish:
    python -m pytest tests/test_logist_service.py   # pytest bo'lsa
    python tests/test_logist_service.py             # pytest'siz (standalone)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# logist_service -> db.models -> db.database -> Settings. .env bo'lmasa ham
# import ishlashi uchun majburiy env'larni oldindan o'rnatamiz (ulanish bo'lmaydi).
os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from bot.services.logist_service import (  # noqa: E402
    Label,
    canonicalize_city,
    classify_routes,
    distinct_route_count,
    normalize_phone,
    parse_route,
)


# ---------------------------------------------------------------------------
# Spec §9 — rasmlardagi real ma'lumot
# ---------------------------------------------------------------------------

def test_single_route_many_listings_is_cargo():
    # Rasm 1 — +998 87 625 91 91: 4 e'lon, hammasi Andijon->Toshkent
    routes_9191 = [("Andijon", "Toshkent")] * 4
    assert distinct_route_count(routes_9191) == 1
    assert classify_routes(routes_9191) == Label.CARGO   # katta yuk beruvchi, logist emas


def test_one_origin_many_dests_is_logist():
    # Rasm 2/3 — bitta origin, 7 destination
    routes_mustafo = [
        ("Andijon", "Nukus"), ("Andijon", "Buxoro"), ("Andijon", "Denov"),
        ("Andijon", "Shahrisabz"), ("Andijon", "Navoiy"),
        ("Andijon", "Urganch"), ("Andijon", "Buka"),
    ]
    assert distinct_route_count(routes_mustafo) == 7
    assert classify_routes(routes_mustafo) == Label.LOGIST


def test_district_noise_guard():
    assert canonicalize_city("Andijon vest") == "Andijon"
    assert canonicalize_city("Andijon g'arb") == "Andijon"
    assert canonicalize_city("Toshkent shahri") == "Toshkent"


def test_parse_route_variants():
    assert parse_route("Andijon ➡️ Toshkent") == ("Andijon", "Toshkent")
    assert parse_route("ANDIJON - NUKUS") == ("Andijon", "Nukus")
    assert parse_route("Andijon -> Samarqand") == ("Andijon", "Samarqand")


# ---------------------------------------------------------------------------
# Chegara (threshold) mantig'i
# ---------------------------------------------------------------------------

def test_thresholds():
    two = [("Andijon", "Toshkent"), ("Andijon", "Samarqand")]
    assert classify_routes(two) == Label.CARGO           # <=2 -> CARGO

    three = two + [("Andijon", "Buxoro")]
    assert classify_routes(three) == Label.SUSPICIOUS    # ==3 -> SUSPICIOUS

    four = three + [("Andijon", "Nukus")]
    assert classify_routes(four) == Label.LOGIST         # >=4 -> LOGIST


def test_directional():
    # A->B va B->A alohida yo'nalish (directional)
    routes = [("Toshkent", "Andijon"), ("Andijon", "Toshkent")]
    assert distinct_route_count(routes) == 2


def test_unknown_city_not_counted():
    # Noma'lum shahar -> None, sanoqqa kirmaydi (soxta pozitivni oldini oladi)
    routes = [
        ("Andijon", "Toshkent"),
        ("Andijon", None),                 # dest parse bo'lmagan
        (None, None),
        ("Andijon", canonicalize_city("Qwerty shahri")),  # None
    ]
    assert distinct_route_count(routes) == 1


def test_normalize_phone():
    assert normalize_phone("+998 87 625 91 91") == "+998876259191"
    assert normalize_phone("998876259191") == "+998876259191"
    assert normalize_phone("876259191") == "+998876259191"
    assert normalize_phone("тел: 90 123 45 67") == "+998901234567"
    assert normalize_phone("salom") is None
    assert normalize_phone(None) is None


def test_canonicalize_cyrillic_latin():
    assert canonicalize_city("ташкент") == "Toshkent"
    assert canonicalize_city("тошкент") == "Toshkent"
    assert canonicalize_city("tashkent") == "Toshkent"
    assert canonicalize_city("Qwerty") is None


# ---------------------------------------------------------------------------
# Standalone runner (pytest'siz)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {fn.__name__}: {e or 'assertion failed'}")
        except Exception as e:  # noqa: BLE001
            print(f"  💥 {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} test o'tdi.")
    sys.exit(0 if passed == len(fns) else 1)
