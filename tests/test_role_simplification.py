"""Faza 3 — Rollar 2 taga qisqaradi + mashina ma'lumoti saqlanadi.

3.1 — role_choice_kb/ROLE_MAP faqat 2 rol (haydovchi, yuk beruvchi).
3.2 — /migrate_roles: asset_owner/staff_driver userlarga rol tanlash so'rovi.
3.3 — DriverReg oqimida yig'ilgan vehicle_type/capacity_t create_user/
      update_user_role'ga uzatiladi va bazada saqlanadi.

Ishga tushirish:
    python3 -m pytest tests/test_role_simplification.py
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

from aiogram.exceptions import TelegramForbiddenError  # noqa: E402

from bot.handlers import admin as admin_handlers  # noqa: E402
from bot.handlers import start as start_handlers  # noqa: E402
from bot.keyboards import role_choice_kb  # noqa: E402
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
        self.markup_edits: list = []

    async def answer(self, text, reply_markup=None, **kw):
        self.answers.append((text, reply_markup))
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
    """create_user/update_user_role uchun — session.add/flush/commit yozib boradi."""

    def __init__(self):
        self.added: list = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True


class FakeBot:
    """bot.send_message — ba'zi userlarga xato (bloklagan) simulyatsiya qilinadi."""

    def __init__(self, blocked_ids: set[int] | None = None):
        self.blocked_ids = blocked_ids or set()
        self.sent: list[tuple] = []

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        if chat_id in self.blocked_ids:
            raise TelegramForbiddenError(method=None, message="bot blocked")
        self.sent.append((chat_id, text, reply_markup))


def _reply_texts(markup) -> list[str]:
    return [b.text for row in markup.keyboard for b in row]


