"""Faza 1.3 — obuna bo'limi foydalanuvchi oqimidan olib tashlandi.

Kod (Subscription modeli, user_service funksiyalari, /grant_sub) saqlanadi —
faqat haydovchi menyusi va gate'lar tekshiriladi.

Ishga tushirish:
    python3 -m pytest tests/test_driver_menu.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from bot.handlers import admin as admin_handlers  # noqa: E402
from bot.handlers import driver as driver_handlers  # noqa: E402
from bot.keyboards import main_menu_driver_kb  # noqa: E402
from bot.services import user_service  # noqa: E402


def _menu_texts() -> list[str]:
    return [btn.text for row in main_menu_driver_kb().keyboard for btn in row]


def test_menyuda_obuna_tugmasi_yoq():
    assert "💳 Obunam" not in _menu_texts()


def test_menyudagi_qolgan_tugmalar_joyida():
    texts = _menu_texts()
    for expected in (
        "📦 Yuklar", "📋 Bitimlarim", "⚙️ Sozlamalar",
        "💬 Fikr-mulohaza", "📞 Murojaat", "🏠 Asosiy bo'lim",
    ):
        assert expected in texts


def test_menyu_qatorlari_bosh_emas():
    kb = main_menu_driver_kb()
    assert all(row for row in kb.keyboard)          # bo'sh qator qolmasin
    assert all(len(row) <= 2 for row in kb.keyboard)


def test_driverda_obuna_gate_yoq():
    src = Path(driver_handlers.__file__).read_text(encoding="utf-8")
    assert "is_subscribed" not in src
    assert "Obuna faol emas" not in src
    assert "💳 Obunam" not in src


def test_obuna_handleri_ochirilgan():
    assert not hasattr(driver_handlers, "show_subscription")


def test_obuna_kodi_saqlangan():
    # Keyingi bosqichda qaytariladi — o'chirilmagani tekshiriladi
    assert hasattr(user_service, "is_subscribed")
    assert hasattr(user_service, "get_active_subscription")
    assert hasattr(user_service, "grant_subscription")
    assert hasattr(admin_handlers, "grant_sub")


def test_driver_kartasi_default_holatda_telefon_yashirin():
    """Standart chaqiruvda (_fmt_load(load)) telefon matnda YO'Q,
    o'rniga ishonch yorlig'i bor — tugma keyingi vazifada qo'shiladi."""
    load = SimpleNamespace(
        id=1,
        route=SimpleNamespace(origin="Toshkent", destination="Samarqand"),
        contact_phone="+998901234567",
        raw_text="",
        note="Paxta",
        cargo_type=None,
        posted_at=datetime.utcnow() - timedelta(minutes=40),
        first_time_phone=True,
    )
    text = driver_handlers._fmt_load(load)
    assert "🕒 40 daqiqa oldin" in text
    assert "+998901234567" not in text
    assert "100% 1-qo'l" in text


def test_driver_kartasi_show_phone_true_bilan_raqam_koradi():
    load = SimpleNamespace(
        id=1,
        route=SimpleNamespace(origin="Toshkent", destination="Samarqand"),
        contact_phone="+998901234567",
        raw_text="",
        note="Paxta",
        cargo_type=None,
        posted_at=datetime.utcnow() - timedelta(minutes=40),
        first_time_phone=False,
    )
    text = driver_handlers._fmt_load(load, show_phone=True)
    assert "📞 +998901234567" in text
    assert "dispetcher" in text.lower() or "logist" in text.lower()


def test_take_kb_load_bilan_qongiroq_tugmasi_qoshadi(monkeypatch):
    # driver.py `build_load_deeplink`ni to'g'ridan-to'g'ri import qilgan
    # (`from ... import ...`), shuning uchun patch shu modul nomiga qo'llanadi —
    # `bot.services.deeplink` ga emas.
    monkeypatch.setattr(
        "bot.handlers.driver.build_load_deeplink",
        lambda load_id: f"https://t.me/TestBot?start=load_{load_id}",
    )
    load = SimpleNamespace(id=7)
    kb = driver_handlers._take_kb(7, load=load)
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert "🤝 Olish" in texts
    assert "📞 Qo'ng'iroq qilish" in texts


def test_take_kb_loadsiz_faqat_olish_tugmasi():
    kb = driver_handlers._take_kb(7)
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert texts == ["🤝 Olish"]
