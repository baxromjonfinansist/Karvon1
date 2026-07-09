from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
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
