"""Yuk kartasi — yosh (`humanize_age`) va umumiy formatlovchi testlari.

Ishga tushirish:
    python3 -m pytest tests/test_load_card.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from bot.services.load_service import (  # noqa: E402
    FRESH_MINUTES,
    format_load_card,
    humanize_age,
)

# Bazadagi vaqtlar naive UTC (datetime.utcnow) — testda ham shunday.
NOW = datetime(2026, 8, 3, 12, 0, 0)


def _ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


# ---------------------------------------------------------------------------
# humanize_age — chegaralar
# ---------------------------------------------------------------------------

def test_hozir_5_daqiqagacha():
    assert humanize_age(NOW, NOW) == "hozir"
    assert humanize_age(_ago(seconds=30), NOW) == "hozir"
    assert humanize_age(_ago(minutes=4, seconds=59), NOW) == "hozir"


def test_daqiqa_chegarasi():
    assert humanize_age(_ago(minutes=5), NOW) == "5 daqiqa oldin"
    assert humanize_age(_ago(minutes=25), NOW) == "25 daqiqa oldin"
    assert humanize_age(_ago(minutes=59, seconds=59), NOW) == "59 daqiqa oldin"


def test_soat_chegarasi():
    assert humanize_age(_ago(minutes=60), NOW) == "1 soat oldin"
    assert humanize_age(_ago(hours=2, minutes=30), NOW) == "2 soat oldin"
    assert humanize_age(_ago(hours=23, minutes=59), NOW) == "23 soat oldin"


def test_kun_chegarasi():
    assert humanize_age(_ago(hours=24), NOW) == "1 kun oldin"
    assert humanize_age(_ago(days=3, hours=5), NOW) == "3 kun oldin"


def test_kelajak_vaqt_hozir_boladi():
    # Soat farqi tufayli posted_at "kelajakda" bo'lsa — manfiy yosh chiqmasin
    assert humanize_age(NOW + timedelta(minutes=10), NOW) == "hozir"


def test_none_bosh_qator_qaytaradi():
    assert humanize_age(None, NOW) == ""


def test_tz_aware_vaqt_utc_deb_qabul_qilinadi():
    aware = (NOW - timedelta(hours=2)).replace(tzinfo=timezone.utc)
    assert humanize_age(aware, NOW) == "2 soat oldin"


def test_now_berilmasa_utcnow_ishlatiladi():
    assert humanize_age(datetime.utcnow() - timedelta(minutes=30)) == "30 daqiqa oldin"


# ---------------------------------------------------------------------------
# format_load_card — feed va xabarnoma uchun umumiy karta
# ---------------------------------------------------------------------------

def _load(**kw) -> SimpleNamespace:
    data = dict(
        id=1,
        route=SimpleNamespace(origin="Toshkent", destination="Samarqand"),
        contact_phone="+998901234567",
        raw_text="",
        note="Paxta 20 tonna",
        cargo_type=None,
        posted_at=_ago(minutes=25),
    )
    data.update(kw)
    return SimpleNamespace(**data)


def test_reveal_holatda_yonalish_telefon_va_yosh_bor():
    """show_phone=True ("reveal" rejimi) — telefon standart holatda endi
    matnda yo'q (Task 4), bu test faqat reveal holatini tekshiradi."""
    text = format_load_card(_load(), NOW, show_phone=True)
    assert "🚚 <b>Toshkent → Samarqand</b>" in text
    assert "📞 +998901234567" in text
    assert "🕒 25 daqiqa oldin" in text
    assert "📝 Paxta 20 tonna" in text


def test_posted_at_yoq_bolsa_yosh_qatori_yoq():
    assert "🕒" not in format_load_card(_load(posted_at=None), NOW)


def test_karta_html_escape_qiladi():
    text = format_load_card(_load(note="<b>xato</b>"), NOW)
    assert "&lt;b&gt;" in text


def test_reveal_holatda_yonalishsiz_ham_ishlaydi():
    """show_phone=True ("reveal" rejimi) — route/telefon yo'q holatda ham
    ikkalasi ham "—" bilan almashtirilishini tekshiradi."""
    text = format_load_card(_load(route=None, contact_phone=None), NOW, show_phone=True)
    assert "🚚 <b>—</b>" in text
    assert "📞 —" in text


# ---------------------------------------------------------------------------
# 1.1 — yuk oynasi 6 soat
# ---------------------------------------------------------------------------

def test_fresh_oyna_6_soat():
    assert FRESH_MINUTES == 360


# ---------------------------------------------------------------------------
# format_load_card — show_phone parametri va "1-qo'l" ishonch yorlig'i
# ---------------------------------------------------------------------------

def test_karta_standart_holatda_telefonni_yashiradi():
    load = _load(first_time_phone=True)
    text = format_load_card(load, NOW)
    assert "🚚 <b>Toshkent → Samarqand</b>" in text
    assert "📞" not in text
    assert load.contact_phone not in text


def test_karta_show_phone_true_bolganda_raqamni_korsatadi():
    load = _load(first_time_phone=True)
    text = format_load_card(load, NOW, show_phone=True)
    assert f"📞 {load.contact_phone}" in text


def test_karta_first_time_phone_true_bolsa_100_foiz_yorligi():
    text = format_load_card(_load(first_time_phone=True), NOW)
    assert "100% 1-qo'l" in text


def test_karta_first_time_phone_false_bolsa_dispetcher_yoq_yorligi():
    text = format_load_card(_load(first_time_phone=False), NOW)
    assert "dispetcher" in text.lower() or "logist" in text.lower()
    assert "100%" not in text
