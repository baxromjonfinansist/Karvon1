"""Faza 6 — Bot instruksiyasi (video/matn).

6.1 — Admin: 🎬 Instruksiya -> Video yuklash / Matn / Ko'rish, `app_settings`
jadvalida saqlanadi (settings_service.py).
6.2 — Foydalanuvchi: yangi user /start da instruksiya bo'lsa ko'rsatiladi,
«✅ Ko'rdim»/«⏭ Keyinroq» ikkalasi ham rol tanlashga o'tkazadi; mavjud
userlar uchun ko'rsatilmaydi; asosiy menyudan «📖 Instruksiya» qayta ko'rish.

Ishga tushirish:
    python3 -m pytest tests/test_instruction.py
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

from bot.handlers import instruction as instruction_handlers  # noqa: E402
from bot.handlers import start as start_handlers  # noqa: E402
from bot.services import settings_service  # noqa: E402
from bot.states import InstructionFlow  # noqa: E402
from db.models import UserRole  # noqa: E402


# ---------------------------------------------------------------------------
# Soxta (fake) obyektlar — DB/tarmoqsiz, mavjud testlar uslubiga mos
# ---------------------------------------------------------------------------

class FakeMessage:
    def __init__(self, text: str = "", user_id: int = 1, video=None):
        self.text = text
        self.video = video
        self.from_user = SimpleNamespace(id=user_id, full_name="Test User")
        self.answers: list[tuple] = []
        self.edits: list[tuple] = []
        self.videos: list[str] = []
        self.markup_edits: list = []

    async def answer(self, text, reply_markup=None, **kw):
        self.answers.append((text, reply_markup))
        return self

    async def answer_video(self, video, **kw):
        self.videos.append(video)
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
    async def commit(self):
        pass


def _cb_datas(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _btn_texts(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


def _reply_texts(markup) -> list[str]:
    return [b.text for row in markup.keyboard for b in row]


# ---------------------------------------------------------------------------
# settings_service — get_instruction / save_instruction_video / save_instruction_text
# ---------------------------------------------------------------------------

class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class FakeSettingsSession:
    """execute() chaqiruvlar tartibi bo'yicha oldindan tayyorlangan natijalarni qaytaradi."""

    def __init__(self, results):
        self._results = list(results)
        self.added: list = []
        self.committed = False

    async def execute(self, query):
        return self._results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


def test_get_instruction_hech_narsa_sozlanmagan():
    session = FakeSettingsSession([_Result(None), _Result(None)])
    result = asyncio.run(settings_service.get_instruction(session))
    assert result == {"video_file_id": None, "text": None}


def test_get_instruction_video_va_matn_bor():
    video = SimpleNamespace(file_id="VIDEOID123")
    text = SimpleNamespace(value="Botdan qanday foydalanish...")
    session = FakeSettingsSession([_Result(video), _Result(text)])
    result = asyncio.run(settings_service.get_instruction(session))
    assert result == {"video_file_id": "VIDEOID123", "text": "Botdan qanday foydalanish..."}


def test_save_instruction_video_yangi_yozadi():
    session = FakeSettingsSession([_Result(None)])
    asyncio.run(settings_service.save_instruction_video(session, "VID999"))
    assert len(session.added) == 1
    assert session.added[0].key == "instruction_video"
    assert session.added[0].file_id == "VID999"
    assert session.committed is True


def test_save_instruction_video_mavjudini_yangilaydi():
    existing = SimpleNamespace(key="instruction_video", file_id="OLD")
    session = FakeSettingsSession([_Result(existing)])
    asyncio.run(settings_service.save_instruction_video(session, "NEW"))
    assert session.added == []
    assert existing.file_id == "NEW"
    assert session.committed is True


def test_save_instruction_text_yangi_yozadi():
    session = FakeSettingsSession([_Result(None)])
    asyncio.run(settings_service.save_instruction_text(session, "Yangi matn"))
    assert len(session.added) == 1
    assert session.added[0].key == "instruction_text"
    assert session.added[0].value == "Yangi matn"


