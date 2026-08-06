from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Contact,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.admin_users import notify_admins_new_user
from bot.keyboards import (
    BACK_TEXT,
    back_reply_kb,
    back_row,
    main_menu_driver_kb,
    main_menu_provider_kb,
    phone_request_kb,
    pref_viloyat_kb,
    role_choice_kb,
    vehicle_type_kb,
)
from bot.services.deeplink import parse_load_start_payload
from bot.services.load_service import format_load_card, get_load_detail, get_ranked_viloyats
from bot.services.settings_service import get_instruction
from bot.services.user_service import (
    create_user,
    get_or_none,
    update_user_role,
)
from bot.states import DriverReg, ProviderReg, RoleChange
from db.models import UserRole, VehicleType

router = Router(name="start")
log = logging.getLogger(__name__)

# Faza 3.1: rollar 2 taga qisqartirildi — "🏭 Asset egasi" endi yangi
# ro'yxatga olishda taklif qilinmaydi (UserRole.asset_owner qiymati saqlanadi,
# faqat bu yerda ishlatilmaydi; mavjud userlar /migrate_roles orqali ko'chadi).
ROLE_MAP = {
    "🚛 Haydovchi": UserRole.driver,
    "📦 Yuk beruvchi": UserRole.cargo_provider,
}

VEHICLE_TYPE_MAP = {
    "Isuzu": VehicleType.isuzu,
    "Fura": VehicleType.fura,
    "Kichik (Porter/Labo)": VehicleType.kichik,
    "Boshqa": VehicleType.other,
}


def _normalize_phone(raw: str) -> str | None:
    """O'zbekiston raqamini tekshirib normallashtiradi.

    Qabul qilinadi: +998901234567, 998901234567, 901234567 (9 ta raqam).
    Qaytaradi: +998XXXXXXXXX yoki None (noto'g'ri bo'lsa).
    """
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 9:  # operator+raqam, 998 siz kiritilgan
        digits = "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return "+" + digits
    return None


async def _notify_admins_safe(bot: "Bot | None", user) -> None:
    """Ro'yxatdan o'tish tugagach adminlarga xabar (Faza 4.1).

    `bot` berilmasa (masalan test/monkeypatch) — jim o'tadi. Xato bo'lsa ham
    asosiy ro'yxatdan o'tish oqimi UZILMASIN — faqat log.
    """
    if bot is None:
        return
    try:
        await notify_admins_new_user(bot, user)
    except Exception:
        log.exception("notify_admins_new_user kutilmagan xato bilan tugadi")


WELCOME_TEXT = "Yuk Logistika Marketplace-ga xush kelibsiz!\n\nRo'lni tanlang:"


