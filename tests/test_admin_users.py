"""Faza 4 — Admin: yangi user xabarnomasi + userlar ro'yxati.

4.1 — notify_admins_new_user: ro'yxatdan o'tish tugagach barcha adminlarga
      xabar (bloklagan admin bo'lsa ham asosiy oqim uzilmaydi).
4.2 — list_users (sahifalash + filtr) va «📇 Userlar ro'yxati» handler'i.

Ishga tushirish:
    python3 -m pytest tests/test_admin_users.py
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

from aiogram.exceptions import TelegramForbiddenError  # noqa: E402

from bot.handlers import admin_users  # noqa: E402
from bot.handlers import start as start_handlers  # noqa: E402
from bot.services import user_service  # noqa: E402
from bot.states import DriverReg  # noqa: E402
from db.models import UserRole, VehicleType  # noqa: E402


# ---------------------------------------------------------------------------
# Soxta (fake) obyektlar — DB va tarmoqsiz
# ---------------------------------------------------------------------------

class FakeMessage:
    def __init__(self, text: str = "", user_id: int = 1):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id, full_name="Test Admin")
        self.answers: list[tuple] = []
        self.edits: list[tuple] = []
        self.markup_edits: list = []

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
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


class FakeBot:
    """bot.send_message — ba'zi adminlarga xato (bloklagan) simulyatsiya qilinadi."""

    def __init__(self, blocked_ids: set[int] | None = None):
        self.blocked_ids = blocked_ids or set()
        self.sent: list[tuple] = []

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        if chat_id in self.blocked_ids:
            raise TelegramForbiddenError(method=None, message="bot blocked")
        self.sent.append((chat_id, text, reply_markup))