def test_save_instruction_text_mavjudini_yangilaydi():
    existing = SimpleNamespace(key="instruction_text", value="Eski matn")
    session = FakeSettingsSession([_Result(existing)])
    asyncio.run(settings_service.save_instruction_text(session, "Yangilangan matn"))
    assert session.added == []
    assert existing.value == "Yangilangan matn"


# ---------------------------------------------------------------------------
# 6.1 — Admin handlerlar
# ---------------------------------------------------------------------------

def test_instruction_menu_admin_emas_hech_narsa_qilmaydi(monkeypatch):
    monkeypatch.setattr(instruction_handlers, "_is_admin", lambda tg_id: tg_id == 999)
    msg = FakeMessage(user_id=1)
    asyncio.run(instruction_handlers.instruction_menu(msg))
    assert msg.answers == []


def test_instruction_menu_admin_uch_tugma_korsatadi(monkeypatch):
    monkeypatch.setattr(instruction_handlers, "_is_admin", lambda tg_id: tg_id == 1)
    msg = FakeMessage(user_id=1)
    asyncio.run(instruction_handlers.instruction_menu(msg))
    text, markup = msg.answers[-1]
    datas = _cb_datas(markup)
    assert datas == ["instr|video", "instr|text", "instr|view"]


def test_instruction_ask_video_admin_emas(monkeypatch):
    monkeypatch.setattr(instruction_handlers, "_is_admin", lambda tg_id: tg_id == 999)
    cb = FakeCallback("instr|video", user_id=1)
    state = FakeState()
    asyncio.run(instruction_handlers.instruction_ask_video(cb, state))
    assert cb.answered[-1][1] is True  # show_alert
    assert state.state is None


def test_instruction_ask_video_state_ozgaradi(monkeypatch):
    monkeypatch.setattr(instruction_handlers, "_is_admin", lambda tg_id: tg_id == 1)
    cb = FakeCallback("instr|video", user_id=1)
    state = FakeState()
    asyncio.run(instruction_handlers.instruction_ask_video(cb, state))
    assert state.state == InstructionFlow.waiting_video
    assert "video" in cb.message.edits[-1][0].lower()


def test_instruction_video_received_saqlaydi(monkeypatch):
    captured = {}

    async def _save(session, file_id):
        captured["file_id"] = file_id

    monkeypatch.setattr(instruction_handlers, "save_instruction_video", _save)

    msg = FakeMessage(user_id=1, video=SimpleNamespace(file_id="VID1"))
    state = FakeState(InstructionFlow.waiting_video)
    asyncio.run(instruction_handlers.instruction_video_received(msg, state, FakeSession()))

    assert captured["file_id"] == "VID1"
    assert state.state is None
    assert "saqlandi" in msg.answers[-1][0].lower()


def test_instruction_video_invalid_qayta_soraydi():
    msg = FakeMessage(user_id=1, text="matn yubordim")
    asyncio.run(instruction_handlers.instruction_video_invalid(msg))
    assert "video" in msg.answers[-1][0].lower()


def test_instruction_ask_text_state_ozgaradi(monkeypatch):
    monkeypatch.setattr(instruction_handlers, "_is_admin", lambda tg_id: tg_id == 1)
    cb = FakeCallback("instr|text", user_id=1)
    state = FakeState()
    asyncio.run(instruction_handlers.instruction_ask_text(cb, state))
    assert state.state == InstructionFlow.waiting_text


def test_instruction_text_received_saqlaydi(monkeypatch):
    captured = {}

    async def _save(session, text):
        captured["text"] = text

    monkeypatch.setattr(instruction_handlers, "save_instruction_text", _save)

    msg = FakeMessage(user_id=1, text="  Botdan foydalanish tartibi  ")
    state = FakeState(InstructionFlow.waiting_text)
    asyncio.run(instruction_handlers.instruction_text_received(msg, state, FakeSession()))

    assert captured["text"] == "Botdan foydalanish tartibi"
    assert state.state is None
    assert "saqlandi" in msg.answers[-1][0].lower()