def _instruction_ack_kb() -> InlineKeyboardMarkup:
    """Faza 6 — instruksiya ko'rsatilgandan keyingi ikkita tugma: ikkalasi
    ham (Ko'rdim/Keyinroq farqsiz) rol tanlashga o'tkazadi."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ko'rdim", callback_data="instr|seen"),
        InlineKeyboardButton(text="⏭ Keyinroq", callback_data="instr|later"),
    ]])


async def _send_main_menu(message: Message, role: UserRole) -> None:
    if role == UserRole.cargo_provider:
        await message.answer(
            "Asosiy menyu:",
            reply_markup=main_menu_provider_kb(),
        )
    else:
        await message.answer(
            "Asosiy menyu:",
            reply_markup=main_menu_driver_kb(),
        )


# ---------------------------------------------------------------------------
# Ro'yxatdan o'tish savollari — bitta joyda, chunki «⬅️ Orqaga» bosilganda
# aynan o'sha savol qayta so'raladi (takroriy kod bo'lmasin).
# ---------------------------------------------------------------------------

async def _ask_role(message: Message, state: FSMContext) -> None:
    """Rol tanlashga qaytish. Sozlamalardan kelingan bo'lsa «reregister» saqlanadi.

    `pending_load_id` (deep-link orqali kutilayotgan yuk) ham saqlanishi
    shart — aks holda user «⬅️ Orqaga» bosib rol tanlashga qaytganda uni
    hech qachon ko'rmay ro'yxatdan o'tib qoladi (va'da qilingan raqam
    jim yo'qoladi).
    """
    data = await state.get_data()
    reregister = bool(data.get("reregister"))
    pending_load_id = data.get("pending_load_id")
    await state.clear()
    if reregister:
        await state.update_data(reregister=True)
        await state.set_state(RoleChange.waiting_role)
    if pending_load_id is not None:
        await state.update_data(pending_load_id=pending_load_id)
    await message.answer(
        "Ro'lni tanlang:", reply_markup=role_choice_kb(with_back=reregister)
    )


async def _ask_name(message: Message) -> None:
    await message.answer(
        "Ismingiz va familiyangizni kiriting\n(masalan: Alisher Qodirov):",
        reply_markup=back_reply_kb(),
    )


async def _ask_phone(message: Message) -> None:
    await message.answer(
        "Telefon raqamingizni yuboring:", reply_markup=phone_request_kb()
    )


async def _ask_vehicle_type(message: Message) -> None:
    await message.answer("Mashina turini tanlang:", reply_markup=vehicle_type_kb())


async def _ask_capacity(message: Message) -> None:
    await message.answer(
        "Mashina yuk ko'tarish quvvatini kiriting (tonnada, masalan: 5 yoki 1.5):",
        reply_markup=back_reply_kb(),
    )


async def _ask_pref_origin(message: Message, session: AsyncSession) -> None:
    viloyats = await get_ranked_viloyats(session)
    await message.answer(
        "📍 <b>Eng aktual yo'nalishingiz</b>\n\n"
        "Qaysi viloyatdan yuk olasiz? (eng ko'p yuk chiqadigan joylar yuqorida):",
        reply_markup=pref_viloyat_kb(viloyats, "prego", back_data="bk|dreg|capacity"),
    )


async def _ask_pref_destination(
    message: Message, session: AsyncSession, origin: str
) -> None:
    viloyats = await get_ranked_viloyats(session, origin_filter=origin)
    await message.answer(
        f"📍 <b>{origin}</b>dan qayerga olib borasiz?\n"
        "(Ikkala yo'nalish bo'yicha ham xabarnoma keladi — masalan "
        f"{origin}→X va X→{origin}):",
        reply_markup=pref_viloyat_kb(viloyats, "predst", back_data="bk|dreg|origin"),
    )


async def _ask_notify(message: Message) -> None:
    await message.answer(
        "🔔 <b>Xabarnoma</b>\n\n"
        "Shu yo'nalishga yangi yuk kelsa, sizga avtomatik xabar yuboraylikmi? "
        "(Keyin ⚙️ Sozlamalarda o'zgartirishingiz mumkin)",
        reply_markup=_notify_ask_kb(),
    )


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    # /start har doim ishlashi kerak — hatto foydalanuvchi biror jarayonda
    # (masalan yo'nalish tanlashda) "qotib qolgan" bo'lsa ham qutqaradi.
    await state.clear()

    parts = (message.text or "").split(maxsplit=1)
    deep_link_load_id = parse_load_start_payload(parts[1] if len(parts) > 1 else None)

    user = await get_or_none(session, message.from_user.id)
    if user:
        if deep_link_load_id is not None:
            await _show_deeplinked_load(message, session, deep_link_load_id)
        await _send_main_menu(message, user.role)
        return

    if deep_link_load_id is not None:
        await state.update_data(pending_load_id=deep_link_load_id)

    # Faza 6: yangi (hali ro'yxatdan o'tmagan) user uchun — instruksiya
    # sozlangan bo'lsa (video va/yoki matn) avval shuni ko'rsatamiz, keyin
    # «✅ Ko'rdim»/«⏭ Keyinroq» — IKKALASI HAM rol tanlashga o'tkazadi.
    # Sozlanmagan bo'lsa — to'g'ridan rol tanlash (eski xatti-harakat).
    instruction = await get_instruction(session)
    if instruction["video_file_id"] or instruction["text"]:
        if instruction["video_file_id"]:
            await message.answer_video(instruction["video_file_id"])
        if instruction["text"]:
            await message.answer(instruction["text"])
        await message.answer(
            "Botdan qanday foydalanishni ko'rsatib berdik. Davom etamizmi?",
            reply_markup=_instruction_ack_kb(),
        )
        return

    await message.answer(WELCOME_TEXT, reply_markup=role_choice_kb())


# ---------------------------------------------------------------------------
# Faza 6 — instruksiya ko'rsatilgandan keyin: ikkala tugma ham (Ko'rdim/
# Keyinroq) rol tanlashga o'tkazadi.
# ---------------------------------------------------------------------------

@router.callback_query(F.data.in_(["instr|seen", "instr|later"]))
async def instruction_ack(callback: CallbackQuery) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(WELCOME_TEXT, reply_markup=role_choice_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Rol tanlash
# ---------------------------------------------------------------------------

@router.message(F.text.in_(ROLE_MAP.keys()), StateFilter(None, RoleChange.waiting_role))
async def role_chosen(message: Message, state: FSMContext) -> None:
    role = ROLE_MAP[message.text]
    await state.update_data(role=role.value)

    if role == UserRole.cargo_provider:
        await state.set_state(ProviderReg.waiting_name)
    else:
        await state.set_state(DriverReg.waiting_name)

    await _ask_name(message)


# ---------------------------------------------------------------------------
# DriverReg oqimi
# ---------------------------------------------------------------------------

@router.message(DriverReg.waiting_name, F.text == BACK_TEXT)
async def driver_name_back(message: Message, state: FSMContext) -> None:
    """Ism → rol tanlash (oqimning eng birinchi qadami)."""
    await _ask_role(message, state)


@router.message(DriverReg.waiting_name)
async def driver_name(message: Message, state: FSMContext) -> None:
    if not message.text or len(message.text.strip()) < 3:
        await message.answer("Iltimos, to'liq ism kiriting (kamida 3 harf).")
        return

    await state.update_data(full_name=message.text.strip())
    await state.set_state(DriverReg.waiting_phone)
    await _ask_phone(message)


@router.message(DriverReg.waiting_phone, F.text == BACK_TEXT)
async def driver_phone_back(message: Message, state: FSMContext) -> None:
    """Telefon → ism."""
    await state.set_state(DriverReg.waiting_name)
    await _ask_name(message)


@router.message(DriverReg.waiting_phone, F.contact)
async def driver_phone_contact(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    await _reveal_pending_load_if_any(message, state, session)
    await state.set_state(DriverReg.waiting_vehicle_type)
    await _ask_vehicle_type(message)


@router.message(DriverReg.waiting_phone, F.text)
async def driver_phone_text(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    phone = _normalize_phone(message.text or "")
    if phone is None:
        await message.answer(
            "Noto'g'ri format. Raqamni +998XXXXXXXXX shaklida kiriting yoki "
            "«📱 Raqamni yuborish» tugmasini bosing."
        )
        return

    await state.update_data(phone=phone)
    await _reveal_pending_load_if_any(message, state, session)
    await state.set_state(DriverReg.waiting_vehicle_type)
    await _ask_vehicle_type(message)


@router.message(DriverReg.waiting_vehicle_type, F.text == BACK_TEXT)
async def driver_vehicle_back(message: Message, state: FSMContext) -> None:
    """Mashina turi → telefon."""
    await state.set_state(DriverReg.waiting_phone)
    await _ask_phone(message)


@router.message(DriverReg.waiting_vehicle_type, F.text.in_(VEHICLE_TYPE_MAP.keys()))
async def driver_vehicle_type(message: Message, state: FSMContext) -> None:
    await state.update_data(vehicle_type=message.text)
    await state.set_state(DriverReg.waiting_capacity)
    await _ask_capacity(message)


@router.message(DriverReg.waiting_vehicle_type)
async def driver_vehicle_type_invalid(message: Message) -> None:
    await message.answer("Iltimos, tugmalardan birini tanlang.")


@router.message(DriverReg.waiting_capacity, F.text == BACK_TEXT)
async def driver_capacity_back(message: Message, state: FSMContext) -> None:
    """Tonnaj → mashina turi."""
    await state.set_state(DriverReg.waiting_vehicle_type)
    await _ask_vehicle_type(message)


@router.message(DriverReg.waiting_capacity)
async def driver_capacity(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        capacity = float(message.text.replace(",", "."))
        if capacity <= 0 or capacity > 100:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("Noto'g'ri qiymat. 0 dan 100 gacha son kiriting (masalan: 5 yoki 1.5).")
        return

    await state.update_data(capacity_t=capacity)
    await state.set_state(DriverReg.waiting_pref_origin)
    await _ask_pref_origin(message, session)


@router.callback_query(DriverReg.waiting_pref_origin, F.data == "bk|dreg|capacity")
async def driver_pref_origin_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Chiqish viloyati → tonnaj."""
    await state.set_state(DriverReg.waiting_capacity)
    await callback.message.edit_reply_markup(reply_markup=None)
    await _ask_capacity(callback.message)
    await callback.answer()


