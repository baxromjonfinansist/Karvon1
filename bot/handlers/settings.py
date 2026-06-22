from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

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

    await message.answer(
        "⚙️ <b>Mening profilim</b>\n\n"
        f"👤 Ism: {user.full_name}\n"
        f"📞 Telefon: {phone}\n"
        f"🎭 Rol: {role_label}\n"
        f"⭐ Reyting: {rating}\n"
        f"💳 Obuna: {sub_line}\n"
        f"🆔 Telegram ID: <code>{user.telegram_id}</code>"
    )