def test_instruction_view_admin_emas(monkeypatch):
    monkeypatch.setattr(instruction_handlers, "_is_admin", lambda tg_id: tg_id == 999)
    cb = FakeCallback("instr|view", user_id=1)
    asyncio.run(instruction_handlers.instruction_view(cb, FakeSession()))
    assert cb.answered[-1][1] is True


def test_instruction_view_video_va_matn_ikkalasi_ham(monkeypatch):
    monkeypatch.setattr(instruction_handlers, "_is_admin", lambda tg_id: tg_id == 1)

    async def _get(session):
        return {"video_file_id": "VID1", "text": "Matn shu"}

    monkeypatch.setattr(instruction_handlers, "get_instruction", _get)

    cb = FakeCallback("instr|view", user_id=1)
    asyncio.run(instruction_handlers.instruction_view(cb, FakeSession()))

    assert cb.message.videos == ["VID1"]
    assert cb.message.answers[-1][0] == "Matn shu"


def test_instruction_view_hech_narsa_yoq(monkeypatch):
    monkeypatch.setattr(instruction_handlers, "_is_admin", lambda tg_id: tg_id == 1)

    async def _get(session):
        return {"video_file_id": None, "text": None}

    monkeypatch.setattr(instruction_handlers, "get_instruction", _get)

    cb = FakeCallback("instr|view", user_id=1)
    asyncio.run(instruction_handlers.instruction_view(cb, FakeSession()))

    assert cb.message.videos == []
    assert "sozlanmagan" in cb.message.answers[-1][0].lower()


# ---------------------------------------------------------------------------
# 6.2 — Foydalanuvchi: asosiy menyudan «📖 Instruksiya»
# ---------------------------------------------------------------------------

def test_instruction_user_view_bor(monkeypatch):
    async def _get(session):
        return {"video_file_id": "VID1", "text": "Matn"}

    monkeypatch.setattr(instruction_handlers, "get_instruction", _get)

    msg = FakeMessage(user_id=5)
    asyncio.run(instruction_handlers.instruction_user_view(msg, FakeSession()))

    assert msg.videos == ["VID1"]
    assert msg.answers[-1][0] == "Matn"


def test_instruction_user_view_yoq(monkeypatch):
    async def _get(session):
        return {"video_file_id": None, "text": None}

    monkeypatch.setattr(instruction_handlers, "get_instruction", _get)

    msg = FakeMessage(user_id=5)
    asyncio.run(instruction_handlers.instruction_user_view(msg, FakeSession()))

    assert msg.videos == []
    assert "mavjud emas" in msg.answers[-1][0].lower()


# ---------------------------------------------------------------------------
# 6.2 — /start: yangi user uchun instruksiya, mavjud user uchun yo'q
# ---------------------------------------------------------------------------

def test_cmd_start_yangi_user_instruksiya_yoq_togridan_rol(monkeypatch):
    async def _get_or_none(session, tg_id):
        return None

    async def _get_instruction(session):
        return {"video_file_id": None, "text": None}

    monkeypatch.setattr(start_handlers, "get_or_none", _get_or_none)
    monkeypatch.setattr(start_handlers, "get_instruction", _get_instruction)

    msg = FakeMessage(user_id=7)
    state = FakeState()
    asyncio.run(start_handlers.cmd_start(msg, FakeSession(), state))

    assert msg.videos == []
    text, markup = msg.answers[-1]
    assert "Ro'lni tanlang" in text
    assert _reply_texts(markup) == ["🚛 Haydovchi", "📦 Yuk beruvchi"]


