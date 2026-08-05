"""Deep-link (/start load_<id>) — yuk raqamini ochish oqimi."""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from bot.handlers import start as start_handlers  # noqa: E402
from bot.states import DriverReg  # noqa: E402
from db.models import UserRole  # noqa: E402


class FakeMessage:
    def __init__(self, text: str = "", user_id: int = 1):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id, full_name="Test User")
        self.contact = None
        self.answers: list[tuple] = []

    async def answer(self, text, reply_markup=None, **kw):
        self.answers.append((text, reply_markup))
        return self

    async def answer_video(self, *a, **kw):
        return self


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


def _load(load_id=42, phone="+998901112233"):
    route = SimpleNamespace(origin="Toshkent", destination="Andijon")
    return SimpleNamespace(
        id=load_id, route=route, contact_phone=phone, raw_text="",
        note=None, cargo_type=None, posted_at=None, first_time_phone=True,
    )


def _user(role=UserRole.driver):
    return SimpleNamespace(telegram_id=1, role=role)


# ---------------------------------------------------------------------------
# 1) Ro'yxatdan o'tgan user + deep-link -> darhol ko'rsatiladi
# ---------------------------------------------------------------------------

def test_existing_user_deeplink_shows_load(monkeypatch):
    load = _load()

    async def fake_get_load_detail(session, load_id):
        assert load_id == 42
        return load

    async def fake_get_or_none(session, telegram_id):
        return _user()

    monkeypatch.setattr(start_handlers, "get_load_detail", fake_get_load_detail)
    monkeypatch.setattr(start_handlers, "get_or_none", fake_get_or_none)

    message = FakeMessage(text="/start load_42")
    state = FakeState()
    asyncio.run(start_handlers.cmd_start(message, FakeSession(), state))

    joined = "\n".join(a[0] for a in message.answers)
    assert load.contact_phone in joined   # show_phone=True — raqam matnda


def test_existing_user_deeplink_load_missing(monkeypatch):
    async def fake_get_load_detail(session, load_id):
        return None

    async def fake_get_or_none(session, telegram_id):
        return _user()

    monkeypatch.setattr(start_handlers, "get_load_detail", fake_get_load_detail)
    monkeypatch.setattr(start_handlers, "get_or_none", fake_get_or_none)

    message = FakeMessage(text="/start load_999")
    state = FakeState()
    asyncio.run(start_handlers.cmd_start(message, FakeSession(), state))

    joined = "\n".join(a[0] for a in message.answers)
    assert "mavjud emas" in joined


# ---------------------------------------------------------------------------
# 2) Yangi user + deep-link -> pending_load_id state'da saqlanadi
# ---------------------------------------------------------------------------

def test_new_user_deeplink_saves_pending_load_id(monkeypatch):
    async def fake_get_or_none(session, telegram_id):
        return None   # hali ro'yxatdan o'tmagan

    async def fake_get_instruction(session):
        return {"video_file_id": None, "text": None}

    monkeypatch.setattr(start_handlers, "get_or_none", fake_get_or_none)
    monkeypatch.setattr(start_handlers, "get_instruction", fake_get_instruction)

    message = FakeMessage(text="/start load_42")
    state = FakeState()
    asyncio.run(start_handlers.cmd_start(message, FakeSession(), state))

    assert state.data.get("pending_load_id") == 42


# ---------------------------------------------------------------------------
# 3) DriverReg: telefon berilgach pending yuk ko'rsatiladi, oqim davom etadi
# ---------------------------------------------------------------------------

def test_driver_phone_reveals_pending_load_then_asks_vehicle(monkeypatch):
    load = _load()

    async def fake_get_load_detail(session, load_id):
        return load

    monkeypatch.setattr(start_handlers, "get_load_detail", fake_get_load_detail)

    message = FakeMessage(text="901234567")
    state = FakeState(
        state=DriverReg.waiting_phone,
        data={"role": UserRole.driver.value, "full_name": "Test", "pending_load_id": 42},
    )
    asyncio.run(start_handlers.driver_phone_text(message, state, FakeSession()))

    joined = "\n".join(a[0] for a in message.answers)
    assert load.contact_phone in joined
    assert state.state == DriverReg.waiting_vehicle_type
    assert state.data.get("pending_load_id") is None   # tozalangan