def _cb_datas(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _btn_texts(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


def _user(**kw):
    defaults = dict(
        id=1, telegram_id=1, role=UserRole.driver, full_name="Alisher Qodirov",
        phone="+998901234567", vehicle_type=None, capacity_t=None,
        created_at=datetime(2026, 8, 3, 10, 0, 0),
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# 4.1 — notify_admins_new_user
# ---------------------------------------------------------------------------

def test_notify_admins_new_user_matn_va_tarkib(monkeypatch):
    monkeypatch.setattr(admin_users.settings, "ADMIN_IDS", "100,200")
    monkeypatch.setattr(admin_users.settings, "ADMIN_ID", None)

    user = _user(
        role=UserRole.driver, full_name="Alisher Qodirov", phone="+998901234567",
        vehicle_type=VehicleType.isuzu, capacity_t=5.0,
    )
    bot = FakeBot()
    asyncio.run(admin_users.notify_admins_new_user(bot, user))

    assert len(bot.sent) == 2
    ids_sent = {chat_id for chat_id, _, _ in bot.sent}
    assert ids_sent == {100, 200}

    text = bot.sent[0][1]
    assert "🆕 Yangi foydalanuvchi" in text
    assert "Alisher Qodirov" in text
    assert "+998901234567" in text
    assert "Haydovchi" in text
    assert "Isuzu" in text and "5 t" in text


def test_notify_admins_new_user_cargo_provider_mashinasiz(monkeypatch):
    """Yuk beruvchida mashina yo'q — «Mashina:» qatori chiqmasligi kerak."""
    monkeypatch.setattr(admin_users.settings, "ADMIN_IDS", "100")
    monkeypatch.setattr(admin_users.settings, "ADMIN_ID", None)

    user = _user(role=UserRole.cargo_provider, vehicle_type=None, capacity_t=None)
    bot = FakeBot()
    asyncio.run(admin_users.notify_admins_new_user(bot, user))

    text = bot.sent[0][1]
    assert "Yuk beruvchi" in text
    assert "Mashina:" not in text


def test_notify_admins_new_user_bloklagan_admin_xato_yutiladi(monkeypatch):
    """Bitta admin bloklagan bo'lsa ham — boshqasiga yuboriladi, xato ko'tarilmaydi."""
    monkeypatch.setattr(admin_users.settings, "ADMIN_IDS", "100,200,300")
    monkeypatch.setattr(admin_users.settings, "ADMIN_ID", None)

    user = _user()
    bot = FakeBot(blocked_ids={200})
    asyncio.run(admin_users.notify_admins_new_user(bot, user))

    ids_sent = {chat_id for chat_id, _, _ in bot.sent}
    assert ids_sent == {100, 300}


def test_notify_admins_new_user_admin_yoq_hech_narsa_yubormaydi(monkeypatch):
    monkeypatch.setattr(admin_users.settings, "ADMIN_IDS", "")
    monkeypatch.setattr(admin_users.settings, "ADMIN_ID", None)

    bot = FakeBot()
    asyncio.run(admin_users.notify_admins_new_user(bot, _user()))
    assert bot.sent == []


# ---------------------------------------------------------------------------
# 4.1 — start.py oqimi notify_admins_new_user'ni chaqirishi kerak
# ---------------------------------------------------------------------------

def test_driver_notify_choice_admin_xabar_yuboradi(monkeypatch):
    captured = {}

    async def _create_user(session, **kw):
        return _user(role=UserRole.driver, full_name=kw["full_name"], phone=kw.get("phone"),
                     vehicle_type=VehicleType.isuzu, capacity_t=5.0)

    async def _notify(bot, user):
        captured["bot"] = bot
        captured["user"] = user

    monkeypatch.setattr(start_handlers, "create_user", _create_user)
    monkeypatch.setattr(start_handlers, "notify_admins_new_user", _notify)

    cb = FakeCallback("notify_yes", user_id=42)
    state = FakeState(DriverReg.waiting_notify, {
        "role": "driver",
        "full_name": "Alisher Qodirov",
        "phone": "+998901234567",
        "vehicle_type": "Isuzu",
        "capacity_t": 5.0,
        "pref_origin": "Toshkent",
        "pref_destination": "Samarqand",
    })
    bot = FakeBot()
    asyncio.run(start_handlers.driver_notify_choice(cb, state, FakeSession(), bot))

    assert captured["bot"] is bot
    assert captured["user"].full_name == "Alisher Qodirov"


def test_driver_notify_choice_reregisterda_xabar_yuborilmaydi(monkeypatch):
    """Rol almashtirish (reregister) — YANGI user emas, xabar kerak emas."""
    called = {"count": 0}

    async def _get_or_none(session, tg_id):
        return _user()

    async def _update_user_role(session, user, **kw):
        return _user(full_name=kw["full_name"])

    async def _notify(bot, user):
        called["count"] += 1

    monkeypatch.setattr(start_handlers, "get_or_none", _get_or_none)
    monkeypatch.setattr(start_handlers, "update_user_role", _update_user_role)
    monkeypatch.setattr(start_handlers, "notify_admins_new_user", _notify)

    cb = FakeCallback("notify_no", user_id=43)
    state = FakeState(DriverReg.waiting_notify, {
        "reregister": True,
        "role": "driver",
        "full_name": "Botir Yusupov",
        "phone": "+998901234567",
        "vehicle_type": "Fura",
        "capacity_t": 12.0,
        "pref_origin": "Toshkent",
        "pref_destination": "Buxoro",
    })
    asyncio.run(start_handlers.driver_notify_choice(cb, state, FakeSession(), FakeBot()))

    assert called["count"] == 0


def test_driver_notify_choice_bot_yoq_bosa_ham_oqim_buzilmaydi(monkeypatch):
    """bot=None (masalan eski chaqiruv/test) — notify chaqirilmaydi, xato chiqmaydi."""
    async def _create_user(session, **kw):
        return _user(full_name=kw["full_name"])

    monkeypatch.setattr(start_handlers, "create_user", _create_user)

    cb = FakeCallback("notify_yes", user_id=44)
    state = FakeState(DriverReg.waiting_notify, {
        "role": "driver", "full_name": "Test User", "phone": "+998901234567",
        "pref_origin": "Toshkent", "pref_destination": "Samarqand",
    })
    # bot argumenti berilmaydi — eski chaqiruv uslubiga moslik.
    asyncio.run(start_handlers.driver_notify_choice(cb, state, FakeSession()))
    assert cb.message.answers  # oqim davom etdi, xato chiqmadi


def test_finish_provider_reg_admin_xabar_yuboradi(monkeypatch):
    captured = {}

    async def _create_user(session, **kw):
        return _user(role=UserRole.cargo_provider, full_name=kw["full_name"], phone=kw.get("phone"))

    async def _notify(bot, user):
        captured["user"] = user

    monkeypatch.setattr(start_handlers, "create_user", _create_user)
    monkeypatch.setattr(start_handlers, "notify_admins_new_user", _notify)

    msg = FakeMessage(user_id=50)
    state = FakeState(None, {"role": "cargo_provider", "full_name": "Vali Aliyev"})
    bot = FakeBot()
    asyncio.run(start_handlers._finish_provider_reg(msg, state, FakeSession(), "+998901234567", bot))

    assert captured["user"].full_name == "Vali Aliyev"


# ---------------------------------------------------------------------------
# 4.2 — list_users: filtr + sahifalash
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


def _users_session(users):
    session = FakeSession()

    async def execute(query):
        return _FakeResult(users)

    session.execute = execute
    return session


def _make_users(n, role=UserRole.driver):
    return [
        _user(id=i, telegram_id=i, full_name=f"User{i}", role=role,
              created_at=datetime(2026, 8, 3, 10, i))
        for i in range(n)
    ]


def test_list_users_sahifalash_birinchi_sahifa():
    users = _make_users(25)
    session = _users_session(users)
    page, has_more = asyncio.run(user_service.list_users(session, offset=0, limit=10))
    assert len(page) == 10
    assert has_more is True


def test_list_users_sahifalash_oxirgi_sahifa():
    users = _make_users(25)
    session = _users_session(users)
    page, has_more = asyncio.run(user_service.list_users(session, offset=20, limit=10))
    assert len(page) == 5
    assert has_more is False


def test_list_users_filtr_driver_asset_owner_staff_driver_ham_kiradi():
    users = (
        _make_users(2, role=UserRole.driver)
        + _make_users(2, role=UserRole.asset_owner)
        + _make_users(2, role=UserRole.staff_driver)
        + _make_users(2, role=UserRole.cargo_provider)
    )
    session = _users_session(users)
    page, has_more = asyncio.run(
        user_service.list_users(session, role_filter="driver", offset=0, limit=10)
    )
    assert len(page) == 6
    assert has_more is False
    assert all(u.role in (UserRole.driver, UserRole.asset_owner, UserRole.staff_driver) for u in page)


def test_list_users_filtr_cargo_provider():
    users = _make_users(3, role=UserRole.driver) + _make_users(4, role=UserRole.cargo_provider)
    session = _users_session(users)
    page, has_more = asyncio.run(
        user_service.list_users(session, role_filter="cargo_provider", offset=0, limit=10)
    )
    assert len(page) == 4
    assert all(u.role == UserRole.cargo_provider for u in page)


def test_list_users_filtr_none_barchasi():
    users = _make_users(3, role=UserRole.driver) + _make_users(4, role=UserRole.cargo_provider)
    session = _users_session(users)
    page, has_more = asyncio.run(user_service.list_users(session, role_filter=None, offset=0, limit=10))
    assert len(page) == 7


# ---------------------------------------------------------------------------
# 4.2 — «📇 Userlar ro'yxati» handler
# ---------------------------------------------------------------------------

def test_users_list_menu_admin_emas_ishlamaydi(monkeypatch):
    monkeypatch.setattr(admin_users, "_is_admin", lambda tg_id: tg_id == 999)
    msg = FakeMessage(user_id=1)
    session = _users_session([])
    asyncio.run(admin_users.users_list_menu(msg, session))
    assert msg.answers == []


def test_users_list_menu_admin_royxatni_korsatadi(monkeypatch):
    monkeypatch.setattr(admin_users, "_is_admin", lambda tg_id: tg_id == 1)
    users = _make_users(3)
    msg = FakeMessage(user_id=1)
    session = _users_session(users)

    asyncio.run(admin_users.users_list_menu(msg, session))

    text, markup = msg.answers[-1]
    assert "Userlar ro'yxati" in text
    assert "User0" in text
    # Filtr tugmalari mavjud
    datas = _cb_datas(markup)
    assert "ulist|all|0" in datas
    assert "ulist|driver|0" in datas
    assert "ulist|cargo_provider|0" in datas


def test_users_list_page_callback_sahifalash_tugmalari(monkeypatch):
    monkeypatch.setattr(admin_users, "_is_admin", lambda tg_id: tg_id == 1)
    users = _make_users(15)
    session = _users_session(users)

    cb = FakeCallback("ulist|all|0", user_id=1)
    asyncio.run(admin_users.users_list_page(cb, session))

    text, markup = cb.message.edits[-1]
    datas = _cb_datas(markup)
    assert "ulist|all|10" in datas   # "Keyingi"
    assert not any(d.endswith("|-10") for d in datas)  # "Oldingi" birinchi sahifada yo'q


def test_users_list_page_callback_ikkinchi_sahifada_oldingi_tugma_bor(monkeypatch):
    monkeypatch.setattr(admin_users, "_is_admin", lambda tg_id: tg_id == 1)
    users = _make_users(15)
    session = _users_session(users)

    cb = FakeCallback("ulist|all|10", user_id=1)
    asyncio.run(admin_users.users_list_page(cb, session))

    text, markup = cb.message.edits[-1]
    datas = _cb_datas(markup)
    assert "ulist|all|0" in datas or any("ulist|all|0" == d for d in datas)


def test_users_list_page_admin_emas_ruxsat_yoq(monkeypatch):
    monkeypatch.setattr(admin_users, "_is_admin", lambda tg_id: tg_id == 999)
    session = _users_session([])
    cb = FakeCallback("ulist|all|0", user_id=1)
    asyncio.run(admin_users.users_list_page(cb, session))
    assert cb.answered[-1][1] is True  # show_alert
    assert cb.message.edits == []


def test_users_list_page_filtr_callback_data_toqnashmaydi():
    """Spec: mavjud prefikslar bilan to'qnashmasligi kerak."""
    existing_prefixes = (
        "region_", "veh|", "dst|", "more|", "bk|", "take_", "takeyes_",
        "takeno_", "score_", "rate_deal_", "cargo_", "delivered_",
        "cancel_load_", "prego_", "predst_", "notify_", "confirm_",
        "remind_enable", "toggle_notify", "change_role", "roleswitch|",
        "approve_", "reject_",
    )
    for data in ("ulist|all|0", "ulist|driver|0", "ulist|cargo_provider|10"):
        assert not any(data.startswith(p) for p in existing_prefixes)
