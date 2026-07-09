from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from db.models import (
    Deal, DealStatus, Load, LoadStatus,
    Route, User, UserRole, VehicleType, driver_preferred_routes,
)

# Yuk faqat shuncha daqiqa "yangi" hisoblanadi — undan eskisi ko'rsatilmaydi
# va bazadan avtomatik o'chiriladi. Feed shu oynadagi yuklarni ko'rsatadi.
FRESH_MINUTES = 120


def _fresh_cutoff() -> datetime:
    return datetime.utcnow() - timedelta(minutes=FRESH_MINUTES)


async def delete_stale_loads(session: AsyncSession) -> int:
    """FRESH_MINUTES dan eski, hali band qilinmagan (open/pending) yuklarni o'chiradi.

    Matched/closed yuklar (bitimga bog'langan) tegilmaydi — FK buzilmaydi.
    """
    result = await session.execute(
        delete(Load).where(
            Load.status.in_([LoadStatus.open, LoadStatus.pending]),
            Load.posted_at < _fresh_cutoff(),
        )
    )
    await session.commit()
    return result.rowcount or 0


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
        .where(Load.status == LoadStatus.open, Load.posted_at >= _fresh_cutoff())
        .group_by(Route.origin)
        .order_by(func.count(Load.id).desc())
    )
    return [(row[0], row[1]) for row in result.all()]


# Shahar/tuman -> viloyat. Manzillarni viloyat bo'yicha guruhlash uchun.
# Kalitlar: kichik harf, to'g'ri apostrof ('). Xaritada yo'q manzil o'zicha
# alohida guruh bo'ladi (hech qanday yuk yashirilmaydi).
_REGION_OF = {
    # Toshkent viloyati
    "toshkent": "Toshkent", "chirchiq": "Toshkent", "angren": "Toshkent",
    "olmaliq": "Toshkent", "bekobod": "Toshkent", "parkent": "Toshkent",
    "kibray": "Toshkent", "nurafshon": "Toshkent", "yangiyo'l": "Toshkent",
    "ohangaron": "Toshkent", "chinoz": "Toshkent",
    # Sirdaryo
    "sirdaryo": "Sirdaryo", "guliston": "Sirdaryo", "yangiyer": "Sirdaryo",
    "xovos": "Sirdaryo", "shirin": "Sirdaryo", "boyovut": "Sirdaryo",
    # Jizzax
    "jizzax": "Jizzax", "gagarin": "Jizzax", "zomin": "Jizzax",
    # Samarqand
    "samarqand": "Samarqand", "kattaqo'rg'on": "Samarqand", "urgut": "Samarqand",
    "bulung'ur": "Samarqand", "jomboy": "Samarqand",
    # Qashqadaryo
    "qashqadaryo": "Qashqadaryo", "qarshi": "Qashqadaryo", "shahrisabz": "Qashqadaryo",
    "koson": "Qashqadaryo", "qamashi": "Qashqadaryo", "kitob": "Qashqadaryo",
    "g'uzor": "Qashqadaryo", "muborak": "Qashqadaryo", "kasbi": "Qashqadaryo",
    # Surxondaryo
    "surxondaryo": "Surxondaryo", "termiz": "Surxondaryo", "denov": "Surxondaryo",
    "sho'rchi": "Surxondaryo", "boysun": "Surxondaryo", "sherobod": "Surxondaryo",
    "jarqo'rg'on": "Surxondaryo", "qumqo'rg'on": "Surxondaryo",
    # Buxoro
    "buxoro": "Buxoro", "g'ijduvon": "Buxoro", "kogon": "Buxoro",
    "qorako'l": "Buxoro", "vobkent": "Buxoro",
    # Navoiy
    "navoiy": "Navoiy", "zarafshon": "Navoiy", "uchquduq": "Navoiy",
    "karmana": "Navoiy", "nurota": "Navoiy",
    # Xorazm
    "xorazm": "Xorazm", "urganch": "Xorazm", "xiva": "Xorazm",
    "gurlan": "Xorazm", "hazorasp": "Xorazm", "shovot": "Xorazm", "pitnak": "Xorazm",
    # Qoraqalpog'iston
    "qoraqalpog'iston": "Qoraqalpog'iston", "nukus": "Qoraqalpog'iston",
    "qo'ng'irot": "Qoraqalpog'iston", "xo'jayli": "Qoraqalpog'iston",
    "chimboy": "Qoraqalpog'iston", "beruniy": "Qoraqalpog'iston", "to'rtko'l": "Qoraqalpog'iston",
    # Namangan
    "namangan": "Namangan", "chust": "Namangan", "pop": "Namangan",
    "chortoq": "Namangan", "uchqo'rg'on": "Namangan", "kosonsoy": "Namangan",
    # Andijon
    "andijon": "Andijon", "asaka": "Andijon", "xonobod": "Andijon",
    "shahrixon": "Andijon", "qo'rg'ontepa": "Andijon", "marhamat": "Andijon",
    # Farg'ona
    "farg'ona": "Farg'ona", "qo'qon": "Farg'ona", "marg'ilon": "Farg'ona",
    "quvasoy": "Farg'ona", "oltiariq": "Farg'ona", "rishton": "Farg'ona",
    "bag'dod": "Farg'ona", "qo'shtepa": "Farg'ona", "quva": "Farg'ona",
}