# Inline bosqichlarda ekranda oldingi qadamning reply «⬅️ Orqaga» tugmasi ham
# qolib ketadi — u bosilsa ham xuddi shu bir qadam orqaga ishlashi kerak.

@router.message(DriverReg.waiting_pref_origin, F.text == BACK_TEXT)
async def driver_pref_origin_back_text(message: Message, state: FSMContext) -> None:
    await state.set_state(DriverReg.waiting_capacity)
    await _ask_capacity(message)


@router.message(DriverReg.waiting_pref_destination, F.text == BACK_TEXT)
async def driver_pref_dest_back_text(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    await state.set_state(DriverReg.waiting_pref_origin)
    await _ask_pref_origin(message, session)


@router.message(DriverReg.waiting_notify, F.text == BACK_TEXT)
async def driver_notify_back_text(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    await state.set_state(DriverReg.waiting_pref_destination)
    await _ask_pref_destination(message, session, data.get("pref_origin") or "")


@router.callback_query(DriverReg.waiting_pref_origin, F.data.startswith("prego_"))
async def driver_pref_origin(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    origin = callback.data.split("_", 1)[1]
    await state.update_data(pref_origin=origin)
    await state.set_state(DriverReg.waiting_pref_destination)

    await callback.message.edit_reply_markup(reply_markup=None)
    await _ask_pref_destination(callback.message, session, origin)
    await callback.answer()


def _notify_ask_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔔 Ha, xabar bering", callback_data="notify_yes"),
            InlineKeyboardButton(text="🔕 Yo'q", callback_data="notify_no"),
        ],
        back_row("bk|dreg|dest"),
    ])


