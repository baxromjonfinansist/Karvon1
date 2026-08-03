"""Faza 2 — «⬅️ Orqaga» barcha ko'p qadamli oqimlarda.

Qoida: orqaga AYNAN bitta qadam qaytaradi (asosiy menyuga emas).

Ishga tushirish:
    python3 -m pytest tests/test_back_navigation.py
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

import pytest  # noqa: E402

from bot.handlers import driver as driver_handlers  # noqa: E402
from bot.handlers import provider as provider_handlers  # noqa: E402
from bot.handlers import settings as settings_handlers  # noqa: E402
from bot.handlers import start as start_handlers  # noqa: E402
from bot.keyboards import (  # noqa: E402
    BACK_TEXT,
    back_reply_kb,
    back_row,
    phone_request_kb,
)
from bot.states import DriverReg, LoadPost, ProviderReg, RatingFlow, RoleChange  # noqa: E402
from db.models import UserRole  # noqa: E402


# ---------------------------------------------------------------------------
# Soxta (fake) aiogram obyektlari — DB va tarmoqsiz
# ---------------------------------------------------------------------------

class FakeMessage:
    def __init__(self, text: str = "", user_id: int = 1):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id, full_name="Test User")
        self.answers: list[tuple[str, object]] = []
        self.edits: list[tuple[str, object]] = []
        self.markup_edits: list[object] = []

    async def answer(self, text, reply_markup=None, **kw):
        self.answers.append((text, reply_markup))
        return self

    async def edit_text(self, text, reply_markup=None, **kw):
        self.edits.append((text, reply_markup))
        return self

    async def edit_reply_markup(self, reply_markup=None, **kw):
        self.markup_edits.append(reply_markup)
        return self


class FakeCallback:
    def __init__(self, data: str, user_id: int = 1):
        self.data = data
        self.message = FakeMessage(user_id=user_id)
        self.from_user = SimpleNamespace(id=user_id, full_name="Test User")
        self.answered: list[tuple] = []

    async def answer(self, text=None, show_alert=False, **kw):
        self.answered.append((text, show_alert))


class FakeState:
    """FSMContext o'rniga — state va data xotirada."""

    def __init__(self, state=None, data: dict | None = None):
        self.state = state
        self.data = dict(data or {})

    async def set_state(self, state):
        self.state = state

    async def get_state(self):
        return self.state

    async def update_data(self, **kw):
        self.data.update(kw)
        return dict(self.data)

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.state = None
        self.data = {}


class FakeSession:
    async def commit(self):
        return None


def _driver_user():
    return SimpleNamespace(
        id=1, telegram_id=1, role=UserRole.driver, full_name="Test",
        phone="+998901234567", notify_enabled=True, rating=None,
        last_feed_view_at=None,
    )


def _provider_user():
    return SimpleNamespace(
        id=2, telegram_id=2, role=UserRole.cargo_provider, full_name="Test",
        phone="+998901234567", notify_enabled=True, rating=None,
    )