def _region_key(dest: str) -> str:
    return (dest or "").strip().lower().replace("’", "'").replace("ʼ", "'").replace("`", "'")


def _dest_region(dest: str) -> str:
    """Manzil shaharini viloyatga aylantiradi; topilmasa o'zini qaytaradi."""
    return _REGION_OF.get(_region_key(dest), dest)


# Barcha viloyatlar — ro'yxatdan o'tishda yo'nalish tanlashda ishlatiladi
# (joriy yuk oqimidan qat'i nazar, hammasi doim tanlash uchun ochiq).
ALL_VILOYATS = [
    "Toshkent", "Andijon", "Farg'ona", "Namangan", "Samarqand", "Sirdaryo",
    "Jizzax", "Qashqadaryo", "Xorazm", "Buxoro", "Navoiy", "Surxondaryo",
    "Qoraqalpog'iston",
]


async def get_ranked_viloyats(
    session: AsyncSession, origin_filter: Optional[str] = None
) -> list[tuple[str, int]]:
    """Barcha viloyatlar — joriy yuk soni bo'yicha kamayish tartibida (0 talari oxirida).

    origin_filter berilsa — shu viloyatdan chiqadigan yuklar manzili bo'yicha
    (get_destination_regions kabi). Aks holda — chiqish viloyati bo'yicha
    (get_origin_regions_with_open_loads kabi).
    """
    if origin_filter is None:
        ranked = await get_origin_regions_with_open_loads(session)
    else:
        ranked = await get_destination_regions(session, origin_filter)
    counts = dict(ranked)
    for v in ALL_VILOYATS:
        counts.setdefault(v, 0)
    return sorted(counts.items(), key=lambda x: -x[1])


async def get_destination_regions(
    session: AsyncSession, origin: str, vehicle: Optional[str] = None
) -> list[tuple[str, int]]:
    """Chiqish viloyatidan boradigan manzillar viloyat bo'yicha guruhlangan.

    vehicle berilsa ("fura"/"isuzu") — faqat shu turdagi yuklar sanaladi.
    Qaytaradi: [("Samarqand", 58), ("Qashqadaryo", 42), ...] — eng ko'pi yuqorida.
    """
    conds = [
        Load.status == LoadStatus.open,
        Route.origin == origin,
        Load.posted_at >= _fresh_cutoff(),
    ]
    vf = _vehicle_filter(vehicle)
    if vf is not None:
        conds.append(vf)
    result = await session.execute(
        select(Route.destination, func.count(Load.id))
        .join(Load, Load.route_id == Route.id)
        .where(*conds)
        .group_by(Route.destination)
    )
    buckets: dict[str, int] = {}
    for dest, cnt in result.all():
        b = _dest_region(dest)
        buckets[b] = buckets.get(b, 0) + cnt
    return sorted(buckets.items(), key=lambda x: -x[1])


async def get_selection_loads(
    session: AsyncSession,
    origin: str,
    dest_region: str,
    vehicle: Optional[str] = None,
    offset: int = 0,
    limit: int = 10,
) -> tuple[list[Load], bool]:
    """Chiqish viloyati + mashina turi + borish viloyati bo'yicha yuklar (eng yangisidan).

    offset/limit — sahifalash. Qaytaradi: (yuklar_sahifasi, yana_bormi).
    """
    conds = [
        Load.status == LoadStatus.open,
        Route.origin == origin,
        Load.posted_at >= _fresh_cutoff(),
    ]
    vf = _vehicle_filter(vehicle)
    if vf is not None:
        conds.append(vf)
    result = await session.execute(
        select(Load)
        .options(joinedload(Load.route), joinedload(Load.provider))
        .join(Route, Load.route_id == Route.id)
        .where(*conds)
        .order_by(Load.posted_at.desc())
    )
    loads = [
        l for l in result.scalars().unique().all()
        if l.route and _dest_region(l.route.destination) == dest_region
    ]
    page = loads[offset:offset + limit]
    has_more = len(loads) > offset + limit
    return page, has_more


def _vehicle_filter(vehicle: Optional[str]):
    """Mashina turi bo'yicha filtr — parser vaqtida hisoblangan vehicle_type ustuniga."""
    if vehicle == "kichik":
        return Load.vehicle_type == VehicleType.kichik
    if vehicle == "isuzu":
        return Load.vehicle_type == VehicleType.isuzu
    if vehicle == "fura":
        return Load.vehicle_type == VehicleType.fura
    return None


async def get_vehicle_counts_by_origin(
    session: AsyncSession, origin: str
) -> list[tuple[str, int]]:
    """Viloyatdagi ochiq yuklarni mashina turi bo'yicha sanaydi.

    Qaytaradi: [("fura", 300), ("isuzu", 6), ("kichik", 2)] — faqat yuk bor turlar.
    """
    base = (
        select(func.count(Load.id))
        .join(Route, Load.route_id == Route.id)
        .where(
            Load.status == LoadStatus.open,
            Route.origin == origin,
            Load.posted_at >= _fresh_cutoff(),
        )
    )
    out: list[tuple[str, int]] = []
    for veh in ("fura", "isuzu", "kichik"):
        n = (await session.execute(base.where(_vehicle_filter(veh)))).scalar() or 0
        if n:
            out.append((veh, n))
    return out


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
