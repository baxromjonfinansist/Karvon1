from aiogram.fsm.state import State, StatesGroup


class DriverReg(StatesGroup):
    waiting_name = State()
    waiting_phone = State()
    waiting_vehicle_type = State()
    waiting_capacity = State()
    waiting_routes = State()


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
