from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Deal, DealStatus, Load, LoadStatus, Rating, User


async def complete_deal(session: AsyncSession, deal_id: int) -> Deal:
    result = await session.execute(
        select(Deal)
        .options(selectinload(Deal.load))
        .where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise ValueError(f"Bitim #{deal_id} topilmadi.")

    deal.status = DealStatus.completed
    deal.closed_at = datetime.now(timezone.utc)
    if deal.load:
        deal.load.status = LoadStatus.closed

    await session.flush()
    return deal


async def submit_rating(
    session: AsyncSession,
    from_user: User,
    to_user_id: int,
    deal_id: int,
    score: int,
    comment: Optional[str],
) -> Rating:
    if score not in range(1, 6):
        raise ValueError("Reyting 1 dan 5 gacha bo'lishi kerak.")

    duplicate = await session.execute(
        select(Rating).where(
            Rating.from_user_id == from_user.id,
            Rating.deal_id == deal_id,
        )
    )
    if duplicate.scalar_one_or_none():
        raise ValueError("Siz bu bitim uchun allaqachon reyting qoldirgansiz.")

    rating = Rating(
        from_user_id=from_user.id,
        to_user_id=to_user_id,
        deal_id=deal_id,
        score=score,
        comment=comment or None,
    )
    session.add(rating)
    await session.flush()

    avg_result = await session.execute(
        select(func.avg(Rating.score)).where(Rating.to_user_id == to_user_id)
    )
    avg = avg_result.scalar()
    if avg is not None:
        to_user = (
            await session.execute(select(User).where(User.id == to_user_id))
        ).scalar_one_or_none()
        if to_user:
            to_user.rating = Decimal(str(round(float(avg), 2)))

    return rating


async def get_pending_ratings(session: AsyncSession, user: User) -> list[Deal]:
    rated_result = await session.execute(
        select(Rating.deal_id).where(Rating.from_user_id == user.id)
    )
    already_rated_ids = [row[0] for row in rated_result.fetchall()]

    query = (
        select(Deal)
        .join(Deal.load)
        .options(selectinload(Deal.load).selectinload(Load.route))
        .where(
            Deal.status == DealStatus.completed,
            or_(Deal.driver_id == user.id, Load.provider_id == user.id),
        )
    )
    if already_rated_ids:
        query = query.where(Deal.id.notin_(already_rated_ids))

    result = await session.execute(query)
    return list(result.scalars().unique().all())


async def has_rated(session: AsyncSession, from_user_id: int, deal_id: int) -> bool:
    result = await session.execute(
        select(Rating).where(
            Rating.from_user_id == from_user_id,
            Rating.deal_id == deal_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def get_deal_for_rating(session: AsyncSession, deal_id: int) -> Optional[Deal]:
    result = await session.execute(
        select(Deal)
        .options(selectinload(Deal.load))
        .where(Deal.id == deal_id)
    )
    return result.scalar_one_or_none()


async def get_active_deal_by_load(session: AsyncSession, load_id: int) -> Optional[Deal]:
    result = await session.execute(
        select(Deal)
        .options(selectinload(Deal.load), selectinload(Deal.driver))
        .where(
            Deal.load_id == load_id,
            Deal.status == DealStatus.active,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()
