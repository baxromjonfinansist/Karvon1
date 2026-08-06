"""Menyu tugmalari callback_data'ga sig'maydigan shahar nomidan qulamasligi.

Bug (prod, 2026-08-06): provider "➕ Yuk joylash"da shahar nomini erkin matn
sifatida kiritadi (cheklovsiz). Uzun/nostandart qiymat `Route.origin`ga
tushib, keyin 📦 Yuklar va ro'yxatdan o'tishning "eng aktual yo'nalish"
menyusi tugmalarida `callback_data` (masalan `region_<origin>`) 64 baytdan
oshib ketardi — Telegram butun xabarni `BUTTON_DATA_INVALID` bilan rad
etardi va HAMMA foydalanuvchi uchun shu menyu ishlamay qolardi (jim qotish).

Ishga tushirish:
    python3 -m pytest tests/test_region_menu_safety.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from bot.handlers import provider as provider_handlers  # noqa: E402
from bot.services.load_service import (  # noqa: E402
    MAX_REGION_NAME_BYTES,
    _drop_callback_unsafe,
)
from bot.states import LoadPost  # noqa: E402


# ---------------------------------------------------------------------------
# _drop_callback_unsafe — sof funksiya
# ---------------------------------------------------------------------------

def test_qisqa_nomlar_saqlanadi():
    pairs = [("Toshkent", 5), ("Qoraqalpog'iston", 2)]
    assert _drop_callback_unsafe(pairs) == pairs


def test_uzun_nom_otkazib_yuboriladi():
    long_name = "Toshkent shahar Chilonzor tumani 15-uy yonidagi bozor"
    assert len(long_name.encode("utf-8")) > MAX_REGION_NAME_BYTES

    pairs = [("Toshkent", 5), (long_name, 1)]
    result = _drop_callback_unsafe(pairs)

    assert result == [("Toshkent", 5)]


def test_chegara_bayt_asosida_hisoblanadi():
    """MAX_REGION_NAME_BYTES aynan BAYT, belgi emas — ko'p baytli harflar
    (masalan lotin ’ apostrofi) bilan ham to'g'ri hisoblansin."""
    exactly_at_limit = "a" * MAX_REGION_NAME_BYTES
    one_over = "a" * (MAX_REGION_NAME_BYTES + 1)

    result = _drop_callback_unsafe([(exactly_at_limit, 1), (one_over, 1)])

    assert result == [(exactly_at_limit, 1)]


def test_bosh_nom_otkazib_yuboriladi():
    assert _drop_callback_unsafe([("", 3)]) == []


# ---------------------------------------------------------------------------
# provider.py — kirishda uzun shahar nomi rad etiladi
# ---------------------------------------------------------------------------

class FakeMessage:
    def __init__(self, text: str = "", user_id: int = 1):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id, full_name="Test User")
        self.answers: list[tuple[str, object]] = []

    async def answer(self, text, reply_markup=None, **kw):
        self.answers.append((text, reply_markup))
        return self


class FakeState:
    def __init__(self, state=None, data: dict | None = None):
        self.state = state
        self.data = dict(data or {})

    async def set_state(self, state):
        self.state = state

    async def update_data(self, **kw):
        self.data.update(kw)
        return dict(self.data)

    async def get_data(self):
        return dict(self.data)


def test_uzun_jonash_shahri_rad_etiladi():
    long_text = "Toshkent shahar Chilonzor tumani 15-uy yonidagi katta bozor"
    msg = FakeMessage(long_text)
    state = FakeState(LoadPost.waiting_origin)

    asyncio.run(provider_handlers.load_origin(msg, state))

    assert state.state == LoadPost.waiting_origin  # oldinga o'tmadi
    assert "origin" not in state.data
    assert "uzun" in msg.answers[-1][0].lower()


def test_qisqa_jonash_shahri_qabul_qilinadi():
    msg = FakeMessage("Toshkent")
    state = FakeState(LoadPost.waiting_origin)

    asyncio.run(provider_handlers.load_origin(msg, state))

    assert state.state == LoadPost.waiting_destination
    assert state.data["origin"] == "Toshkent"


def test_uzun_borish_shahri_rad_etiladi():
    long_text = "Samarqand shahar Registon ko'chasi 42-uy yonidagi ombor"
    msg = FakeMessage(long_text)
    state = FakeState(LoadPost.waiting_destination, {"origin": "Toshkent"})

    asyncio.run(provider_handlers.load_destination(msg, state))

    assert state.state == LoadPost.waiting_destination  # oldinga o'tmadi
    assert "destination" not in state.data
    assert "uzun" in msg.answers[-1][0].lower()