def _cb_datas(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _btn_texts(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


def _reply_texts(markup) -> list[str]:
    return [b.text for row in markup.keyboard for b in row]


def _last_markup(msg: FakeMessage):
    """Oxirgi yuborilgan/tahrirlangan xabar klaviaturasi."""
    if msg.answers:
        return msg.answers[-1][1]
    return msg.edits[-1][1] if msg.edits else None


# ---------------------------------------------------------------------------
# 0. Klaviatura yordamchilari
# ---------------------------------------------------------------------------

def test_back_row_tugma_va_callback():
    row = back_row("bk|reg")
    assert len(row) == 1
    assert row[0].text == BACK_TEXT
    assert row[0].callback_data == "bk|reg"


def test_back_row_64_bayt_chegarasi():
    with pytest.raises(ValueError):
        back_row("bk|" + "x" * 62)


def test_back_row_baytlarni_sanaydi_belgilarni_emas():
    # 40 ta 2-baytli belgi = 80 bayt — Telegram uchun juda uzun
    with pytest.raises(ValueError):
        back_row("ў" * 40)


def test_back_reply_kb_oxirgi_qatorda_orqaga():
    kb = back_reply_kb()
    assert _reply_texts(kb) == [BACK_TEXT]


def test_back_reply_kb_qoshimcha_qator_bilan():
    from aiogram.types import KeyboardButton
    kb = back_reply_kb([KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)])
    texts = _reply_texts(kb)
    assert texts[0] == "📱 Raqamni yuborish"
    assert texts[-1] == BACK_TEXT


def test_phone_request_kb_da_orqaga_bor():
    assert BACK_TEXT in _reply_texts(phone_request_kb())


# ---------------------------------------------------------------------------
# 1. Yuk qidirish oqimi (driver.py)
# ---------------------------------------------------------------------------

def _patch_driver(monkeypatch, **overrides):
    async def _noop(*a, **kw):
        return 0

    async def _get_or_none(session, tg_id):
        return _driver_user()

    monkeypatch.setattr(driver_handlers, "get_or_none", _get_or_none)
    monkeypatch.setattr(driver_handlers, "delete_stale_loads", _noop)
    for name, fn in overrides.items():
        monkeypatch.setattr(driver_handlers, name, fn)


def test_mashina_menyusida_orqaga_viloyatga(monkeypatch):
    async def vehicles(session, origin):
        return [("fura", 5), ("isuzu", 3)]

    _patch_driver(monkeypatch, get_vehicle_counts_by_origin=vehicles)
    cb = FakeCallback("region_Toshkent")
    asyncio.run(driver_handlers.show_vehicle_menu(cb, FakeSession()))

    markup = _last_markup(cb.message)
    assert BACK_TEXT in _btn_texts(markup)
    assert "bk|reg" in _cb_datas(markup)


def test_orqaga_mashina_turidan_viloyat_royxatiga(monkeypatch):
    async def regions(session):
        return [("Toshkent", 12), ("Andijon", 4)]

    _patch_driver(monkeypatch, get_origin_regions_with_open_loads=regions)
    cb = FakeCallback("bk|reg")
    asyncio.run(driver_handlers.back_to_regions(cb, FakeSession()))

    text = (cb.message.edits or cb.message.answers)[-1][0]
    markup = _last_markup(cb.message)
    assert "Qayerdan" in text                       # viloyat bosqichi
    assert "region_Toshkent" in _cb_datas(markup)
    assert "Asosiy menyu" not in text               # asosiy menyuga sakramaydi


def test_manzil_menyusida_orqaga_mashina_turiga(monkeypatch):
    async def dests(session, origin, vehicle=None):
        return [("Samarqand", 3)]

    _patch_driver(monkeypatch, get_destination_regions=dests)
    cb = FakeCallback("veh|Toshkent|fura")
    asyncio.run(driver_handlers.show_destinations(cb, FakeSession()))

    markup = _last_markup(cb.message)
    assert "bk|veh|Toshkent" in _cb_datas(markup)


def test_orqaga_manzildan_mashina_menyusiga(monkeypatch):
    async def vehicles(session, origin):
        return [("fura", 5), ("isuzu", 3)]

    _patch_driver(monkeypatch, get_vehicle_counts_by_origin=vehicles)
    cb = FakeCallback("bk|veh|Toshkent")
    asyncio.run(driver_handlers.back_to_vehicles(cb, FakeSession()))

    text = (cb.message.edits or cb.message.answers)[-1][0]
    markup = _last_markup(cb.message)
    assert "mashina turini" in text
    assert "veh|Toshkent|fura" in _cb_datas(markup)


def test_bitta_mashina_turi_bolsa_orqaga_viloyatga(monkeypatch):
    """Bitta tur bo'lsa mashina menyusi o'tkazib yuboriladi — orqaga viloyatga."""
    async def vehicles(session, origin):
        return [("fura", 5)]

    async def dests(session, origin, vehicle=None):
        return [("Samarqand", 3)]

    _patch_driver(
        monkeypatch,
        get_vehicle_counts_by_origin=vehicles,
        get_destination_regions=dests,
    )
    cb = FakeCallback("region_Toshkent")
    asyncio.run(driver_handlers.show_vehicle_menu(cb, FakeSession()))

    assert "bk|reg" in _cb_datas(_last_markup(cb.message))


def test_yuk_royxatida_orqaga_manzil_menyusiga(monkeypatch):
    load = SimpleNamespace(id=7)

    async def selection(session, origin, region, vehicle=None, offset=0, limit=10):
        return [load], False

    _patch_driver(monkeypatch, get_selection_loads=selection)
    monkeypatch.setattr(driver_handlers, "_fmt_load", lambda l: "yuk")
    cb = FakeCallback("dst|Toshkent|fura|Samarqand")
    asyncio.run(driver_handlers.show_dest_loads(cb, FakeSession()))

    # Oxirgi xabar — sahifalash/orqaga qatori
    markup = cb.message.answers[-1][1]
    assert "bk|dst|Toshkent|fura" in _cb_datas(markup)


def test_orqaga_royxatdan_manzil_menyusiga(monkeypatch):
    async def dests(session, origin, vehicle=None):
        return [("Samarqand", 3)]

    _patch_driver(monkeypatch, get_destination_regions=dests)
    cb = FakeCallback("bk|dst|Toshkent|fura")
    asyncio.run(driver_handlers.back_to_dests(cb, FakeSession()))

    text = (cb.message.edits or cb.message.answers)[-1][0]
    markup = _last_markup(cb.message)
    assert "Borish viloyatini" in text
    assert "dst|Toshkent|fura|Samarqand" in _cb_datas(markup)


def test_tasdiq_klaviaturasida_orqaga_bor():
    markup = driver_handlers._take_confirm_kb(42)
    assert BACK_TEXT in _btn_texts(markup)
    assert "takeno_42" in _cb_datas(markup)


def test_tasdiqdan_orqaga_yuk_kartasini_tiklaydi(monkeypatch):
    from db.models import LoadStatus

    load = SimpleNamespace(id=42, status=LoadStatus.open)

    async def detail(session, load_id):
        return load

    monkeypatch.setattr(driver_handlers, "get_load_detail", detail)
    monkeypatch.setattr(driver_handlers, "_fmt_load", lambda l: "yuk kartasi")

    cb = FakeCallback("takeno_42")
    asyncio.run(driver_handlers.take_decline_cb(cb, FakeSession()))

    text, markup = cb.message.edits[-1]
    assert text == "yuk kartasi"
    assert "take_42" in _cb_datas(markup)      # yana «🤝 Olish» bosqichi


def test_feed_orqaga_callbacklari_64_baytdan_oshmaydi():
    origin, vehicle = "Qashqadaryo viloyati", "kichik"
    for data in (
        "bk|reg",
        f"bk|veh|{origin}",
        f"bk|dst|{origin}|{vehicle}",
        "bk|rate|999999",
    ):
        assert len(data.encode("utf-8")) <= 64


# ---------------------------------------------------------------------------
# 2. Haydovchi ro'yxatdan o'tishi (DriverReg)
# ---------------------------------------------------------------------------

def test_reg_ismdan_orqaga_rol_tanlashga():
    msg = FakeMessage(BACK_TEXT)
    state = FakeState(DriverReg.waiting_name, {"role": "driver"})
    asyncio.run(start_handlers.driver_name_back(msg, state))

    assert state.state is None                       # rol tanlash — state'siz
    assert "🚛 Haydovchi" in _reply_texts(msg.answers[-1][1])


def test_reg_telefondan_orqaga_ismga():
    msg = FakeMessage(BACK_TEXT)
    state = FakeState(DriverReg.waiting_phone)
    asyncio.run(start_handlers.driver_phone_back(msg, state))

    assert state.state == DriverReg.waiting_name
    assert "Ismingiz" in msg.answers[-1][0]
    assert BACK_TEXT in _reply_texts(msg.answers[-1][1])


def test_reg_tonnajdan_orqaga_mashina_turiga():
    msg = FakeMessage(BACK_TEXT)
    state = FakeState(DriverReg.waiting_capacity)
    asyncio.run(start_handlers.driver_capacity_back(msg, state))

    assert state.state == DriverReg.waiting_vehicle_type
    assert "Isuzu" in _reply_texts(msg.answers[-1][1])


def test_reg_viloyat_menyusida_orqaga_tonnajga(monkeypatch):
    cb = FakeCallback("bk|dreg|capacity")
    state = FakeState(DriverReg.waiting_pref_origin)
    asyncio.run(start_handlers.driver_pref_origin_back(cb, state))

    assert state.state == DriverReg.waiting_capacity
    assert "quvvat" in cb.message.answers[-1][0]
    assert BACK_TEXT in _reply_texts(cb.message.answers[-1][1])


def test_reg_manzil_menyusida_orqaga_viloyatga(monkeypatch):
    async def ranked(session, origin_filter=None):
        return [("Toshkent", 5)]

    monkeypatch.setattr(start_handlers, "get_ranked_viloyats", ranked)
    cb = FakeCallback("bk|dreg|origin")
    state = FakeState(DriverReg.waiting_pref_destination, {"pref_origin": "Toshkent"})
    asyncio.run(start_handlers.driver_pref_dest_back(cb, state, FakeSession()))

    assert state.state == DriverReg.waiting_pref_origin
    assert "prego_Toshkent" in _cb_datas(cb.message.answers[-1][1])


def test_reg_xabarnomadan_orqaga_manzilga(monkeypatch):
    async def ranked(session, origin_filter=None):
        return [("Samarqand", 5)]

    monkeypatch.setattr(start_handlers, "get_ranked_viloyats", ranked)
    cb = FakeCallback("bk|dreg|dest")
    state = FakeState(DriverReg.waiting_notify, {"pref_origin": "Toshkent"})
    asyncio.run(start_handlers.driver_notify_back(cb, state, FakeSession()))

    assert state.state == DriverReg.waiting_pref_destination
    assert "predst_Samarqand" in _cb_datas(cb.message.answers[-1][1])


def test_reg_har_bosqichda_orqaga_tugmasi_bor(monkeypatch):
    """Ro'yxatdan o'tish savollarining klaviaturasida orqaga bo'lishi shart."""
    async def ranked(session, origin_filter=None):
        return [("Toshkent", 5)]

    monkeypatch.setattr(start_handlers, "get_ranked_viloyats", ranked)

    # ism → orqaga bor
    msg = FakeMessage("🚛 Haydovchi")
    state = FakeState(None)
    asyncio.run(start_handlers.role_chosen(msg, state))
    assert BACK_TEXT in _reply_texts(msg.answers[-1][1])

    # telefon → orqaga bor
    msg = FakeMessage("Alisher Qodirov")
    state = FakeState(DriverReg.waiting_name)
    asyncio.run(start_handlers.driver_name(msg, state))
    assert BACK_TEXT in _reply_texts(msg.answers[-1][1])

    # tonnaj → orqaga bor
    msg = FakeMessage("Isuzu")
    state = FakeState(DriverReg.waiting_vehicle_type)
    asyncio.run(start_handlers.driver_vehicle_type(msg, state))
    assert BACK_TEXT in _reply_texts(msg.answers[-1][1])

    # chiqish viloyati (inline) → orqaga bor
    msg = FakeMessage("5")
    state = FakeState(DriverReg.waiting_capacity)
    asyncio.run(start_handlers.driver_capacity(msg, state, FakeSession()))
    assert "bk|dreg|capacity" in _cb_datas(msg.answers[-1][1])

    # manzil (inline) → orqaga bor
    cb = FakeCallback("prego_Toshkent")
    state = FakeState(DriverReg.waiting_pref_origin)
    asyncio.run(start_handlers.driver_pref_origin(cb, state, FakeSession()))
    assert "bk|dreg|origin" in _cb_datas(cb.message.answers[-1][1])

    # xabarnoma (inline) → orqaga bor
    cb = FakeCallback("predst_Samarqand")
    state = FakeState(DriverReg.waiting_pref_destination)
    asyncio.run(start_handlers.driver_pref_destination(cb, state))
    assert "bk|dreg|dest" in _cb_datas(cb.message.answers[-1][1])


# ---------------------------------------------------------------------------
# 3. Yuk beruvchi ro'yxatdan o'tishi (ProviderReg)
# ---------------------------------------------------------------------------

def test_provider_ismdan_orqaga_rol_tanlashga():
    msg = FakeMessage(BACK_TEXT)
    state = FakeState(ProviderReg.waiting_name, {"role": "cargo_provider"})
    asyncio.run(start_handlers.provider_name_back(msg, state))

    assert state.state is None
    assert "📦 Yuk beruvchi" in _reply_texts(msg.answers[-1][1])


def test_provider_telefondan_orqaga_ismga():
    msg = FakeMessage(BACK_TEXT)
    state = FakeState(ProviderReg.waiting_phone)
    asyncio.run(start_handlers.provider_phone_back(msg, state))

    assert state.state == ProviderReg.waiting_name
    assert "Ismingiz" in msg.answers[-1][0]


# ---------------------------------------------------------------------------
# 4. Yuk joylash (LoadPost)
# ---------------------------------------------------------------------------

def test_yuk_manzildan_orqaga_jonash_shahriga():
    msg = FakeMessage(BACK_TEXT)
    state = FakeState(LoadPost.waiting_destination, {"origin": "Toshkent"})
    asyncio.run(provider_handlers.load_destination_back(msg, state))

    assert state.state == LoadPost.waiting_origin
    assert "Jo'nab ketish" in msg.answers[-1][0]
    assert BACK_TEXT in _reply_texts(msg.answers[-1][1])


def test_yuk_turidan_orqaga_manzilga():
    cb = FakeCallback("bk|load|dest")
    state = FakeState(LoadPost.waiting_cargo_type, {"origin": "Toshkent"})
    asyncio.run(provider_handlers.load_cargo_type_back(cb, state))

    assert state.state == LoadPost.waiting_destination
    assert "Yetib borish" in cb.message.answers[-1][0]


def test_yuk_vazndan_orqaga_turiga():
    msg = FakeMessage(BACK_TEXT)
    state = FakeState(LoadPost.waiting_weight)
    asyncio.run(provider_handlers.load_weight_back(msg, state))

    assert state.state == LoadPost.waiting_cargo_type
    assert "cargo_Qurilish" in _cb_datas(msg.answers[-1][1])


def test_yuk_narxdan_orqaga_vaznga():
    msg = FakeMessage(BACK_TEXT)
    state = FakeState(LoadPost.waiting_price)
    asyncio.run(provider_handlers.load_price_back(msg, state))

    assert state.state == LoadPost.waiting_weight
    assert "vazn" in msg.answers[-1][0]


def test_yuk_tasdiqdan_orqaga_narxga():
    cb = FakeCallback("bk|load|price")
    state = FakeState(LoadPost.waiting_confirm, {"weight_t": 5})
    asyncio.run(provider_handlers.load_confirm_back(cb, state))

    assert state.state == LoadPost.waiting_price
    assert "Narx" in cb.message.answers[-1][0]


def test_yuk_joylashda_har_bosqichda_orqaga_bor():
    msg = FakeMessage("Toshkent")
    state = FakeState(LoadPost.waiting_origin)
    asyncio.run(provider_handlers.load_origin(msg, state))
    assert BACK_TEXT in _reply_texts(msg.answers[-1][1])

    msg = FakeMessage("Samarqand")
    state = FakeState(LoadPost.waiting_destination, {"origin": "Toshkent"})
    asyncio.run(provider_handlers.load_destination(msg, state))
    assert "bk|load|dest" in _cb_datas(msg.answers[-1][1])

    cb = FakeCallback("cargo_Qurilish")
    state = FakeState(LoadPost.waiting_cargo_type)
    asyncio.run(provider_handlers.load_cargo_type(cb, state))
    assert BACK_TEXT in _reply_texts(cb.message.answers[-1][1])

    msg = FakeMessage("5")
    state = FakeState(LoadPost.waiting_weight)
    asyncio.run(provider_handlers.load_weight(msg, state))
    assert BACK_TEXT in _reply_texts(msg.answers[-1][1])

    msg = FakeMessage("500000")
    state = FakeState(LoadPost.waiting_price, {
        "origin": "Toshkent", "destination": "Samarqand",
        "cargo_type": "Qurilish", "weight_t": 5,
    })
    asyncio.run(provider_handlers.load_price(msg, state))
    assert "bk|load|price" in _cb_datas(msg.answers[-1][1])


# ---------------------------------------------------------------------------
# 5. Sozlamalar (rol o'zgartirish) va reyting oqimi
# ---------------------------------------------------------------------------

def test_rol_tanlashda_orqaga_profilga(monkeypatch):
    async def _get_or_none(session, tg_id):
        return _driver_user()

    monkeypatch.setattr(settings_handlers, "get_or_none", _get_or_none)

    msg = FakeMessage(BACK_TEXT)
    state = FakeState(RoleChange.waiting_role, {"reregister": True})
    asyncio.run(settings_handlers.change_role_back(msg, state, FakeSession()))

    assert state.state is None
    assert "Mening profilim" in msg.answers[-1][0]


def test_rol_ozgartirishda_orqaga_tugmasi_chiqadi():
    cb = FakeCallback("change_role")
    state = FakeState(None)
    asyncio.run(settings_handlers.change_role_start(cb, state))

    assert state.state == RoleChange.waiting_role
    assert BACK_TEXT in _reply_texts(cb.message.answers[-1][1])


def test_reyting_ballidan_orqaga_bitim_kartasiga():
    cb = FakeCallback("bk|rate|5")
    state = FakeState(RatingFlow.waiting_score, {"deal_id": 5})
    asyncio.run(driver_handlers.rating_score_back(cb, state))

    assert state.state is None
    assert "rate_deal_5" in _cb_datas(cb.message.edits[-1][1])


def test_reyting_izohdan_orqaga_ballga():
    msg = FakeMessage(BACK_TEXT)
    state = FakeState(RatingFlow.waiting_comment, {"deal_id": 5, "score": 4})
    asyncio.run(driver_handlers.rating_comment_back(msg, state))

    assert state.state == RatingFlow.waiting_score
    assert "score_5_3" in _cb_datas(msg.answers[-1][1])


# ---------------------------------------------------------------------------
# 6. Inline bosqichda reply «⬅️ Orqaga» tugmasi ham ishlaydi
#    (oldingi qadamning reply klaviaturasi ekranda qolib ketadi)
# ---------------------------------------------------------------------------

def test_reply_orqaga_inline_bosqichlarda_ham_ishlaydi(monkeypatch):
    async def ranked(session, origin_filter=None):
        return [("Toshkent", 5)]

    monkeypatch.setattr(start_handlers, "get_ranked_viloyats", ranked)

    msg = FakeMessage(BACK_TEXT)
    state = FakeState(DriverReg.waiting_pref_origin)
    asyncio.run(start_handlers.driver_pref_origin_back_text(msg, state))
    assert state.state == DriverReg.waiting_capacity

    msg = FakeMessage(BACK_TEXT)
    state = FakeState(DriverReg.waiting_pref_destination)
    asyncio.run(start_handlers.driver_pref_dest_back_text(msg, state, FakeSession()))
    assert state.state == DriverReg.waiting_pref_origin

    msg = FakeMessage(BACK_TEXT)
    state = FakeState(DriverReg.waiting_notify, {"pref_origin": "Toshkent"})
    asyncio.run(start_handlers.driver_notify_back_text(msg, state, FakeSession()))
    assert state.state == DriverReg.waiting_pref_destination

    msg = FakeMessage(BACK_TEXT)
    state = FakeState(LoadPost.waiting_cargo_type)
    asyncio.run(provider_handlers.load_cargo_type_back_text(msg, state))
    assert state.state == LoadPost.waiting_destination

    msg = FakeMessage(BACK_TEXT)
    state = FakeState(LoadPost.waiting_confirm)
    asyncio.run(provider_handlers.load_confirm_back_text(msg, state))
    assert state.state == LoadPost.waiting_price


def test_reyting_klaviaturasida_orqaga_bor():
    markup = driver_handlers._score_kb(5)
    assert "bk|rate|5" in _cb_datas(markup)
