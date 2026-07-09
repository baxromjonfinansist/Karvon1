from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.keyboards import main_menu_driver_kb, main_menu_provider_kb
from bot.services.user_service import get_or_none
from bot.states import FeedbackFlow
from db.models import Feedback, UserRole

router = Router(name="misc")

CONTACT_USERNAME = "@uzz_171"

_DRIVER_ROLES = {UserRole.driver, UserRole.asset_owner, UserRole.staff_driver}


def _main_menu_for(role: UserRole):
    return main_menu_provider_kb() if role == UserRole.cargo_provider else main_menu_driver_kb()


def _cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
    )


# ---------------------------------------------------------------------------
# 🏠 Asosiy bo'lim — istalgan joydan asosiy menyuga qaytaradi (state tozalanadi)
# ---------------------------------------------------------------------------

@router.message(F.text == "🏠 Asosiy bo'lim")
async def go_home(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    user = await get_or_none(session, message.from_user.id)
    if not user:
        await message.answer("Avval /start buyrug'ini yuboring.")
        return
    await message.answer("🏠 Asosiy menyu:", reply_markup=_main_menu_for(user.role))


# ---------------------------------------------------------------------------
# 📞 Murojaat — admin/operator kontakti
# ---------------------------------------------------------------------------

@router.message(F.text == "📞 Murojaat")
async def contact(message: Message) -> None:
    await message.answer(
        "📞 <b>Murojaat uchun</b>\n\n"
        "Savol, taklif yoki muammo bo'lsa — bemalol yozing:\n"
        f"👉 {CONTACT_USERNAME}"
    )


# ---------------------------------------------------------------------------
# 💬 Fikr-mulohaza — foydalanuvchi yozadi, admin panelga ogohlantirish boradi
# ---------------------------------------------------------------------------

@router.message(F.text == "💬 Fikr-mulohaza")
async def feedback_start(message: Message, state: FSMContext) -> None:
    await state.set_state(FeedbackFlow.waiting_text)
    await message.answer(
        "💬 <b>Fikr-mulohaza</b>\n\n"
        "Bot haqidagi fikringiz, taklifingiz yoki shikoyatingizni yozing.\n"
        "Bekor qilish uchun «❌ Bekor qilish» tugmasini bosing:",
        reply_markup=_cancel_kb(),
    )


@router.message(FeedbackFlow.waiting_text, F.text == "❌ Bekor qilish")
async def feedback_cancel(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    user = await get_or_none(session, message.from_user.id)
    kb = _main_menu_for(user.role) if user else None
    await message.answer("Bekor qilindi.", reply_markup=kb)


@router.message(FeedbackFlow.waiting_text, F.text)
async def feedback_save(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    text = message.text.strip()
    await state.clear()

    user = await get_or_none(session, message.from_user.id)
    if user:
        session.add(Feedback(user_id=user.id, text=text))
        await session.commit()

    # Admin panelga ogohlantirish
    if settings.ADMIN_ID:
        who = user.full_name if user else message.from_user.full_name
        phone = f" ({user.phone})" if user and user.phone else ""
        try:
            await bot.send_message(
                settings.ADMIN_ID,
                f"💬 <b>Yangi fikr-mulohaza</b>\n\n"
                f"👤 {who}{phone}\n"
                f"🆔 <code>{message.from_user.id}</code>\n\n"
                f"{text}",
            )
        except TelegramAPIError:
            pass

    kb = _main_menu_for(user.role) if user else None
    await message.answer(
        "✅ Rahmat! Fikringiz qabul qilindi.", reply_markup=kb
    )
