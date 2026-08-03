"""Fon siklda eskirgan yuklarni tozalash (Faza 1.1) testlari.

Ishga tushirish:
    python3 -m pytest tests/test_notify_cleanup.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from bot.services import notify_service as ns  # noqa: E402


class _FakeSession:
    """AsyncSessionLocal() o'rniga — DB'siz kontekst menejer."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_tozalash_har_10_daqiqada():
    assert ns.NOTIFY_INTERVAL == 600


def test_cleanup_ochirilgan_sonni_qaytaradi(monkeypatch):
    calls = []

    async def fake_delete(session):
        calls.append(session)
        return 7

    monkeypatch.setattr(ns, "AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(ns, "delete_stale_loads", fake_delete)

    assert asyncio.run(ns.cleanup_stale_loads()) == 7
    assert len(calls) == 1


def test_cleanup_logga_yozadi(monkeypatch, caplog):
    async def fake_delete(session):
        return 42

    monkeypatch.setattr(ns, "AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(ns, "delete_stale_loads", fake_delete)

    with caplog.at_level("INFO"):
        asyncio.run(ns.cleanup_stale_loads())
    assert "42" in caplog.text


def test_notify_loop_har_siklda_tozalaydi(monkeypatch):
    seen = []

    async def fake_sleep(_):
        return None

    async def fake_run_once(bot):
        seen.append("notify")

    async def fake_cleanup():
        seen.append("cleanup")
        ns.stop_notify()   # bitta sikldan keyin to'xtaymiz
        return 0

    monkeypatch.setattr(ns.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(ns, "_run_once", fake_run_once)
    monkeypatch.setattr(ns, "cleanup_stale_loads", fake_cleanup)

    try:
        asyncio.run(ns.notify_loop(None))
    finally:
        ns.stop_notify()

    assert seen == ["notify", "cleanup"]


def test_tozalash_xatosi_siklni_toxtatmaydi(monkeypatch):
    seen = []

    async def fake_sleep(_):
        return None

    async def fake_run_once(bot):
        seen.append("notify")
        if len(seen) >= 3:
            ns.stop_notify()

    async def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(ns.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(ns, "_run_once", fake_run_once)
    monkeypatch.setattr(ns, "cleanup_stale_loads", boom)

    try:
        asyncio.run(ns.notify_loop(None))
    finally:
        ns.stop_notify()

    assert seen.count("notify") == 3   # tozalash yiqilsa ham xabarnoma ishlayveradi


# ---------------------------------------------------------------------------
# Xabarnoma kartasi ham umumiy formatlovchini ishlatadi (1.2)
# ---------------------------------------------------------------------------

def test_xabarnoma_kartasida_yosh_bor():
    load = SimpleNamespace(
        id=1,
        route=SimpleNamespace(origin="Andijon", destination="Toshkent"),
        contact_phone="+998901234567",
        raw_text="",
        note="Paxta",
        cargo_type=None,
        posted_at=datetime.utcnow() - timedelta(hours=2),
    )
    text = ns._fmt(load)
    assert "🔔 <b>Yangi yuk!</b>" in text
    assert "🚚 <b>Andijon → Toshkent</b>" in text
    assert "🕒 2 soat oldin" in text
