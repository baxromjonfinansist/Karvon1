"""Faza 5 — Broadcast: matn/media, guruh bo'yicha checklist tanlash, yuborish.

Oqim: 1) qabul qiluvchi turi (barchasi/guruh) -> 2) guruh tanlansa rol yoki
viloyat -> 3) checklist (sahifalangan, default hammasi ☑️, chiqarib
tashlash mumkin) -> 4) kontent (matn/media) -> 5) preview+tasdiq ->
6) yuborish (copy_message, TelegramForbiddenError alohida sanaladi).

Ishga tushirish:
    python3 -m pytest tests/test_admin_broadcast.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError  # noqa: E402

from bot.handlers import admin_broadcast  # noqa: E402
from bot.states import BroadcastFlow  # noqa: E402
from db.models import UserRole  # noqa: E402


# ---------------------------------------------------------------------------
# Soxta (fake) obyektlar — DB/tarmoqsiz, mavjud testlar uslubiga mos
# ---------------------------------------------------------------------------

class FakeMessage:
    def __init__(self, text: str = "", user_id: int = 1, message_id: int = 555):
        self.text = text
        self.message_id = message_id
        self.chat = SimpleNamespace(id=user_id)
        self.from_user = SimpleNamespace(id=user_id, full_name="Test Admin")
        self.answers: list[tuple] = []
        self.edits: list[tuple] = []

    async def answer(self, text, reply_markup=None, **kw):
        self.answers.append((text, reply_markup))
        return self

    async def edit_text(self, text, reply_markup=None, **kw):
        self.edits.append((text, reply_markup))
        return self


class FakeCallback:
    def __init__(self, data: str, user_id: int = 1, message_id: int = 555):
        self.data = data
        self.message = FakeMessage(user_id=user_id, message_id=message_id)
        self.from_user = SimpleNamespace(id=user_id, full_name="Test Admin")
        self.answered: list[tuple] = []

    async def answer(self, text=None, show_alert=False, **kw):
        self.answered.append((text, show_alert))


class FakeState:
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
        pass


class FakeBot:
    """copy_message/delete_message chaqiruvlarini sanaydi; blocked/error id'lar xato tashlaydi."""

    def __init__(
        self,
        blocked_ids: set[int] | None = None,
        error_ids: set[int] | None = None,
        undeletable_ids: set[int] | None = None,
    ):
        self.blocked_ids = blocked_ids or set()
        self.error_ids = error_ids or set()
        self.undeletable_ids = undeletable_ids or set()  # delete_message xato beradi
        self.copied: list[tuple] = []
        self.deleted: list[tuple] = []

    async def copy_message(self, chat_id, from_chat_id, message_id, **kw):
        if chat_id in self.blocked_ids:
            raise TelegramForbiddenError(method=None, message="bot blocked")
        if chat_id in self.error_ids:
            raise TelegramAPIError(method=None, message="boshqa xato")
        self.copied.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=1000 + chat_id)

    async def delete_message(self, chat_id, message_id):
        if chat_id in self.undeletable_ids:
            raise TelegramAPIError(method=None, message="message can't be deleted")
        self.deleted.append((chat_id, message_id))