def test_cmd_start_yangi_user_instruksiya_video_va_matn(monkeypatch):
    async def _get_or_none(session, tg_id):
        return None

    async def _get_instruction(session):
        return {"video_file_id": "VID1", "text": "Botdan qanday foydalanish"}

    monkeypatch.setattr(start_handlers, "get_or_none", _get_or_none)
    monkeypatch.setattr(start_handlers, "get_instruction", _get_instruction)

    msg = FakeMessage(user_id=8)
    state = FakeState()
    asyncio.run(start_handlers.cmd_start(msg, FakeSession(), state))

    assert msg.videos == ["VID1"]
    # matn + ack-tugmali xabar — ikkalasi ham answer() orqali
    texts = [a[0] for a in msg.answers]
    assert "Botdan qanday foydalanish" in texts
    last_text, last_markup = msg.answers[-1]
    datas = _cb_datas(last_markup)
    assert "instr|seen" in datas
    assert "instr|later" in datas
    # rol tanlash hali ko'rsatilmagan
    assert "Ro'lni tanlang" not in last_text


def test_cmd_start_yangi_user_faqat_video(monkeypatch):
    async def _get_or_none(session, tg_id):
        return None

    async def _get_instruction(session):
        return {"video_file_id": "VID1", "text": None}

    monkeypatch.setattr(start_handlers, "get_or_none", _get_or_none)
    monkeypatch.setattr(start_handlers, "get_instruction", _get_instruction)

    msg = FakeMessage(user_id=9)
    state = FakeState()
    asyncio.run(start_handlers.cmd_start(msg, FakeSession(), state))

    assert msg.videos == ["VID1"]
    # faqat 1 ta answer() bo'lishi kerak — ack tugmalari (matn yo'q)
    assert len(msg.answers) == 1
    datas = _cb_datas(msg.answers[-1][1])
    assert "instr|seen" in datas and "instr|later" in datas


def test_cmd_start_mavjud_user_instruksiya_korsatilmaydi(monkeypatch):
    user = SimpleNamespace(role=UserRole.driver)

    async def _get_or_none(session, tg_id):
        return user

    async def _get_instruction_should_not_be_called(session):
        raise AssertionError("get_instruction chaqirilmasligi kerak — mavjud user")

    monkeypatch.setattr(start_handlers, "get_or_none", _get_or_none)
    monkeypatch.setattr(start_handlers, "get_instruction", _get_instruction_should_not_be_called)

    msg = FakeMessage(user_id=10)
    state = FakeState()
    asyncio.run(start_handlers.cmd_start(msg, FakeSession(), state))

    assert msg.videos == []
    text, markup = msg.answers[-1]
    assert text == "Asosiy menyu:"


def test_instruction_ack_seen_rol_tanlashga_otadi():
    cb = FakeCallback("instr|seen", user_id=11)
    asyncio.run(start_handlers.instruction_ack(cb))
    assert cb.message.markup_edits == [None]
    text, markup = cb.message.answers[-1]
    assert "Ro'lni tanlang" in text
    assert _reply_texts(markup) == ["🚛 Haydovchi", "📦 Yuk beruvchi"]


def test_instruction_ack_later_ham_rol_tanlashga_otadi():
    cb = FakeCallback("instr|later", user_id=12)
    asyncio.run(start_handlers.instruction_ack(cb))
    text, markup = cb.message.answers[-1]
    assert "Ro'lni tanlang" in text
    assert _reply_texts(markup) == ["🚛 Haydovchi", "📦 Yuk beruvchi"]


# ---------------------------------------------------------------------------
# Callback_data prefiksi mavjudlar bilan to'qnashmasligi (spec talabi)
# ---------------------------------------------------------------------------

def test_instr_prefiks_mavjud_prefikslar_bilan_toqnashmaydi():
    existing_prefixes = (
        "region_", "veh|", "dst|", "more|", "bk|", "take_", "takeyes_",
        "takeno_", "score_", "rate_deal_", "cargo_", "delivered_",
        "cancel_load_", "prego_", "predst_", "notify_", "confirm_",
        "remind_enable", "toggle_notify", "change_role", "roleswitch|",
        "approve_", "reject_", "ulist|", "bcast|",
    )
    sample_datas = ("instr|video", "instr|text", "instr|view", "instr|seen", "instr|later")
    for data in sample_datas:
        assert not any(data.startswith(p) for p in existing_prefixes)
