from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.admin import _is_admin
from bot.services.user_service import count_users_by_viloyat, list_users
from bot.states import BroadcastFlow
from db.models import User

router = Router(name="admin_broadcast")

log = logging.getLogger(__name__)

_PAGE_SIZE = 10
# Sekundiga ~20 xabar — flood limitdan saqlanish uchun har xabardan keyin kutish.
_SEND_DELAY = 0.05

_ROLE_GROUP_LABELS = {
    "driver": "🚛 Haydovchilar",
    "cargo_provider": "📦 Yuk beruvchilar",
}


# ---------------------------------------------------------------------------
# Guruh a'zolarini olish — mavjud list_users() dan foydalanadi (Faza 4.2),
# rol/viloyat filtrini shu yerda birlashtiradi.
# ---------------------------------------------------------------------------

async def _fetch_group_members(
    session: AsyncSession, group_type: Optional[str], group_value: Optional[str]
) -> list[User]:
    """Guruhning BARCHA a'zolarini qaytaradi (sahifalash checklist ichida, Python'da)."""
    role_filter = group_value if group_type == "role" else None
    viloyat_filter = group_value if group_type == "viloyat" else None
    users, _ = await list_users(
        session, role_filter=role_filter, viloyat_filter=viloyat_filter,
        offset=0, limit=1_000_000,
    )
    return users


async def _resolve_recipient_ids(session: AsyncSession, data: dict) -> list[int]:
    """FSM state'dagi tanlovga qarab yakuniy telegram_id ro'yxatini qaytaradi.

    target_type == "all" — barcha userlar (checklist yo'q).
    target_type == "group" — guruh a'zolari, `excluded_ids`dagilar chiqarib
    tashlanadi (checklist orqali admin belgilagan).
    """
    if data.get("target_type") == "all":
        users, _ = await list_users(session, offset=0, limit=1_000_000)
        return [u.telegram_id for u in users]

    members = await _fetch_group_members(session, data.get("group_type"), data.get("group_value"))
    excluded = set(data.get("excluded_ids") or [])
    return [u.telegram_id for u in members if u.telegram_id not in excluded]


# ---------------------------------------------------------------------------
# Klaviaturalar
# ---------------------------------------------------------------------------

def _target_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Barchaga", callback_data="bcast|all")],
        [InlineKeyboardButton(text="🎯 Guruh bo'yicha", callback_data="bcast|group")],
    ])


def _group_choice_kb(viloyats_with_counts: list[tuple[str, int]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"bcast|role|{key}")]
        for key, label in _ROLE_GROUP_LABELS.items()
    ]
    rows += [
        [InlineKeyboardButton(
            text=f"{v} ({count})" if count else v,
            callback_data=f"bcast|vil|{v}",
        )]
        for v, count in viloyats_with_counts
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _checklist_kb(
    page: list[User], excluded: set[int], offset: int, has_more: bool, total_selected: int,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{'⬜️' if u.telegram_id in excluded else '☑️'} {u.full_name}",
            callback_data=f"bcast|tgl|{u.telegram_id}|{offset}",
        )]
        for u in page
    ]

    pager_row = []
    if offset > 0:
        pager_row.append(InlineKeyboardButton(
            text="◀️ Oldingi", callback_data=f"bcast|pg|{max(0, offset - _PAGE_SIZE)}",
        ))
    if has_more:
        pager_row.append(InlineKeyboardButton(
            text="Keyingi ▶️", callback_data=f"bcast|pg|{offset + _PAGE_SIZE}",
        ))
    if pager_row:
        rows.append(pager_row)

    rows.append([InlineKeyboardButton(
        text=f"✅ Davom etish ({total_selected} ta qabul qiluvchi)",
        callback_data="bcast|cont",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yuborish", callback_data="bcast|send"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="bcast|cancel"),
    ]])


# ---------------------------------------------------------------------------
# 1. Qabul qiluvchi turi
# ---------------------------------------------------------------------------

@router.message(F.text == "📢 Xabarnoma")
async def broadcast_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return

    await state.set_state(BroadcastFlow.waiting_target)
    await state.update_data(excluded_ids=[])
    await message.answer(
        "📢 <b>Xabarnoma</b>\n\nKimga yuborilsin?",
        reply_markup=_target_type_kb(),
    )


