from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Load,
    Route,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    User,
    UserRole,
)


async def get_or_none(session: AsyncSession, telegram_id: int) -> Optional[User]:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


# Aktivlik yozuvini shu oraliqdan tez-tez yangilamaymiz (DB yukini kamaytirish).
_ACTIVE_THROTTLE = timedelta(minutes=5)


async def touch_last_active(session: AsyncSession, telegram_id: int) -> None:
    """Foydalanuvchining last_active_at ini yangilaydi (DAU/WAU/MAU uchun).

    Throttle: oxirgi yozuvdan _ACTIVE_THROTTLE o'tmagan bo'lsa — tegmaydi
    (kun/hafta darajasidagi aktivlikka ta'sir qilmaydi, DB yozuvini tejaydi).
    Ro'yxatdan o'tmagan (User yo'q) telegram_id uchun jim o'tadi.
    """
    now = datetime.utcnow()
    result = await session.execute(
        select(User.id, User.last_active_at).where(User.telegram_id == telegram_id)
    )
    row = result.first()
    if row is None:
        return  # hali ro'yxatdan o'tmagan — /start jarayonida yoziladi
    user_id, last_active = row
    if last_active is not None and now - last_active < _ACTIVE_THROTTLE:
        return
    await session.execute(
        update(User).where(User.id == user_id).values(last_active_at=now)
    )
    await session.commit()


async def create_user(
    session: AsyncSession,
    telegram_id: int,
    role: UserRole,
    full_name: str,
    phone: Optional[str],
    notify_enabled: bool = False,
) -> User:
    user = User(
        telegram_id=telegram_id,
        role=role,
        full_name=full_name,
        phone=phone,
        notify_enabled=notify_enabled,
    )
    session.add(user)
    await session.flush()
    return user


async def update_user_role(
    session: AsyncSession,
    user: User,
    role: UserRole,
    full_name: str,
    phone: Optional[str],
    notify_enabled: bool = False,
) -> User:
    """Mavjud foydalanuvchining rolini almashtiradi (adashib boshqa rol tanlaganda).

    Bitim/reyting tarixi (user.id o'zgarmaydi) saqlanib qoladi.
    """
    user.role = role
    user.full_name = full_name
    if phone:
        user.phone = phone
    user.notify_enabled = notify_enabled
    await session.flush()
    return user


async def set_preferred_routes(
    session: AsyncSession,
    user: User,
    route_ids: list[int],
) -> None:
    result = await session.execute(
        select(Route).where(Route.id.in_(route_ids))
    )
    routes = result.scalars().all()

    # preferred_routes ni to'g'ri yuklash uchun
    await session.refresh(user, ["preferred_routes"])
    user.preferred_routes = list(routes)
    await session.flush()


async def is_subscribed(session: AsyncSession, user: User) -> bool:
    if user.sub_status != SubscriptionStatus.active:
        return False
    result = await session.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.status == SubscriptionStatus.active,
            Subscription.end_date > datetime.now(timezone.utc),
        )
    )
    return result.scalar_one_or_none() is not None


async def get_active_subscription(
    session: AsyncSession, user: User
) -> Optional[Subscription]:
    """Foydalanuvchining eng so'nggi faol obunasini qaytaradi (yoki None)."""
    result = await session.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.status == SubscriptionStatus.active,
        )
        .order_by(Subscription.end_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def grant_subscription(
    session: AsyncSession,
    user: User,
    months: int,
    plan: SubscriptionPlan,
) -> Subscription:
    """Foydalanuvchiga qo'lda obuna beradi (Payme/Click integratsiyasigacha vaqtinchalik).

    Eski faol obunalarni `expired` qiladi, yangi obuna yaratadi va
    `user.sub_status` ni `active` ga o'tkazadi.
    """
    now = datetime.now(timezone.utc)

    # Eski faol obunalarni yopamiz
    old = await session.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.status == SubscriptionStatus.active,
        )
    )
    for sub in old.scalars().all():
        sub.status = SubscriptionStatus.expired

    subscription = Subscription(
        user_id=user.id,
        plan=plan,
        start_date=now,
        end_date=now + timedelta(days=30 * months),
        status=SubscriptionStatus.active,
    )
    session.add(subscription)
    user.sub_status = SubscriptionStatus.active
    await session.flush()
    return subscription


async def get_all_routes(session: AsyncSession) -> list[Route]:
    """Yo'nalishlar — eng ko'p yuk o'tganlari birinchi (ro'yxat sahifalanadi)."""
    result = await session.execute(
        select(Route)
        .outerjoin(Load, Load.route_id == Route.id)
        .group_by(Route.id)
        .order_by(func.count(Load.id).desc(), Route.id)
    )
    return list(result.scalars().all())


async def get_activity_dashboard(session: AsyncSession) -> dict:
    """Admin dashboard uchun aktivlik statistikasi.

    Barcha vaqtlar naive UTC (bazadagi ustunlar bilan mos). "Aktiv" =
    last_active_at berilgan oyna ichida. Bu ma'lumot MIGRATSIYADAN keyin
    to'plana boshlaydi — o'tmish uchun last_active_at NULL (aktivmas sanaladi).
    """
    now = datetime.utcnow()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    async def _count(condition) -> int:
        return (await session.execute(
            select(func.count(User.id)).where(condition)
        )).scalar() or 0

    # DAU / WAU / MAU — oxirgi faollik oynasi bo'yicha
    dau = await _count(User.last_active_at >= day_ago)
    wau = await _count(User.last_active_at >= week_ago)
    mau = await _count(User.last_active_at >= month_ago)

    total_users = await _count(User.id.isnot(None))
    ever_active = await _count(User.last_active_at.isnot(None))

    # Yuk feed'ini ochgan haydovchilar (kun/hafta)
    feed_day = await _count(User.last_feed_view_at >= day_ago)
    feed_week = await _count(User.last_feed_view_at >= week_ago)

    # Ro'yxatdan o'tish dinamikasi (created_at bo'yicha — o'tmish uchun ham ishlaydi)
    signup_day = await _count(User.created_at >= day_ago)
    signup_week = await _count(User.created_at >= week_ago)
    signup_month = await _count(User.created_at >= month_ago)

    # Rol bo'yicha aktiv (hafta) — kim faol
    role_rows = (await session.execute(
        select(User.role, func.count(User.id))
        .where(User.last_active_at >= week_ago)
        .group_by(User.role)
    )).all()
    active_by_role = {role.value: cnt for role, cnt in role_rows}

    return {
        "now": now,
        "total_users": total_users,
        "ever_active": ever_active,
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "feed_day": feed_day,
        "feed_week": feed_week,
        "signup_day": signup_day,
        "signup_week": signup_week,
        "signup_month": signup_month,
        "active_by_role": active_by_role,
    }


async def seed_default_routes(session: AsyncSession) -> None:
    """Agar routes jadvali bo'sh bo'lsa, 5 ta standart yo'nalish qo'shadi."""
    result = await session.execute(select(Route).limit(1))
    if result.scalar_one_or_none() is not None:
        return

    defaults = [
        Route(origin="Toshkent", destination="Samarqand", distance_km=340, base_price=500_000),
        Route(origin="Toshkent", destination="Buxoro", distance_km=580, base_price=800_000),
        Route(origin="Toshkent", destination="Namangan", distance_km=320, base_price=450_000),
        Route(origin="Toshkent", destination="Andijon", distance_km=375, base_price=550_000),
        Route(origin="Samarqand", destination="Termiz", distance_km=450, base_price=650_000),
    ]
    session.add_all(defaults)
    await session.commit()
