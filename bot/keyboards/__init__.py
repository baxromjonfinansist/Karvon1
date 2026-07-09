from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)


def role_choice_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚛 Haydovchi"), KeyboardButton(text="📦 Yuk beruvchi")],
            [KeyboardButton(text="🏭 Asset egasi")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def vehicle_type_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Isuzu"), KeyboardButton(text="Fura")],
            [KeyboardButton(text="Kichik (Porter/Labo)"), KeyboardButton(text="Boshqa")],
            [KeyboardButton(text="⬅️ Orqaga")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def phone_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def pref_viloyat_kb(viloyats_with_counts, prefix: str) -> InlineKeyboardMarkup:
    """Ro'yxatdan o'tishda «eng aktual yo'nalish» tanlash — viloyatlar, yuk soni bilan."""
    buttons = [
        [InlineKeyboardButton(
            text=f"{v} ({count})" if count else v,
            callback_data=f"{prefix}_{v}",
        )]
        for v, count in viloyats_with_counts
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def main_menu_driver_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 Yuklar"), KeyboardButton(text="💳 Obunam")],
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


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="confirm_yes"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="confirm_no"),
            ]
        ]
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