def _cb_datas(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _btn_texts(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


# ---------------------------------------------------------------------------
# 3.1 — role_choice_kb / ROLE_MAP faqat 2 rol
# ---------------------------------------------------------------------------

def test_role_choice_kb_faqat_ikki_rol():
    texts = _reply_texts(role_choice_kb())
    assert texts == ["🚛 Haydovchi", "📦 Yuk beruvchi"]
    assert "🏭 Asset egasi" not in texts


def test_role_choice_kb_with_back_saqlanadi():
    texts = _reply_texts(role_choice_kb(with_back=True))
    assert texts[:2] == ["🚛 Haydovchi", "📦 Yuk beruvchi"]
    assert texts[-1] == "⬅️ Orqaga"
    assert "🏭 Asset egasi" not in texts


def test_role_map_faqat_ikki_kalit():
    assert set(start_handlers.ROLE_MAP.keys()) == {"🚛 Haydovchi", "📦 Yuk beruvchi"}
    assert start_handlers.ROLE_MAP["🚛 Haydovchi"] == UserRole.driver
    assert start_handlers.ROLE_MAP["📦 Yuk beruvchi"] == UserRole.cargo_provider


def test_user_role_enum_eski_qiymatlar_saqlangan():
    """Enum qiymatlari saqlanishi shart — eski yozuvlar buzilmasin."""
    assert UserRole.asset_owner.value == "asset_owner"
    assert UserRole.staff_driver.value == "staff_driver"


# ---------------------------------------------------------------------------
# 3.2 — /migrate_roles
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


def _migrate_roles_session(users):
    session = FakeSession()

    async def execute(query):
        return _FakeResult(users)

    session.execute = execute
    return session


def test_migrate_roles_admin_emas_ishlamaydi(monkeypatch):
    monkeypatch.setattr(admin_handlers, "_is_admin", lambda tg_id: tg_id == 999)
    msg = FakeMessage(user_id=1)
    session = _migrate_roles_session([])
    bot = FakeBot()
    asyncio.run(admin_handlers.migrate_roles(msg, session, bot))
    assert msg.answers == []


def test_migrate_roles_bosh_royxat(monkeypatch):
    monkeypatch.setattr(admin_handlers, "_is_admin", lambda tg_id: tg_id == 1)
    msg = FakeMessage(user_id=1)
    session = _migrate_roles_session([])
    bot = FakeBot()
    asyncio.run(admin_handlers.migrate_roles(msg, session, bot))
    assert "yo'q" in msg.answers[-1][0]


def test_migrate_roles_xabar_va_hisobot(monkeypatch):
    monkeypatch.setattr(admin_handlers, "_is_admin", lambda tg_id: tg_id == 1)
    users = [
        SimpleNamespace(telegram_id=10, role=UserRole.asset_owner),
        SimpleNamespace(telegram_id=11, role=UserRole.staff_driver),
        SimpleNamespace(telegram_id=12, role=UserRole.asset_owner),
    ]
    msg = FakeMessage(user_id=1)
    session = _migrate_roles_session(users)
    bot = FakeBot(blocked_ids={11})

    asyncio.run(admin_handlers.migrate_roles(msg, session, bot))

    assert len(bot.sent) == 2
    sent_text = bot.sent[0][1]
    assert "rollar soddalashtirildi" in sent_text.lower()
    markup = bot.sent[0][2]
    assert "roleswitch|driver" in _cb_datas(markup)
    assert "roleswitch|cargo_provider" in _cb_datas(markup)
    assert "🚛 Haydovchi" in _btn_texts(markup)
    assert "📦 Yuk beruvchi" in _btn_texts(markup)

    report = msg.answers[-1][0]
    assert "3" in report      # jami nomzod
    assert "2" in report      # yuborildi
    assert "1" in report      # bloklagan


def test_migrate_roles_callback_data_toqnashmaydi():
    """Spec: mavjud prefikslar bilan to'qnashmasligi kerak."""
    existing_prefixes = (
        "region_", "veh|", "dst|", "more|", "bk|", "take_", "takeyes_",
        "takeno_", "score_", "rate_deal_", "cargo_", "delivered_",
        "cancel_load_", "prego_", "predst_", "notify_", "confirm_",
        "remind_enable", "toggle_notify", "change_role",
    )
    for data in ("roleswitch|driver", "roleswitch|cargo_provider"):
        assert not any(data.startswith(p) for p in existing_prefixes)


def test_role_switch_chosen_driver(monkeypatch):
    user = SimpleNamespace(
        telegram_id=10, role=UserRole.asset_owner, full_name="Ali",
        phone="+998901234567", notify_enabled=True,
        vehicle_type=None, capacity_t=None,
    )

    async def _get_or_none(session, tg_id):
        return user

    monkeypatch.setattr(admin_handlers, "get_or_none", _get_or_none)

    cb = FakeCallback("roleswitch|driver", user_id=10)
    asyncio.run(admin_handlers.role_switch_chosen(cb, FakeSession()))

    assert user.role == UserRole.driver
    text, markup = cb.message.answers[-1]
    assert "Haydovchi" in text
    assert "📦 Yuklar" in _reply_texts(markup)   # asosiy haydovchi menyusi


def test_role_switch_chosen_cargo_provider(monkeypatch):
    user = SimpleNamespace(
        telegram_id=11, role=UserRole.staff_driver, full_name="Vali",
        phone="+998901234567", notify_enabled=False,
        vehicle_type=None, capacity_t=None,
    )

    async def _get_or_none(session, tg_id):
        return user

    monkeypatch.setattr(admin_handlers, "get_or_none", _get_or_none)

    cb = FakeCallback("roleswitch|cargo_provider", user_id=11)
    asyncio.run(admin_handlers.role_switch_chosen(cb, FakeSession()))

    assert user.role == UserRole.cargo_provider
    text, markup = cb.message.answers[-1]
    assert "Yuk beruvchi" in text
    assert "➕ Yuk joylash" in _reply_texts(markup)   # asosiy provider menyusi


def test_role_switch_chosen_user_topilmasa(monkeypatch):
    async def _get_or_none(session, tg_id):
        return None

    monkeypatch.setattr(admin_handlers, "get_or_none", _get_or_none)

    cb = FakeCallback("roleswitch|driver", user_id=999)
    asyncio.run(admin_handlers.role_switch_chosen(cb, FakeSession()))

    assert cb.answered[-1][1] is True   # show_alert


# ---------------------------------------------------------------------------
# 3.3 — vehicle_type/capacity_t create_user/update_user_role'ga uzatiladi
# ---------------------------------------------------------------------------

def test_create_user_vehicle_type_va_capacity_saqlanadi():
    session = FakeSession()
    user = asyncio.run(user_service.create_user(
        session,
        telegram_id=1,
        role=UserRole.driver,
        full_name="Ali",
        phone="+998901234567",
        notify_enabled=True,
        vehicle_type=VehicleType.isuzu,
        capacity_t=5.0,
    ))
    assert user.vehicle_type == VehicleType.isuzu
    assert user.capacity_t == 5.0
    assert session.added == [user]


def test_create_user_vehicle_type_ixtiyoriy():
    """cargo_provider uchun mashina ma'lumoti yo'q — NULL bo'lishi kerak."""
    session = FakeSession()
    user = asyncio.run(user_service.create_user(
        session,
        telegram_id=2,
        role=UserRole.cargo_provider,
        full_name="Vali",
        phone="+998901234567",
    ))
    assert user.vehicle_type is None
    assert user.capacity_t is None


def test_update_user_role_yangi_vehicle_type_saqlaydi():
    user = SimpleNamespace(
        role=UserRole.asset_owner, full_name="A", phone="+998901234567",
        notify_enabled=True, vehicle_type=None, capacity_t=None,
    )
    session = FakeSession()
    result = asyncio.run(user_service.update_user_role(
        session, user,
        role=UserRole.driver, full_name="A", phone=None, notify_enabled=True,
        vehicle_type=VehicleType.kichik, capacity_t=1.5,
    ))
    assert result.vehicle_type == VehicleType.kichik
    assert result.capacity_t == 1.5


def test_update_user_role_vehicle_type_berilmasa_saqlanadi():
    """phone kabi — berilmasa (None) mavjud qiymat o'zgarmasligi kerak."""
    user = SimpleNamespace(
        role=UserRole.driver, full_name="A", phone="+998901234567",
        notify_enabled=True, vehicle_type=VehicleType.fura, capacity_t=8.0,
    )
    session = FakeSession()
    result = asyncio.run(user_service.update_user_role(
        session, user,
        role=UserRole.driver, full_name="A", phone=None, notify_enabled=True,
    ))
    assert result.vehicle_type == VehicleType.fura
    assert result.capacity_t == 8.0


def test_driver_notify_choice_vehicle_type_uzatiladi(monkeypatch):
    """DriverReg oqimi: vehicle_type/capacity_t create_user'ga borishi shart."""
    captured = {}

    async def _create_user(session, **kw):
        captured.update(kw)
        return SimpleNamespace(
            full_name=kw["full_name"], pref_origin=None, pref_destination=None,
        )

    monkeypatch.setattr(start_handlers, "create_user", _create_user)

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
    asyncio.run(start_handlers.driver_notify_choice(cb, state, FakeSession()))

    assert captured["vehicle_type"] == VehicleType.isuzu
    assert captured["capacity_t"] == 5.0


def test_driver_notify_choice_reregister_update_user_role_chaqiradi(monkeypatch):
    captured = {}

    async def _get_or_none(session, tg_id):
        return SimpleNamespace(full_name="Old")

    async def _update_user_role(session, user, **kw):
        captured.update(kw)
        return SimpleNamespace(
            full_name=kw["full_name"], pref_origin=None, pref_destination=None,
        )

    monkeypatch.setattr(start_handlers, "get_or_none", _get_or_none)
    monkeypatch.setattr(start_handlers, "update_user_role", _update_user_role)

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
    asyncio.run(start_handlers.driver_notify_choice(cb, state, FakeSession()))

    assert captured["vehicle_type"] == VehicleType.fura
    assert captured["capacity_t"] == 12.0
