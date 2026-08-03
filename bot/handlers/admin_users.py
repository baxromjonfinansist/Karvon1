from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.handlers.admin import _ROLE_LABELS, _is_admin
from bot.services.user_service import list_users
from db.models import User

router = Router(name="admin_users")

log = logging.getLogger(__name__)

_PAGE_SIZE = 10

_VEHICLE_LABELS = {
    "isuzu": "Isuzu",
    "fura": "Fura",
    "kichik": "Kichik (Porter/Labo)",
    "other": "Boshqa",
}

_FILTER_BUTTON_LABELS = {
    "all": "Barchasi",
    "driver": "🚛 Haydovchilar",
    "cargo_provider": "📦 Yuk beruvchilar",
}


# ---------------------------------------------------------------------------
# 4.1 — Yangi user ro'yxatdan o'tganda barcha adminlarga xabar
# ---------------------------------------------------------------------------

def _fmt_capacity(capacity_t) -> str:
    val = float(capacity_t)
    if val == int(val):
        return f"{int(val)} t"
    return f"{val:g} t"


async def notify_admins_new_user(bot: Bot, user: User) -> None:
    """Ro'yxatdan o'tish tugagach barcha adminlarga xabar (Faza 4.1).

    Bitta admin bloklagan/xato bo'lsa — faqat log, boshqa adminlarga
    yuborish davom etadi va chaqiruvchi (start.py) oqim uzilmaydi.
    """
    role_value = user.role.value if hasattr(user.role, "value") else user.role
    role_label = _ROLE_LABELS.get(role_value, str(role_value))

    lines = [
        "🆕 Yangi foydalanuvchi",
        f"Ism: {user.full_name}",
        f"Tel: {user.phone or '—'}",
        f"Rol: {role_label}",
    ]

    vehicle_type = getattr(user, "vehicle_type", None)
    if vehicle_type is not None:
        veh_value = vehicle_type.value if hasattr(vehicle_type, "value") else vehicle_type
        veh_label = _VEHICLE_LABELS.get(veh_value, str(veh_value))
        capacity_t = getattr(user, "capacity_t", None)
        cap_text = f", {_fmt_capacity(capacity_t)}" if capacity_t is not None else ""
        lines.append(f"Mashina: {veh_label}{cap_text}")

    text = "\n".join(lines)

    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError:
            log.warning("Yangi user xabari admin %s ga yetmadi (bloklagan/xato)", admin_id)


# ---------------------------------------------------------------------------
# 4.2 — Userlar ro'yxati: sahifalash + filtr
# ---------------------------------------------------------------------------

def _fmt_user_card(user: User) -> str:
    role_value = user.role.value if hasattr(user.role, "value") else user.role
    role_label = _ROLE_LABELS.get(role_value, str(role_value))

    lines = [
        f"👤 <b>{user.full_name}</b>",
        f"📞 {user.phone or '—'}",
        f"Rol: {role_label}",
    ]

    vehicle_type = getattr(user, "vehicle_type", None)
    if vehicle_type is not None:
        veh_value = vehicle_type.value if hasattr(vehicle_type, "value") else vehicle_type
        veh_label = _VEHICLE_LABELS.get(veh_value, str(veh_value))
        capacity_t = getattr(user, "capacity_t", None)
        cap_text = f", {_fmt_capacity(capacity_t)}" if capacity_t is not None else ""
        lines.append(f"🚚 {veh_label}{cap_text}")

    created_at = getattr(user, "created_at", None)
    created_text = created_at.strftime("%d.%m.%Y") if created_at else "—"
    lines.append(f"📅 {created_text}")

    return "\n".join(lines)


def _users_list_kb(role_filter: str, offset: int, has_more: bool) -> InlineKeyboardMarkup:
    filter_row = [
        InlineKeyboardButton(
            text=(f"• {label}" if key == role_filter else label),
            callback_data=f"ulist|{key}|0",
        )
        for key, label in _FILTER_BUTTON_LABELS.items()
    ]
    rows = [filter_row]

    pager_row = []
    if offset > 0:
        pager_row.append(InlineKeyboardButton(
            text="◀️ Oldingi",
            callback_data=f"ulist|{role_filter}|{max(0, offset - _PAGE_SIZE)}",
        ))
    if has_more:
        pager_row.append(InlineKeyboardButton(
            text="Keyingi ▶️",
            callback_data=f"ulist|{role_filter}|{offset + _PAGE_SIZE}",
        ))
    if pager_row:
        rows.append(pager_row)

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_users_page(
    session: AsyncSession, role_filter: str, offset: int
) -> tuple[str, InlineKeyboardMarkup]:
    users, has_more = await list_users(
        session, role_filter=role_filter, offset=offset, limit=_PAGE_SIZE
    )

    if not users:
        text = "📇 <b>Userlar ro'yxati</b>\n\nHech kim topilmadi."
    else:
        start, end = offset + 1, offset + len(users)
        cards = "\n\n".join(_fmt_user_card(u) for u in users)
        text = f"📇 <b>Userlar ro'yxati</b> ({start}–{end}):\n\n{cards}"

    return text, _users_list_kb(role_filter, offset, has_more)


@router.message(F.text == "📇 Userlar ro'yxati")
async def users_list_menu(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    text, kb = await _render_users_page(session, "all", 0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("ulist|"))
async def users_list_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    _, role_filter, offset_str = callback.data.split("|")
    offset = int(offset_str)

    text, kb = await _render_users_page(session, role_filter, offset)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramAPIError:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()