@router.callback_query(DriverReg.waiting_pref_destination, F.data == "bk|dreg|origin")
async def driver_pref_dest_back(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Borish viloyati → chiqish viloyati."""
    await state.set_state(DriverReg.waiting_pref_origin)
    await callback.message.edit_reply_markup(reply_markup=None)
    await _ask_pref_origin(callback.message, session)
    await callback.answer()


@router.callback_query(DriverReg.waiting_pref_destination, F.data.startswith("predst_"))
async def driver_pref_destination(callback: CallbackQuery, state: FSMContext) -> None:
    destination = callback.data.split("_", 1)[1]
    await state.update_data(pref_destination=destination)
    await state.set_state(DriverReg.waiting_notify)

    await callback.message.edit_reply_markup(reply_markup=None)
    await _ask_notify(callback.message)
    await callback.answer()


@router.callback_query(DriverReg.waiting_notify, F.data == "bk|dreg|dest")
async def driver_notify_back(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Xabarnoma → borish viloyati."""
    data = await state.get_data()
    await state.set_state(DriverReg.waiting_pref_destination)
    await callback.message.edit_reply_markup(reply_markup=None)
    await _ask_pref_destination(callback.message, session, data.get("pref_origin") or "")
    await callback.answer()


@router.callback_query(DriverReg.waiting_notify, F.data.in_(["notify_yes", "notify_no"]))
async def driver_notify_choice(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot | None = None
) -> None:
    notify = callback.data == "notify_yes"
    data = await state.get_data()

    # Faza 3.3: mashina turi/tonnaj DriverReg oqimida yig'ilgan (waiting_vehicle_type,
    # waiting_capacity) — endi bazaga uzatiladi (avval tashlab yuborilardi).
    vehicle_type = VEHICLE_TYPE_MAP.get(data.get("vehicle_type"))
    capacity_t = data.get("capacity_t")

    is_reregister = bool(data.get("reregister"))
    if is_reregister:
        user = await get_or_none(session, callback.from_user.id)
        user = await update_user_role(
            session, user,
            role=UserRole(data["role"]),
            full_name=data["full_name"],
            phone=data.get("phone"),
            notify_enabled=notify,
            vehicle_type=vehicle_type,
            capacity_t=capacity_t,
        )
    else:
        user = await create_user(
            session,
            telegram_id=callback.from_user.id,
            role=UserRole(data["role"]),
            full_name=data["full_name"],
            phone=data.get("phone"),
            notify_enabled=notify,
            vehicle_type=vehicle_type,
            capacity_t=capacity_t,
        )

    user.pref_origin = data.get("pref_origin")
    user.pref_destination = data.get("pref_destination")

    await session.commit()
    await state.clear()

    # Faza 4.1: faqat YANGI ro'yxatdan o'tishda xabar — rol almashtirishda (reregister) emas.
    if not is_reregister:
        await _notify_admins_safe(bot, user)

    notify_line = (
        "🔔 Xabarnoma yoqildi — yangi yuklar avtomatik keladi."
        if notify else
        "🔕 Xabarnoma o'chiq — ⚙️ Sozlamalardan yoqishingiz mumkin."
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Ro'yxatdan o'tdingiz!\n\n"
        f"Ism: {user.full_name}\n"
        f"Rol: Haydovchi\n"
        f"Yo'nalish: {user.pref_origin} ↔ {user.pref_destination}\n"
        f"{notify_line}\n\n"
        f"Asosiy menyu:",
        reply_markup=main_menu_driver_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# ProviderReg oqimi
# ---------------------------------------------------------------------------

@router.message(ProviderReg.waiting_name, F.text == BACK_TEXT)
async def provider_name_back(message: Message, state: FSMContext) -> None:
    """Ism → rol tanlash (oqimning eng birinchi qadami)."""
    await _ask_role(message, state)


@router.message(ProviderReg.waiting_name)
async def provider_name(message: Message, state: FSMContext) -> None:
    if not message.text or len(message.text.strip()) < 3:
        await message.answer("Iltimos, to'liq ism kiriting (kamida 3 harf).")
        return

    await state.update_data(full_name=message.text.strip())
    await state.set_state(ProviderReg.waiting_phone)
    await _ask_phone(message)


@router.message(ProviderReg.waiting_phone, F.text == BACK_TEXT)
async def provider_phone_back(message: Message, state: FSMContext) -> None:
    """Telefon → ism."""
    await state.set_state(ProviderReg.waiting_name)
    await _ask_name(message)


@router.message(ProviderReg.waiting_phone, F.contact)
async def provider_phone_contact(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot | None = None
) -> None:
    phone = message.contact.phone_number
    await _finish_provider_reg(message, state, session, phone, bot)


@router.message(ProviderReg.waiting_phone, F.text)
async def provider_phone_text(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot | None = None
) -> None:
    phone = _normalize_phone(message.text or "")
    if phone is None:
        await message.answer(
            "Noto'g'ri format. Raqamni +998XXXXXXXXX shaklida kiriting yoki "
            "«📱 Raqamni yuborish» tugmasini bosing."
        )
        return
    await _finish_provider_reg(message, state, session, phone, bot)


async def _show_deeplinked_load(message: Message, session: AsyncSession, load_id: int) -> None:
    """Deep-link orqali so'ralgan yukni ko'rsatadi (raqam ochiq holda).

    Yuk topilmasa (band bo'lgan/eskirgan — 6 soatda o'chadi) — muloyim
    xabar, oqim to'xtamaydi.
    """
    load = await get_load_detail(session, load_id)
    if load is None:
        await message.answer("Bu yuk endi mavjud emas, lekin yangi yuklar bor 👇")
        return
    await message.answer(
        "📦 Siz ko'rmoqchi bo'lgan yuk:\n\n" + format_load_card(load, show_phone=True)
    )


async def _reveal_pending_load_if_any(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Deep-link orqali kutilayotgan yuk bo'lsa — ko'rsatadi va state'ni tozalaydi."""
    data = await state.get_data()
    load_id = data.get("pending_load_id")
    if load_id is None:
        return
    await _show_deeplinked_load(message, session, load_id)
    await state.update_data(pending_load_id=None)


async def _finish_provider_reg(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    phone: str,
    bot: Bot | None = None,
) -> None:
    data = await state.get_data()

    is_reregister = bool(data.get("reregister"))
    if is_reregister:
        user = await get_or_none(session, message.from_user.id)
        user = await update_user_role(
            session, user,
            role=UserRole(data["role"]),
            full_name=data["full_name"],
            phone=phone,
        )
    else:
        user = await create_user(
            session,
            telegram_id=message.from_user.id,
            role=UserRole(data["role"]),
            full_name=data["full_name"],
            phone=phone,
        )
    await session.commit()
    await state.clear()

    # Faza 4.1: faqat YANGI ro'yxatdan o'tishda xabar — rol almashtirishda (reregister) emas.
    if not is_reregister:
        await _notify_admins_safe(bot, user)

    await message.answer(
        f"✅ Ro'yxatdan o'tdingiz!\n\n"
        f"Ism: {user.full_name}\n"
        f"Rol: Yuk beruvchi\n\n"
        f"Asosiy menyu:",
        reply_markup=main_menu_provider_kb(),
    )

    pending_load_id = data.get("pending_load_id")
    if pending_load_id is not None:
        await _show_deeplinked_load(message, session, pending_load_id)


# ---------------------------------------------------------------------------
# Kutilmagan xabarlar handler'i alohida router'ga ko'chirildi
# (bot/handlers/fallback.py) — u eng oxirida ro'yxatdan o'tishi kerak,
# aks holda menyu tugmalarini "yutib" yuboradi.
# ---------------------------------------------------------------------------
