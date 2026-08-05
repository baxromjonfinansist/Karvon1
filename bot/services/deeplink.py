from __future__ import annotations

from typing import Optional

_bot_username: Optional[str] = None

_LOAD_PREFIX = "load_"


def set_bot_username(username: Optional[str]) -> None:
    """Bot username'ini keshlaydi — `main.py` startup'da bir marta chaqiradi."""
    global _bot_username
    _bot_username = username


def build_load_deeplink(load_id: int) -> str:
    """Yukni ko'rsatuvchi deep-link: `https://t.me/<bot>?start=load_<id>`.

    Bot username hali sozlanmagan bo'lsa (`set_bot_username` chaqirilmagan)
    — xato ko'taradi, jim noto'g'ri link qaytarmaydi.
    """
    if not _bot_username:
        raise RuntimeError(
            "Bot username hali sozlanmagan — set_bot_username() chaqirilmagan."
        )
    return f"https://t.me/{_bot_username}?start={_LOAD_PREFIX}{load_id}"


def parse_load_start_payload(args: Optional[str]) -> Optional[int]:
    """`/start load_42` argumentidan yuk ID sini ajratadi. Mos kelmasa `None`."""
    if not args or not args.startswith(_LOAD_PREFIX):
        return None
    try:
        return int(args[len(_LOAD_PREFIX):])
    except ValueError:
        return None
