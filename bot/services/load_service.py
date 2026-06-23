from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from db.models import (
    Deal, DealStatus, Load, LoadStatus,
    Route, User, UserRole, driver_preferred_routes,
)


async def get_feed(session: AsyncSession, user: User) -> list[Load]:
    pref_result = await session.execute(
        select(driver_preferred_routes.c.route_id)
        .where(driver_preferred_routes.c.driver_id == user.id)
    )
    preferred_route_ids = [row[0] for row in pref_result.fetchall()]

    query = (
        select(Load)
        .options(joinedload(Load.route), joinedload(Load.provider))
        .where(Load.status == LoadStatus.open)
        .order_by(Load.posted_at.desc())
        .limit(20)
    )
    if preferred_route_ids:
        query = query.where(Load.route_id.in_(preferred_route_ids))

    result = await session.execute(query)
    return list(result.scalars().unique().all())


async def get_load_detail(session: AsyncSession, load_id: int) -> Optional[Load]:
    result = await session.execute(
        select(Load)
        .options(joinedload(Load.route), joinedload(Load.provider))
        .where(Load.id == load_id)
    )
    return result.scalar_one_or_none()


async def take_load(session: AsyncSession, load: Load, driver: User) -> Optional[Deal]:
    """Yukni atomar tarzda band qiladi.

    Faqat status hali `open` bo'lsa `matched` ga o'tkazadi. Agar boshqa
    haydovchi bir vaqtning o'zida olib ulgurgan bo'lsa, UPDATE 0 qator
    qaytaradi va biz None qaytaramiz (deal yaratilmaydi).
    """
    result = await session.execute(
        update(Load)
        .where(Load.id == load.id, Load.status == LoadStatus.open)
        .values(status=LoadStatus.matched)
        .returning(Load.id)
    )
    if result.scalar_one_or_none() is None:
        return None  # allaqachon band qilingan

    commission = (load.price or Decimal("0")) * Decimal("0.05")
    deal = Deal(
        load_id=load.id,
        driver_id=driver.id,
        agreed_price=load.price,
        commission=commission,
        status=DealStatus.active,
    )
    session.add(deal)
    await session.flush()
    return deal


async def get_driver_deals(session: AsyncSession, driver: User) -> list[Deal]:
    result = await session.execute(
        select(Deal)
        .options(joinedload(Deal.load).joinedload(Load.route))
        .where(Deal.driver_id == driver.id)
        .order_by(Deal.created_at.desc())
    )
    return list(result.scalars().unique().all())


def _norm_city(s: str) -> str:
    """Apostrof variantlarini birlashtirib, birinchi harfni katta qiladi."""
    s = (s or "").strip().replace("’", "'").replace("ʼ", "'").replace("`", "'")
    return s[:1].upper() + s[1:].lower() if s else s


async def get_or_create_route(
    session: AsyncSession, origin: str, destination: str
) -> Route:
    origin = _norm_city(origin)
    destination = _norm_city(destination)
    result = await session.execute(
        select(Route).where(
            func.lower(Route.origin) == origin.lower(),
            func.lower(Route.destination) == destination.lower(),
        )
    )
    route = result.scalar_one_or_none()
    if route is None:
        route = Route(origin=origin, destination=destination)
        session.add(route)
        await session.flush()
    return route


async def create_load(
    session: AsyncSession,
    provider: User,
    route_id: int,
    cargo_type: str,
    weight_t: float,
    price: float,
) -> Load:
    load = Load(
        provider_id=provider.id,
        route_id=route_id,
        cargo_type=cargo_type,
        weight_t=Decimal(str(weight_t)),
        price=Decimal(str(price)),
        status=LoadStatus.pending,  # moderatsiyaga tushadi, admin tasdiqlagach `open`
    )
    session.add(load)
    await session.flush()
    return load


async def get_provider_loads(session: AsyncSession, provider: User) -> list[Load]:
    result = await session.execute(
        select(Load)
        .options(joinedload(Load.route))
        .where(Load.provider_id == provider.id)
        .order_by(Load.posted_at.desc())
    )
    return list(result.scalars().unique().all())


async def get_origin_regions_with_open_loads(session: AsyncSession) -> list[tuple[str, int]]:
    """Ochiq yuk bor viloyatlar (chiqish) va har biridagi yuklar soni.

    Yuklar bo'limi menyusi viloyat bo'yicha — faqat yuk bor viloyatlar,
    eng ko'p yuk borlari yuqorida.
    """
    result = await session.execute(
        select(Route.origin, func.count(Load.id).label("cnt"))
        .join(Load, Load.route_id == Route.id)
        .where(Load.status == LoadStatus.open)
        .group_by(Route.origin)
        .order_by(func.count(Load.id).desc())
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_open_loads_by_origin(
    session: AsyncSession, origin: str, limit: int = 10
) -> list[Load]:
    """Bitta viloyatdan (origin) chiqadigan ochiq yuklar (eng yangisidan)."""
    result = await session.execute(
        select(Load)
        .options(joinedload(Load.route), joinedload(Load.provider))
        .join(Route, Load.route_id == Route.id)
        .where(Load.status == LoadStatus.open, Route.origin == origin)
        .order_by(Load.posted_at.desc())
        .limit(limit)
    )
    return list(result.scalars().unique().all())


async def cancel_load(session: AsyncSession, load_id: int, provider_id: int) -> bool:
    """Provider o'z yukini bekor qiladi.

    Faqat `pending` yoki `open` holatdagi (hali haydovchi olmagan) yukni
    bekor qilish mumkin. Muvaffaqiyatli bo'lsa True qaytaradi.
    """
    result = await session.execute(
        update(Load)
        .where(
            Load.id == load_id,
            Load.provider_id == provider_id,
            Load.status.in_([LoadStatus.pending, LoadStatus.open]),
        )
        .values(status=LoadStatus.cancelled)
        .returning(Load.id)
    )
    return result.scalar_one_or_none() is not None


async def get_driver_telegram_ids_for_route(
    session: AsyncSession, route_id: Optional[int]
) -> list[int]:
    """Yangi yuk `open` bo'lganda xabar yuboriladigan haydovchilar.

    - Shu yo'nalishni afzal ko'rgan haydovchilar, VA
    - Hech qanday yo'nalish tanlamagan (hammasi ko'rsin) haydovchilar.
    """
    driver_roles = [UserRole.driver, UserRole.asset_owner, UserRole.staff_driver]

    # Yo'nalishni tanlagan haydovchilar
    interested_ids: set[int] = set()
    if route_id is not None:
        rows = await session.execute(
            select(driver_preferred_routes.c.driver_id)
            .where(driver_preferred_routes.c.route_id == route_id)
        )
        interested_ids = {row[0] for row in rows.fetchall()}

    # Umuman yo'nalish tanlamagan haydovchilar (filtersiz feed ko'radi)
    drivers_with_prefs = await session.execute(
        select(driver_preferred_routes.c.driver_id).distinct()
    )
    has_prefs = {row[0] for row in drivers_with_prefs.fetchall()}

    result = await session.execute(
        select(User.id, User.telegram_id).where(User.role.in_(driver_roles))
    )
    telegram_ids: list[int] = []
    for user_id, telegram_id in result.fetchall():
        if user_id in interested_ids or user_id not in has_prefs:
            telegram_ids.append(telegram_id)
    return telegram_ids
