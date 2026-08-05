"""_is_first_time_phone — "1-qo'l" ishonch yorlig'i uchun sof tekshiruv."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from bot.services.parser_service import _is_first_time_phone  # noqa: E402


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeSession:
    """execute() — oldindan berilgan bitta natijani qaytaradi (query e'tiborsiz)."""

    def __init__(self, existing_id):
        self._result = _Result(existing_id)

    async def execute(self, query):
        return self._result


def test_no_prior_load_is_first_time():
    session = _FakeSession(existing_id=None)   # hech narsa topilmadi
    assert asyncio.run(_is_first_time_phone(session, "+998901112233")) is True


def test_existing_load_is_not_first_time():
    session = _FakeSession(existing_id=42)     # boshqa yozuv bor
    assert asyncio.run(_is_first_time_phone(session, "+998901112233")) is False


def test_empty_phone_is_treated_as_first_time():
    """Telefon bo'lmasa (nazariy holat) — DB'ga so'rov yuborilmasdan True."""
    session = _FakeSession(existing_id=999)  # chaqirilmasligi kerak bo'lgan natija
    assert asyncio.run(_is_first_time_phone(session, None)) is True
