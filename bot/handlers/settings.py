from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import role_choice_kb
from bot.services.user_service import (
    get_active_subscription,
    get_or_none,
    is_subscribed,
)
from db.models import UserRole

router = Router(name="settings")

_ROLE_LABELS = {
    UserRole.driver: "🚛 Haydovchi",
    UserRole.cargo_provider: "📦 Yuk beruvchi",
    UserRole.asset_owner: "🏭 Asset egasi",
    UserRole.staff_driver: "👤 Mashinasiz haydovchi",
    UserRole.admin: "👨‍💼 Admin",
}

_DRIVER_ROLES = {UserRole.driver, UserRole.asset_owner, UserRole.staff_driver}


def _profile_kb(user) -> InlineKeyboardMarkup:
    rows = []
    if user.role in _DRIVER_ROLES:
        label = "🔕 Xabarnomani o'chirish" if user.notify_enabled else "🔔 Xabarnomani yoqish"
        rows.append([InlineKeyboardButton(text=label, callback_data="toggle_notify")])
    rows.append([InlineKeyboardButton(text="🔄 Rolni o'zgartirish", callback_data="change_role")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "⚙️ Sozlamalar")
async def show_profile(message: Message, session: AsyncSession) -> None:
    user = await get_or_none(session, message.from_user.id)
    if not user:
        await message.answer("Avval /start buyrug'ini yuboring.")
        return

    role_label = _ROLE_LABELS.get(user.role, user.role.value)
    rating = f"{user.rating:.1f}" if user.rating is not None else "—"
    phone = user.phone or "—"

    if await is_subscribed(session, user):
        sub = await get_active_subscription(session, user)
        if sub:
            sub_line = (
                f"✅ Faol — {sub.plan.value.title()} "
                f"(tugashi: {sub.end_date.strftime('%d.%m.%Y')})"
            )
        else:
            sub_line = "✅ Faol"
    else:
        sub_line = "❌ Faol emas"

    notify_line = ""
    if user.role in _DRIVER_ROLES:
        notify_line = (
            f"\n🔔 Xabarnoma: {'yoniq' if user.notify_enabled else 'o‘chiq'}"
        )

    await message.answer(
        "⚙️ <b>Mening profilim</b>\n\n"
        f"👤 Ism: {user.full_name}\n"
        f"📞 Telefon: {phone}\n"
        f"🎭 Rol: {role_label}\n"
        f"⭐ Reyting: {rating}\n"
        f"💳 Obuna: {sub_line}"
        f"{notify_line}\n"
        f"🆔 Telegram ID: <code>{user.telegram_id}</code>",
        reply_markup=_profile_kb(user),
    )


@router.callback_query(F.data == "remind_enable")
async def remind_enable(callback: CallbackQuery, session: AsyncSession) -> None:
    """Kunlik eslatmadagi «🔔 Xabarnomani yoqish» tugmasi."""
    user = await get_or_none(session, callback.from_user.id)
    if not user:
        await callback.answer("Avval /start bosing.", show_alert=True)
        return
    if not user.notify_enabled:
        user.notify_enabled = True
        await session.commit()
    # Tugmani "✅ Yoqildi" holatiga o'zgartiramiz — vizual tasdiq.
    await callback.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Xabarnoma yoqildi", callback_data="notify_noop")
        ]])
    )
    # Tepada bir marta yonib o'chadigan ogohlantirish (modal emas — toast).
    await callback.answer("🔔 Xabarnoma yondi")


@router.callback_query(F.data == "notify_noop")
async def notify_noop(callback: CallbackQuery) -> None:
    """Allaqachon yoqilgan tugma — qayta bosilsa faqat qisqa eslatma."""
    await callback.answer("🔔 Xabarnoma allaqachon yoqilgan")


@router.callback_query(F.data == "notify_off")
async def notify_off(callback: CallbackQuery, session: AsyncSession) -> None:
    """Xabarnoma xabaridagi «🔕 Xabarnomani o'chirish» tugmasi."""
    user = await get_or_none(session, callback.from_user.id)
    if not user:
        await callback.answer("Avval /start bosing.", show_alert=True)
        return
    if user.notify_enabled:
        user.notify_enabled = False
        await session.commit()
    # Tugmalarni "qayta yoqish" holatiga o'zgartiramiz — foydalanuvchi
    # fikridan qaytsa, bir bosishda tiklay olsin.
    await callback.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔔 Xabarnomani qayta yoqish", callback_data="remind_enable")
        ]])
    )
    await callback.answer("🔕 Xabarnoma o'chirildi", show_alert=True)


@router.callback_query(F.data == "toggle_notify")
async def toggle_notify(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_or_none(session, callback.from_user.id)
    if not user:
        await callback.answer("Avval /start bosing.", show_alert=True)
        return
    user.notify_enabled = not user.notify_enabled
    await session.commit()
    await callback.message.edit_reply_markup(reply_markup=_profile_kb(user))
    await callback.answer(
        "🔔 Xabarnoma yondi" if user.notify_enabled else "🔕 Xabarnoma o'chdi"
    )


# ---------------------------------------------------------------------------
# 🔄 Rolni o'zgartirish — adashib boshqa rol tanlaganlar uchun
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "change_role")
async def change_role_start(callback: CallbackQuery, state: FSMContext) -> None:
    # Haqiqiy FSM state o'rnatilmaydi (None qoladi) — shu bilan mavjud
    # ro'yxatdan o'tish oqimi (role_chosen, StateFilter(None)) qayta ishlaydi.
    # "reregister" belgisi state ma'lumotida saqlanib, oxirida yangi user
    # yaratish o'rniga mavjudini yangilash uchun ishlatiladi.
    await state.update_data(reregister=True)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "🔄 <b>Rolni o'zgartirish</b>\n\nYangi rolingizni tanlang:",
        reply_markup=role_choice_kb(),
    )
    await callback.answer()
