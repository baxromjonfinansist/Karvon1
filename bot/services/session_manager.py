from __future__ import annotations

import os
from pathlib import Path

SESSION_DIR = Path("data")
DEFAULT_SESSION_NAME = "telethon_session"
SESSION_PATH = SESSION_DIR / DEFAULT_SESSION_NAME   # eski nom bilan moslik

# MUHIM: bitta sessiya faylini ikki joyda (masalan lokal kompyuter va server)
# bir vaqtda ishlatish Telegram tomonidan taqiqlangan — auth key BUTUNLAY
# bekor qilinadi (AuthKeyDuplicatedError) va reader yuk o'qishni to'xtatadi.
# Shu sabab diagnostika/yordamchi skriptlar alohida sessiya nomi bilan ishlaydi:
#     TELETHON_SESSION_NAME=diag_session python3 scripts/diag_reader.py
ENV_SESSION_NAME = "TELETHON_SESSION_NAME"
HELPER_SESSION_NAME = "helper_session"   # yordamchi skriptlar uchun


def get_session_path(name: str | None = None) -> str:
    """Sessiya fayli yo'li (data/ papkasi yaratiladi).

    Nom tanlash tartibi: aniq berilgan `name` > $TELETHON_SESSION_NAME >
    `telethon_session` (bot reader'ining asosiy sessiyasi).
    """
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    session_name = name or os.getenv(ENV_SESSION_NAME) or DEFAULT_SESSION_NAME
    return str(SESSION_DIR / session_name)


def get_script_session_path() -> str:
    """Yordamchi skriptlar uchun sessiya — botning sessiyasidan ALOHIDA.

    Bot ishlab turgan paytda skript ishga tushirilsa, bitta auth key ikki
    joyda ishlatilgan bo'ladi va Telegram uni bekor qiladi — reader o'ladi.
    Shu sabab skriptlar `helper_session` (yoki $TELETHON_SESSION_NAME) dan
    foydalanadi va bir marta alohida login qiladi.
    """
    return get_session_path(os.getenv(ENV_SESSION_NAME) or HELPER_SESSION_NAME)
