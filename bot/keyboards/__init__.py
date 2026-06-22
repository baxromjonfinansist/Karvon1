from __future__ import annotations

from typing import Optional

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from db.models import Route


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
            [KeyboardButton(text="Boshqa"), KeyboardButton(text="⬅️ Orqaga")],
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


def routes_kb(routes: list[Route], selected_ids: Optional[list[int]] = None) -> InlineKeyboardMarkup:
    selected_ids = selected_ids or []
    buttons = []
    for route in routes:
        label = f"{'✅ ' if route.id in selected_ids else ''}{route.origin}→{route.destination}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"route_{route.id}")])
    buttons.append([InlineKeyboardButton(text="✅ Tayyor", callback_data="routes_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def main_menu_driver_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 Yuklar"), KeyboardButton(text="💳 Obunam")],
            [KeyboardButton(text="📋 Bitimlarim"), KeyboardButton(text="⚙️ Sozlamalar")],
        ],
        resize_keyboard=True,
    )


def main_menu_provider_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Yuk joylash"), KeyboardButton(text="📦 Mening yuklarim")],
            [KeyboardButton(text="⚙️ Sozlamalar")],
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