def _cb_datas(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _btn_texts(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


def _user(**kw):
    defaults = dict(
        id=1, telegram_id=1, role=UserRole.driver, full_name="Alisher Qodirov",
        phone="+998901234567", vehicle_type=None, capacity_t=None,
        pref_origin=None, pref_destination=None,
        created_at=datetime(2026, 8, 3, 10, 0, 0),
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _make_users(n, role=UserRole.driver, pref_origin=None):
    return [
        _user(id=i, telegram_id=i, full_name=f"User{i}", role=role, pref_origin=pref_origin,
              created_at=datetime(2026, 8, 3, 10, i))
        for i in range(n)
    ]


def _patch_group_members(monkeypatch, users):
    async def _fetch(session, group_type, group_value):
        return users

    monkeypatch.setattr(admin_broadcast, "_fetch_group_members", _fetch)


def _patch_recipient_ids(monkeypatch, ids):
    async def _resolve(session, data):
        return ids

    monkeypatch.setattr(admin_broadcast, "_resolve_recipient_ids", _resolve)


# ---------------------------------------------------------------------------
# 1. Admin bo'lmagan foydalanuvchi oqimga kira olmasligi
# ---------------------------------------------------------------------------

def test_broadcast_start_admin_emas_hech_narsa_qilmaydi(monkeypatch):
    monkeypatch.setattr(admin_broadcast, "_is_admin", lambda tg_id: tg_id == 999)
    msg = FakeMessage(user_id=1)
    state = FakeState()

    asyncio.run(admin_broadcast.broadcast_start(msg, state))

    assert msg.answers == []
    assert state.state is None


def test_broadcast_start_admin_target_kb_korsatadi(monkeypatch):
    monkeypatch.setattr(admin_broadcast, "_is_admin", lambda tg_id: tg_id == 1)
    msg = FakeMessage(user_id=1)
    state = FakeState()

    asyncio.run(admin_broadcast.broadcast_start(msg, state))

    assert state.state == BroadcastFlow.waiting_target
    text, markup = msg.answers[-1]
    datas = _cb_datas(markup)
    assert "bcast|all" in datas
    assert "bcast|group" in datas


# ---------------------------------------------------------------------------
# 2. Qabul qiluvchi tanlash — barchasi
# ---------------------------------------------------------------------------

def test_broadcast_target_all_content_bosqichiga_otadi():
    state = FakeState(BroadcastFlow.waiting_target)
    cb = FakeCallback("bcast|all")

    asyncio.run(admin_broadcast.broadcast_target_all(cb, state))

    assert state.state == BroadcastFlow.waiting_content
    assert state.data["target_type"] == "all"
    assert "Matn yoki media" in cb.message.edits[-1][0]


# ---------------------------------------------------------------------------
# 2. Qabul qiluvchi tanlash — guruh (rol / viloyat)
# ---------------------------------------------------------------------------

def test_broadcast_target_group_rol_va_viloyat_tugmalari(monkeypatch):
    async def _counts(session):
        return [("Toshkent", 5), ("Samarqand", 0)]

    monkeypatch.setattr(admin_broadcast, "count_users_by_viloyat", _counts)

    state = FakeState(BroadcastFlow.waiting_target)
    cb = FakeCallback("bcast|group")

    asyncio.run(admin_broadcast.broadcast_target_group(cb, state, FakeSession()))

    assert state.state == BroadcastFlow.waiting_group_choice
    datas = _cb_datas(cb.message.edits[-1][1])
    assert "bcast|role|driver" in datas
    assert "bcast|role|cargo_provider" in datas
    assert "bcast|vil|Toshkent" in datas
    assert "bcast|vil|Samarqand" in datas


def test_broadcast_group_role_checklist_default_hammasi_belgilangan(monkeypatch):
    users = _make_users(3, role=UserRole.driver)
    _patch_group_members(monkeypatch, users)

    state = FakeState(BroadcastFlow.waiting_group_choice)
    cb = FakeCallback("bcast|role|driver")

    asyncio.run(admin_broadcast.broadcast_group_role(cb, state, FakeSession()))

    assert state.state == BroadcastFlow.waiting_checklist
    assert state.data["group_type"] == "role"
    assert state.data["group_value"] == "driver"

    markup = cb.message.edits[-1][1]
    texts = _btn_texts(markup)
    assert all(t.startswith("☑️") for t in texts if "User" in t)
    datas = _cb_datas(markup)
    assert any(d == "bcast|cont" for d in datas)
    assert any("3 ta qabul qiluvchi" in t for t in texts)


def test_broadcast_group_viloyat_checklist(monkeypatch):
    users = _make_users(2, pref_origin="Toshkent")
    _patch_group_members(monkeypatch, users)

    state = FakeState(BroadcastFlow.waiting_group_choice)
    cb = FakeCallback("bcast|vil|Toshkent")

    asyncio.run(admin_broadcast.broadcast_group_viloyat(cb, state, FakeSession()))

    assert state.data["group_type"] == "viloyat"
    assert state.data["group_value"] == "Toshkent"
    assert state.state == BroadcastFlow.waiting_checklist


# ---------------------------------------------------------------------------
# 3. Checklist: toggle + sahifalar orasida tanlov saqlanishi
# ---------------------------------------------------------------------------

def test_broadcast_checklist_toggle_uncheck_qiladi(monkeypatch):
    users = _make_users(3, role=UserRole.driver)
    _patch_group_members(monkeypatch, users)

    state = FakeState(BroadcastFlow.waiting_checklist, {
        "group_type": "role", "group_value": "driver", "excluded_ids": [],
    })
    cb = FakeCallback("bcast|tgl|1|0")

    asyncio.run(admin_broadcast.broadcast_checklist_toggle(cb, state, FakeSession()))

    assert state.data["excluded_ids"] == [1]
    markup = cb.message.edits[-1][1]
    texts = _btn_texts(markup)
    assert any(t.startswith("⬜️") and "User1" in t for t in texts)
    assert any("2 ta qabul qiluvchi" in t for t in texts)


def test_broadcast_checklist_toggle_qayta_bossa_qaytadi_belgilanadi(monkeypatch):
    users = _make_users(3, role=UserRole.driver)
    _patch_group_members(monkeypatch, users)

    state = FakeState(BroadcastFlow.waiting_checklist, {
        "group_type": "role", "group_value": "driver", "excluded_ids": [1],
    })
    cb = FakeCallback("bcast|tgl|1|0")

    asyncio.run(admin_broadcast.broadcast_checklist_toggle(cb, state, FakeSession()))

    assert state.data["excluded_ids"] == []


def test_broadcast_checklist_tanlov_sahifalar_orasida_yoqolmaydi(monkeypatch):
    """20 ta user, 1-sahifadagi birini o'chirib, 2-sahifaga o'tib, qaytib
    kelganda ham o'sha user hali ⬜️ bo'lishi kerak (excluded_ids state'da saqlanadi)."""
    users = _make_users(20, role=UserRole.driver)
    _patch_group_members(monkeypatch, users)

    state = FakeState(BroadcastFlow.waiting_checklist, {
        "group_type": "role", "group_value": "driver", "excluded_ids": [],
    })

    # 1-sahifada 3-userni o'chiramiz (id=3, offset=0 sahifada bor: id 0..9)
    cb1 = FakeCallback("bcast|tgl|3|0")
    asyncio.run(admin_broadcast.broadcast_checklist_toggle(cb1, state, FakeSession()))
    assert state.data["excluded_ids"] == [3]

    # 2-sahifaga o'tamiz
    cb2 = FakeCallback("bcast|pg|10")
    asyncio.run(admin_broadcast.broadcast_checklist_page(cb2, state, FakeSession()))
    assert state.data["excluded_ids"] == [3]  # tanlov yo'qolmadi

    # 1-sahifaga qaytamiz
    cb3 = FakeCallback("bcast|pg|0")
    asyncio.run(admin_broadcast.broadcast_checklist_page(cb3, state, FakeSession()))
    texts = _btn_texts(cb3.message.edits[-1][1])
    assert any(t.startswith("⬜️") and "User3" in t for t in texts)


def test_broadcast_checklist_continue_hisoblaydi_va_content_ga_otadi(monkeypatch):
    users = _make_users(3, role=UserRole.driver)
    _patch_group_members(monkeypatch, users)
    _patch_recipient_ids(monkeypatch, [0, 2])  # 1 chiqarib tashlangan

    state = FakeState(BroadcastFlow.waiting_checklist, {
        "group_type": "role", "group_value": "driver", "excluded_ids": [1],
    })
    cb = FakeCallback("bcast|cont")

    asyncio.run(admin_broadcast.broadcast_checklist_continue(cb, state, FakeSession()))

    assert state.state == BroadcastFlow.waiting_content
    assert "2 ta qabul qiluvchi" in cb.message.edits[-1][0]


def test_broadcast_checklist_continue_hech_kim_qolmasa_alert(monkeypatch):
    _patch_recipient_ids(monkeypatch, [])

    state = FakeState(BroadcastFlow.waiting_checklist, {
        "group_type": "role", "group_value": "driver", "excluded_ids": [0, 1, 2],
    })
    cb = FakeCallback("bcast|cont")

    asyncio.run(admin_broadcast.broadcast_checklist_continue(cb, state, FakeSession()))

    assert state.state == BroadcastFlow.waiting_checklist  # bosqich o'zgarmadi
    assert cb.answered[-1][1] is True  # show_alert


# ---------------------------------------------------------------------------
# 4. Kontent — matn/media qabul qilish + preview
# ---------------------------------------------------------------------------

def test_broadcast_content_received_preview_va_tasdiq_kb(monkeypatch):
    _patch_recipient_ids(monkeypatch, [10, 20, 30])

    state = FakeState(BroadcastFlow.waiting_content, {"target_type": "all"})
    msg = FakeMessage(text="Salom hammaga!", user_id=1, message_id=777)
    bot = FakeBot()

    asyncio.run(admin_broadcast.broadcast_content_received(msg, state, FakeSession(), bot))

    assert state.state == BroadcastFlow.waiting_confirm
    assert state.data["content_chat_id"] == 1
    assert state.data["content_message_id"] == 777

    # Preview — adminning o'ziga copy_message
    assert bot.copied == [(1, 1, 777)]

    text, markup = msg.answers[-1]
    assert "3" in text
    datas = _cb_datas(markup)
    assert "bcast|send" in datas
    assert "bcast|cancel" in datas


# ---------------------------------------------------------------------------
# 5. Bekor qilish
# ---------------------------------------------------------------------------

def test_broadcast_cancel_state_tozalaydi():
    state = FakeState(BroadcastFlow.waiting_confirm, {"target_type": "all"})
    cb = FakeCallback("bcast|cancel")

    asyncio.run(admin_broadcast.broadcast_cancel(cb, state))

    assert state.state is None
    assert state.data == {}
    assert "bekor qilindi" in cb.message.edits[-1][0].lower()


# ---------------------------------------------------------------------------
# 5. Yuborish — copy_message, TelegramForbiddenError sanaladi, rate-limit sleep
# ---------------------------------------------------------------------------

def test_broadcast_send_hisobot_togri(monkeypatch):
    recipient_ids = [1, 2, 3, 4, 5]
    _patch_recipient_ids(monkeypatch, recipient_ids)

    sleep_calls = []

    async def _fake_sleep(delay):
        sleep_calls.append(delay)

    monkeypatch.setattr(admin_broadcast.asyncio, "sleep", _fake_sleep)

    state = FakeState(BroadcastFlow.waiting_confirm, {
        "target_type": "all", "content_chat_id": 1, "content_message_id": 777,
    })
    cb = FakeCallback("bcast|send")
    bot = FakeBot(blocked_ids={2}, error_ids={4})

    asyncio.run(admin_broadcast.broadcast_send(cb, state, FakeSession(), bot))

    # 5 ta recipient, 1 bloklangan, 1 xato, 3 muvaffaqiyatli
    assert len(bot.copied) == 3
    assert {c[0] for c in bot.copied} == {1, 3, 5}

    report = cb.message.answers[-1][0]
    assert "Jami: 5" in report
    assert "Yuborildi: 3" in report
    assert "Bloklagan: 1" in report
    assert "Xato: 1" in report

    # Har xabardan keyin rate-limit sleep chaqirilgan (real kutishsiz, monkeypatch bilan)
    assert len(sleep_calls) == 5
    assert all(d == admin_broadcast._SEND_DELAY for d in sleep_calls)

    # Yuborishdan keyin state tozalanadi
    assert state.state is None


def test_broadcast_send_bloklagan_userlar_umumiy_oqimni_toxtatmaydi(monkeypatch):
    recipient_ids = [1, 2, 3]
    _patch_recipient_ids(monkeypatch, recipient_ids)

    async def _fake_sleep(*_):
        pass

    monkeypatch.setattr(admin_broadcast.asyncio, "sleep", _fake_sleep)

    state = FakeState(BroadcastFlow.waiting_confirm, {
        "target_type": "all", "content_chat_id": 1, "content_message_id": 5,
    })
    cb = FakeCallback("bcast|send")
    bot = FakeBot(blocked_ids={1, 2})  # birinchi ikkitasi bloklagan

    asyncio.run(admin_broadcast.broadcast_send(cb, state, FakeSession(), bot))

    # 3-chi userga baribir yuborilgan — oqim bloklanganlarda to'xtamadi
    assert bot.copied == [(3, 1, 5)]


# ---------------------------------------------------------------------------
# 🗑 Yuborilgan xabarnomani hammadan o'chirish (admin so'radi)
# ---------------------------------------------------------------------------

async def _fake_sleep_noop(*_):
    pass


def _send_and_get_report(monkeypatch, recipient_ids, bot=None):
    """Yordamchi: broadcast_send'ni chaqirib, hisobot xabarini qaytaradi."""
    _patch_recipient_ids(monkeypatch, recipient_ids)
    monkeypatch.setattr(admin_broadcast.asyncio, "sleep", _fake_sleep_noop)
    monkeypatch.setattr(admin_broadcast, "_is_admin", lambda tg_id: tg_id == 1)
    state = FakeState(BroadcastFlow.waiting_confirm, {
        "target_type": "all", "content_chat_id": 1, "content_message_id": 5,
    })
    cb = FakeCallback("bcast|send")
    bot = bot or FakeBot()
    asyncio.run(admin_broadcast.broadcast_send(cb, state, FakeSession(), bot))
    return cb, bot


def test_broadcast_send_report_has_delete_button(monkeypatch):
    cb, bot = _send_and_get_report(monkeypatch, [1, 2, 3])

    report_text, kb = cb.message.answers[-1]
    datas = _cb_datas(kb)
    assert any(d.startswith("bcast|del|") for d in datas)


def test_broadcast_send_hech_kimga_yetmasa_delete_tugmasi_yoq(monkeypatch):
    bot = FakeBot(blocked_ids={1, 2, 3})
    cb, bot = _send_and_get_report(monkeypatch, [1, 2, 3], bot=bot)

    report_text, kb = cb.message.answers[-1]
    if kb is not None:
        assert not any(d.startswith("bcast|del|") for d in _cb_datas(kb))


def test_broadcast_delete_sent_barchasidan_ochiradi(monkeypatch):
    cb, bot = _send_and_get_report(monkeypatch, [1, 2, 3])
    broadcast_id = _cb_datas(cb.message.answers[-1][1])[0].split("|")[2]

    del_cb = FakeCallback(f"bcast|del|{broadcast_id}")
    asyncio.run(admin_broadcast.broadcast_delete_sent(del_cb, bot))

    assert set(bot.deleted) == {(1, 1001), (2, 1002), (3, 1003)}


def test_broadcast_delete_sent_admin_emas_ochirmaydi(monkeypatch):
    cb, bot = _send_and_get_report(monkeypatch, [1, 2, 3])
    broadcast_id = _cb_datas(cb.message.answers[-1][1])[0].split("|")[2]

    del_cb = FakeCallback(f"bcast|del|{broadcast_id}", user_id=999)  # admin emas
    asyncio.run(admin_broadcast.broadcast_delete_sent(del_cb, bot))

    assert bot.deleted == []
    assert del_cb.answered[-1][1] is True  # show_alert


def test_broadcast_delete_sent_qisman_xato_umumiy_oqimni_toxtatmaydi(monkeypatch):
    bot = FakeBot(undeletable_ids={2})  # 2-chi juda eski/allaqachon o'chirilgan
    cb, bot = _send_and_get_report(monkeypatch, [1, 2, 3], bot=bot)
    broadcast_id = _cb_datas(cb.message.answers[-1][1])[0].split("|")[2]

    del_cb = FakeCallback(f"bcast|del|{broadcast_id}")
    asyncio.run(admin_broadcast.broadcast_delete_sent(del_cb, bot))

    # 1 va 3 o'chdi, 2 xato berdi — lekin oqim to'xtamadi
    assert set(bot.deleted) == {(1, 1001), (3, 1003)}
    result_text = del_cb.message.edits[-1][0]
    assert "2" in result_text and "3" in result_text  # 2/3 o'chirildi


def test_broadcast_delete_sent_tugma_qayta_bosilsa_alert(monkeypatch):
    """Bir marta o'chirilgan xabarnomani qayta o'chirishga urinish — jim xato bermaydi."""
    cb, bot = _send_and_get_report(monkeypatch, [1, 2, 3])
    broadcast_id = _cb_datas(cb.message.answers[-1][1])[0].split("|")[2]

    del_cb1 = FakeCallback(f"bcast|del|{broadcast_id}")
    asyncio.run(admin_broadcast.broadcast_delete_sent(del_cb1, bot))
    bot.deleted.clear()

    del_cb2 = FakeCallback(f"bcast|del|{broadcast_id}")
    asyncio.run(admin_broadcast.broadcast_delete_sent(del_cb2, bot))

    assert bot.deleted == []  # ikkinchi marta hech narsa o'chirilmadi
    assert del_cb2.answered[-1][1] is True  # show_alert — "topilmadi"


def test_broadcast_delete_sent_notogri_id_alert(monkeypatch):
    cb, bot = _send_and_get_report(monkeypatch, [1, 2, 3])

    del_cb = FakeCallback("bcast|del|999999")  # hech qachon mavjud bo'lmagan id
    asyncio.run(admin_broadcast.broadcast_delete_sent(del_cb, bot))

    assert bot.deleted == []
    assert del_cb.answered[-1][1] is True


def test_broadcast_registry_bounded_eski_yozuvlar_chiqib_ketadi(monkeypatch):
    """Xotira cheksiz o'smasin — juda ko'p broadcast keyin eskilari unutiladi."""
    ids = []
    for _ in range(admin_broadcast._MAX_TRACKED_BROADCASTS + 5):
        cb, bot = _send_and_get_report(monkeypatch, [1])
        ids.append(_cb_datas(cb.message.answers[-1][1])[0].split("|")[2])

    assert len(admin_broadcast._SENT_BROADCASTS) <= admin_broadcast._MAX_TRACKED_BROADCASTS
    # eng birinchisi endi registrda yo'q
    assert int(ids[0]) not in admin_broadcast._SENT_BROADCASTS


# ---------------------------------------------------------------------------
# Callback_data prefiksi mavjudlar bilan to'qnashmasligi (spec talabi)
# ---------------------------------------------------------------------------

def test_bcast_prefiks_mavjud_prefikslar_bilan_toqnashmaydi():
    existing_prefixes = (
        "region_", "veh|", "dst|", "more|", "bk|", "take_", "takeyes_",
        "takeno_", "score_", "rate_deal_", "cargo_", "delivered_",
        "cancel_load_", "prego_", "predst_", "notify_", "confirm_",
        "remind_enable", "toggle_notify", "change_role", "roleswitch|",
        "approve_", "reject_", "ulist|",
    )
    sample_datas = (
        "bcast|all", "bcast|group", "bcast|role|driver", "bcast|vil|Toshkent",
        "bcast|tgl|123|0", "bcast|pg|10", "bcast|cont", "bcast|send", "bcast|cancel",
    )
    for data in sample_datas:
        assert not any(data.startswith(p) for p in existing_prefixes)


# ---------------------------------------------------------------------------
# user_service — list_users viloyat_filter, count_users_by_viloyat
# ---------------------------------------------------------------------------

from bot.services import user_service  # noqa: E402


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)

    def all(self):
        return self._rows


def _users_session(users):
    session = FakeSession()

    async def execute(query):
        return _FakeResult(users)

    session.execute = execute
    return session


def test_list_users_viloyat_filter():
    users = (
        _make_users(2, pref_origin="Toshkent")
        + _make_users(3, pref_origin="Samarqand")
    )
    session = _users_session(users)
    page, has_more = asyncio.run(
        user_service.list_users(session, viloyat_filter="Toshkent", offset=0, limit=10)
    )
    assert len(page) == 2
    assert all(u.pref_origin == "Toshkent" for u in page)


def test_list_users_rol_va_viloyat_birga():
    users = (
        _make_users(2, role=UserRole.driver, pref_origin="Toshkent")
        + _make_users(2, role=UserRole.cargo_provider, pref_origin="Toshkent")
        + _make_users(2, role=UserRole.driver, pref_origin="Samarqand")
    )
    session = _users_session(users)
    page, has_more = asyncio.run(
        user_service.list_users(
            session, role_filter="driver", viloyat_filter="Toshkent", offset=0, limit=10
        )
    )
    assert len(page) == 2
    assert all(u.role == UserRole.driver and u.pref_origin == "Toshkent" for u in page)


def test_count_users_by_viloyat_barcha_viloyatlar_qaytadi(monkeypatch):
    rows = [("Toshkent", 5), ("Samarqand", 2)]

    class _CountResult:
        def all(self):
            return rows

    async def execute(query):
        return _CountResult()

    session = FakeSession()
    session.execute = execute

    result = asyncio.run(user_service.count_users_by_viloyat(session))
    result_dict = dict(result)

    assert result_dict["Toshkent"] == 5
    assert result_dict["Samarqand"] == 2
    # 0-user viloyatlar ham ro'yxatda (ALL_VILOYATS to'ldiradi)
    assert "Buxoro" in result_dict
    assert result_dict["Buxoro"] == 0
    # Ko'p userlisi birinchi
    assert result[0][0] == "Toshkent"
