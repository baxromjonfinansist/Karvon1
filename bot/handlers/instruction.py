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

from bot.handlers.admin import _is_admin
from bot.services.settings_service import (
    get_instruction,
    save_instruction_text,
    save_instruction_video,
)
from bot.states import InstructionFlow

router = Router(name="instruction")


def _instruction_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📹 Video yuklash", callback_data="instr|video")],
        [InlineKeyboardButton(text="📝 Matn", callback_data="instr|text")],
        [InlineKeyboardButton(text="👁 Ko'rish", callback_data="instr|view")],
    ])


async def _send_instruction(message: Message, session: AsyncSession) -> bool:
    """Hozirgi video+matnni yuboradi. Hech narsa sozlanmagan bo'lsa False."""
    data = await get_instruction(session)
    sent = False
    if data["video_file_id"]:
        await message.answer_video(data["video_file_id"])
        sent = True
    if data["text"]:
        await message.answer(data["text"])
        sent = True
    return sent


# ---------------------------------------------------------------------------
# 6.1 — Admin: 🎬 Instruksiya bo'limi
# ---------------------------------------------------------------------------

@router.message(F.text == "🎬 Instruksiya")
async def instruction_menu(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(
        "🎬 <b>Instruksiya</b>\n\nBo'limni tanlang:",
        reply_markup=_instruction_menu_kb(),
    )


@router.callback_query(F.data == "instr|video")
async def instruction_ask_video(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await state.set_state(InstructionFlow.waiting_video)
    await callback.message.edit_text("📹 Instruksiya videosini yuboring:")
    await callback.answer()


@router.message(InstructionFlow.waiting_video, F.video)
async def instruction_video_received(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    await save_instruction_video(session, message.video.file_id)
    await state.clear()
    await message.answer("✅ Instruksiya videosi saqlandi.")


@router.message(InstructionFlow.waiting_video)
async def instruction_video_invalid(message: Message) -> None:
    await message.answer("Iltimos, video yuboring.")


@router.callback_query(F.data == "instr|text")
async def instruction_ask_text(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    await state.set_state(InstructionFlow.waiting_text)
    await callback.message.edit_text("📝 Instruksiya matnini yuboring:")
    await callback.answer()


@router.message(InstructionFlow.waiting_text, F.text)
async def instruction_text_received(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    await save_instruction_text(session, message.text.strip())
    await state.clear()
    await message.answer("✅ Instruksiya matni saqlandi.")


@router.callback_query(F.data == "instr|view")
async def instruction_view(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    sent = await _send_instruction(callback.message, session)
    if not sent:
        await callback.message.answer(
            "ℹ️ Hozircha instruksiya sozlanmagan (video ham, matn ham yo'q)."
        )
    await callback.answer()


# ---------------------------------------------------------------------------
# 6.2 — Foydalanuvchi: asosiy menyudan «📖 Instruksiya» — mavjud userlar
# xohlasa qayta ko'rishi uchun (ixtiyoriy tugma, spec 6.2).
# ---------------------------------------------------------------------------

@router.message(F.text == "📖 Instruksiya")
async def instruction_user_view(message: Message, session: AsyncSession) -> None:
    sent = await _send_instruction(message, session)
    if not sent:
        await message.answer("ℹ️ Hozircha instruksiya mavjud emas.")
