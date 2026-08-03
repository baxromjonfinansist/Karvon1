from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)


# Barcha ko'p qadamli oqimlarda bir xil matn ishlatiladi (Faza 2).
BACK_TEXT = "⬅️ Orqaga"

# Telegram callback_data chegarasi — 64 bayt (belgilar emas, baytlar).
CALLBACK_DATA_MAX_BYTES = 64


def back_row(callback_data: str) -> list[InlineKeyboardButton]:
    """Inline menyu uchun bitta «⬅️ Orqaga» tugmali qator.

    callback_data 64 baytdan oshsa — Telegram xatosi o'rniga darhol ValueError
    (xato test bosqichida ushlansin).
    """
    if len(callback_data.encode("utf-8")) > CALLBACK_DATA_MAX_BYTES:
        raise ValueError(
            f"callback_data {CALLBACK_DATA_MAX_BYTES} baytdan oshdi: {callback_data!r}"
        )
    return [InlineKeyboardButton(text=BACK_TEXT, callback_data=callback_data)]


def back_reply_kb(*extra_rows: list[KeyboardButton]) -> ReplyKeyboardMarkup:
    """Matn kutayotgan FSM qadamlari uchun — pastda «⬅️ Orqaga» qatori."""
    keyboard = [list(row) for row in extra_rows]
    keyboard.append([KeyboardButton(text=BACK_TEXT)])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def role_choice_kb(with_back: bool = False) -> ReplyKeyboardMarkup:
    """Rol tanlash. `with_back` — sozlamalardan kelganda profilga qaytish uchun."""
    keyboard = [
        [KeyboardButton(text="🚛 Haydovchi"), KeyboardButton(text="📦 Yuk beruvchi")],
        [KeyboardButton(text="🏭 Asset egasi")],
    ]
    if with_back:
        keyboard.append([KeyboardButton(text=BACK_TEXT)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def vehicle_type_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Isuzu"), KeyboardButton(text="Fura")],
            [KeyboardButton(text="Kichik (Porter/Labo)"), KeyboardButton(text="Boshqa")],
            [KeyboardButton(text=BACK_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def phone_request_kb() -> ReplyKeyboardMarkup:
    return back_reply_kb(
        [KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]
    )


def pref_viloyat_kb(
    viloyats_with_counts, prefix: str, back_data: str | None = None
) -> InlineKeyboardMarkup:
    """Ro'yxatdan o'tishda «eng aktual yo'nalish» tanlash — viloyatlar, yuk soni bilan."""
    buttons = [
        [InlineKeyboardButton(
            text=f"{v} ({count})" if count else v,
            callback_data=f"{prefix}_{v}",
        )]
        for v, count in viloyats_with_counts
    ]
    if back_data:
        buttons.append(back_row(back_data))
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def main_menu_driver_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            # «💳 Obunam» vaqtincha yashirilgan (Faza 1.3) — keyin qaytariladi.
            [KeyboardButton(text="📦 Yuklar")],
            [KeyboardButton(text="📋 Bitimlarim"), KeyboardButton(text="⚙️ Sozlamalar")],
            [KeyboardButton(text="💬 Fikr-mulohaza"), KeyboardButton(text="📞 Murojaat")],
            [KeyboardButton(text="🏠 Asosiy bo'lim")],
        ],
        resize_keyboard=True,
    )


def main_menu_provider_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Yuk joylash"), KeyboardButton(text="📦 Mening yuklarim")],
            [KeyboardButton(text="⚙️ Sozlamalar")],
            [KeyboardButton(text="💬 Fikr-mulohaza"), KeyboardButton(text="📞 Murojaat")],
            [KeyboardButton(text="🏠 Asosiy bo'lim")],
        ],
        resize_keyboard=True,
    )


def confirm_kb(back_data: str | None = None) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="confirm_yes"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="confirm_no"),
    ]]
    if back_data:
        rows.append(back_row(back_data))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
