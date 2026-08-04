from aiogram.fsm.state import State, StatesGroup


class DriverReg(StatesGroup):
    waiting_name = State()
    waiting_phone = State()
    waiting_vehicle_type = State()
    waiting_capacity = State()
    waiting_pref_origin = State()
    waiting_pref_destination = State()
    waiting_notify = State()


class RoleChange(StatesGroup):
    """Sozlamalardan rol o'zgartirish — «⬅️ Orqaga» profilga qaytarishi uchun."""

    waiting_role = State()


class FeedbackFlow(StatesGroup):
    waiting_text = State()


class ProviderReg(StatesGroup):
    waiting_name = State()
    waiting_phone = State()


class LoadPost(StatesGroup):
    waiting_origin = State()
    waiting_destination = State()
    waiting_cargo_type = State()
    waiting_weight = State()
    waiting_price = State()
    waiting_confirm = State()


class RatingFlow(StatesGroup):
    waiting_score = State()
    waiting_comment = State()


class BroadcastFlow(StatesGroup):
    """Faza 5 — admin xabarnoma (broadcast): qabul qiluvchi tanlash → kontent → tasdiq → yuborish."""

    waiting_target = State()        # 👥 Barchaga / 🎯 Guruh bo'yicha
    waiting_group_choice = State()  # rol yoki viloyat tanlash
    waiting_checklist = State()     # guruh a'zolarini ☑️/⬜️ bilan belgilash
    waiting_content = State()       # matn yoki media kutilmoqda
    waiting_confirm = State()       # preview + ✅ Yuborish / ❌ Bekor qilish