@router.callback_query(BroadcastFlow.waiting_target, F.data == "bcast|all")
async def broadcast_target_all(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(target_type="all")
    await state.set_state(BroadcastFlow.waiting_content)
    await callback.message.edit_text(
        "👥 Barchaga yuboriladi.\n\n"
        "Matn yoki media (rasm/video/hujjat, izoh bilan) yuboring:"
    )
    await callback.answer()


@router.callback_query(BroadcastFlow.waiting_target, F.data == "bcast|group")
async def broadcast_target_group(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await state.update_data(target_type="group")
    await state.set_state(BroadcastFlow.waiting_group_choice)
    viloyats = await count_users_by_viloyat(session)
    await callback.message.edit_text(
        "🎯 Guruhni tanlang (rol yoki viloyat):",
        reply_markup=_group_choice_kb(viloyats),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 2. Guruh tanlash (rol / viloyat) → checklist
# ---------------------------------------------------------------------------

async def _render_checklist(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, offset: int
) -> None:
    data = await state.get_data()
    members = await _fetch_group_members(session, data.get("group_type"), data.get("group_value"))
    excluded = set(data.get("excluded_ids") or [])

    page = members[offset:offset + _PAGE_SIZE]
    has_more = len(members) > offset + _PAGE_SIZE
    total_selected = len([u for u in members if u.telegram_id not in excluded])

    if not page:
        text = "🎯 <b>Guruh</b>\n\nBu guruhda hech kim topilmadi."
    else:
        start, end = offset + 1, offset + len(page)
        text = (
            f"🎯 <b>Guruh a'zolari</b> ({start}–{end} / {len(members)}):\n\n"
            "Kerak bo'lmaganlarni bosib chiqarib tashlang."
        )

    kb = _checklist_kb(page, excluded, offset, has_more, total_selected)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramAPIError:
        await callback.message.answer(text, reply_markup=kb)


@router.callback_query(BroadcastFlow.waiting_group_choice, F.data.startswith("bcast|role|"))
async def broadcast_group_role(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    role_key = callback.data.split("|", 2)[2]
    await state.update_data(group_type="role", group_value=role_key, excluded_ids=[])
    await state.set_state(BroadcastFlow.waiting_checklist)
    await _render_checklist(callback, state, session, offset=0)
    await callback.answer()


@router.callback_query(BroadcastFlow.waiting_group_choice, F.data.startswith("bcast|vil|"))
async def broadcast_group_viloyat(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    viloyat = callback.data.split("|", 2)[2]
    await state.update_data(group_type="viloyat", group_value=viloyat, excluded_ids=[])
    await state.set_state(BroadcastFlow.waiting_checklist)
    await _render_checklist(callback, state, session, offset=0)
    await callback.answer()


# ---------------------------------------------------------------------------
# 3. Checklist: sahifalash + ☑️/⬜️ toggle
# ---------------------------------------------------------------------------

@router.callback_query(BroadcastFlow.waiting_checklist, F.data.startswith("bcast|pg|"))
async def broadcast_checklist_page(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    offset = int(callback.data.split("|")[2])
    await _render_checklist(callback, state, session, offset)
    await callback.answer()


@router.callback_query(BroadcastFlow.waiting_checklist, F.data.startswith("bcast|tgl|"))
async def broadcast_checklist_toggle(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    _, _, tg_id_str, offset_str = callback.data.split("|")
    tg_id = int(tg_id_str)
    offset = int(offset_str)

    data = await state.get_data()
    excluded = set(data.get("excluded_ids") or [])
    if tg_id in excluded:
        excluded.discard(tg_id)
    else:
        excluded.add(tg_id)
    await state.update_data(excluded_ids=list(excluded))

    await _render_checklist(callback, state, session, offset)
    await callback.answer()


@router.callback_query(BroadcastFlow.waiting_checklist, F.data == "bcast|cont")
async def broadcast_checklist_continue(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    recipient_ids = await _resolve_recipient_ids(session, data)
    if not recipient_ids:
        await callback.answer("Hech kim tanlanmagan.", show_alert=True)
        return

    await state.set_state(BroadcastFlow.waiting_content)
    await callback.message.edit_text(
        f"✅ {len(recipient_ids)} ta qabul qiluvchi tanlandi.\n\n"
        "Matn yoki media (rasm/video/hujjat, izoh bilan) yuboring:"
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 4. Kontent — matn yoki media (bitta xabar, keyinroq copy_message bilan
#    hammaga yuboriladi — manba ko'rinmasin uchun forward emas).
# ---------------------------------------------------------------------------

@router.message(BroadcastFlow.waiting_content)
async def broadcast_content_received(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    await state.update_data(
        content_chat_id=message.chat.id,
        content_message_id=message.message_id,
    )
    data = await state.get_data()
    recipient_ids = await _resolve_recipient_ids(session, data)

    await state.set_state(BroadcastFlow.waiting_confirm)

    # Preview — adminning o'ziga bir marta copy_message bilan ko'rsatiladi.
    await bot.copy_message(
        chat_id=message.chat.id,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )
    await message.answer(
        f"👆 Preview shu ko'rinishda ketadi.\n\n"
        f"<b>{len(recipient_ids)}</b> ta qabul qiluvchiga yuboriladi. Tasdiqlaysizmi?",
        reply_markup=_confirm_kb(),
    )


# ---------------------------------------------------------------------------
# 5. Yuborish
# ---------------------------------------------------------------------------

@router.callback_query(BroadcastFlow.waiting_confirm, F.data == "bcast|cancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Xabarnoma bekor qilindi.")
    await callback.answer()


@router.callback_query(BroadcastFlow.waiting_confirm, F.data == "bcast|send")
async def broadcast_send(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    data = await state.get_data()
    recipient_ids = await _resolve_recipient_ids(session, data)
    content_chat_id = data.get("content_chat_id")
    content_message_id = data.get("content_message_id")

    await callback.answer()
    await callback.message.edit_text(f"⏳ Yuborilmoqda... (jami {len(recipient_ids)} ta)")

    sent = 0
    blocked = 0
    errors = 0
    for tg_id in recipient_ids:
        try:
            await bot.copy_message(
                chat_id=tg_id,
                from_chat_id=content_chat_id,
                message_id=content_message_id,
            )
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
        except TelegramAPIError:
            errors += 1
            log.warning("Broadcast: %s ga yuborilmadi (xato)", tg_id)
        await asyncio.sleep(_SEND_DELAY)

    await state.clear()
    await callback.message.answer(
        "📊 <b>Xabarnoma hisoboti</b>\n\n"
        f"Jami: {len(recipient_ids)}\n"
        f"✅ Yuborildi: {sent}\n"
        f"🚫 Bloklagan: {blocked}\n"
        f"⚠️ Xato: {errors}"
    )
