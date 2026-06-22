from __future__ import annotations

from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.types import Message

router = Router(name="fallback")


@router.message(StateFilter(None))
async def unknown_message(message: Message) -> None:
    """Eng oxirgi catch-all — boshqa hamma handler ishlamasa, shu tushadi.
    DIQQAT: bu router `main.py` da eng oxirida `include_router` qilinishi shart.
    """
    await message.answer(
        "Tushunarsiz buyruq.\n\n"
        "Asosiy menyuni ochish uchun /start buyrug'ini yuboring."
    )
