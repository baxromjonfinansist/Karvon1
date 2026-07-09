import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum, ForeignKey,
    Index, Integer, Numeric, String, Table, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base


# ---------------------------------------------------------------------------
# Enum-lar
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    driver = "driver"                   # 1-tip: haydovchi-ega
    cargo_provider = "cargo_provider"   # 2-tip: yuk beruvchi
    asset_owner = "asset_owner"         # 3-tip: asset egasi
    staff_driver = "staff_driver"       # 4-tip: mashinasiz haydovchi
    admin = "admin"


class VehicleType(str, enum.Enum):
    kichik = "kichik"   # Isuzudan kichik: Hyundai Porter, labo, damas
    isuzu = "isuzu"
    fura = "fura"
    other = "other"


class VehicleOwnership(str, enum.Enum):
    independent = "independent"   # o'z mashinasi
    leased = "leased"             # ijarada (Faza 2 fleet arm)
    company = "company"           # kompaniyaning


class VehicleStatus(str, enum.Enum):
    available = "available"
    on_trip = "on_trip"
    maintenance = "maintenance"


class RiskTier(str, enum.Enum):
    premium_safe = "premium_safe"   # yuqori narx, past risk
    standard = "standard"
    budget = "budget"               # past narx, yuqori risk


class LoadStatus(str, enum.Enum):
    pending = "pending"         # AI parserladi, moderatsiya kutmoqda
    open = "open"               # tasdiqlandi, haydovchi kutmoqda
    matched = "matched"         # haydovchi topildi, yetkazilmoqda
    closed = "closed"           # yetkazildi, bitim yopildi
    cancelled = "cancelled"


class DealStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class SubscriptionPlan(str, enum.Enum):
    basic = "basic"
    premium = "premium"


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    cancelled = "cancelled"


class TransactionType(str, enum.Enum):
    subscription = "subscription"
    commission = "commission"
    rent = "rent"               # Fleet/leasing (Faza 2)


class TransactionStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


# ---------------------------------------------------------------------------
# Association table: haydovchi ↔ afzal yo'nalishlar (ko'p-ko'p)
# ---------------------------------------------------------------------------

driver_preferred_routes = Table(
    "driver_preferred_routes",
    Base.metadata,
    Column("driver_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("route_id", Integer, ForeignKey("routes.id", ondelete="CASCADE"), primary_key=True),
)


# ---------------------------------------------------------------------------
# Modellar
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    rating: Mapped[Decimal] = mapped_column(Numeric(3, 2), server_default="5.00")
    verified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    sub_status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), server_default=SubscriptionStatus.expired.value, nullable=False
    )
    # Yo'nalish bo'yicha avtomatik yuk xabarnomasi (opt-in)
    notify_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Eng aktual yo'nalish (viloyat juftligi, ikkala tomon bo'yicha xabarnoma keladi)
    pref_origin: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    pref_destination: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Haydovchining tanlagan yo'nalishlari (feed filtri uchun)
    preferred_routes: Mapped[list["Route"]] = relationship(
        "Route", secondary=driver_preferred_routes, back_populates="interested_drivers"
    )

    vehicles_owned: Mapped[list["Vehicle"]] = relationship(
        "Vehicle", foreign_keys="Vehicle.owner_id", back_populates="owner"
    )
    vehicles_driven: Mapped[list["Vehicle"]] = relationship(
        "Vehicle", foreign_keys="Vehicle.driver_id", back_populates="driver"
    )
    loads_posted: Mapped[list["Load"]] = relationship("Load", back_populates="provider")
    deals_as_driver: Mapped[list["Deal"]] = relationship("Deal", back_populates="driver")
    subscriptions: Mapped[list["Subscription"]] = relationship("Subscription", back_populates="user")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="user")
    ratings_given: Mapped[list["Rating"]] = relationship(
        "Rating", foreign_keys="Rating.from_user_id", back_populates="from_user"
    )
    ratings_received: Mapped[list["Rating"]] = relationship(
        "Rating", foreign_keys="Rating.to_user_id", back_populates="to_user"
    )

    def __repr__(self) -> str:
        return f"<User {self.telegram_id} {self.role.value}>"


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    type: Mapped[VehicleType] = mapped_column(Enum(VehicleType), nullable=False)
    capacity_t: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    ownership: Mapped[VehicleOwnership] = mapped_column(Enum(VehicleOwnership), nullable=False)
    driver_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    status: Mapped[VehicleStatus] = mapped_column(Enum(VehicleStatus), server_default=VehicleStatus.available.value)
    plate_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id], back_populates="vehicles_owned")
    driver: Mapped[Optional["User"]] = relationship("User", foreign_keys=[driver_id], back_populates="vehicles_driven")

    def __repr__(self) -> str:
        return f"<Vehicle {self.type.value} {self.plate_number}>"


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin: Mapped[str] = mapped_column(String(100), nullable=False)
    destination: Mapped[str] = mapped_column(String(100), nullable=False)
    distance_km: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    base_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    loads: Mapped[list["Load"]] = relationship("Load", back_populates="route")
    interested_drivers: Mapped[list["User"]] = relationship(
        "User", secondary=driver_preferred_routes, back_populates="preferred_routes"
    )

    def __repr__(self) -> str:
        return f"<Route {self.origin}→{self.destination}>"


class Load(Base):
    __tablename__ = "loads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_channel: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    route_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("routes.id"), nullable=True)
    cargo_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    weight_t: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    vehicle_type: Mapped[Optional[VehicleType]] = mapped_column(Enum(VehicleType), nullable=True)
    risk_tier: Mapped[RiskTier] = mapped_column(Enum(RiskTier), server_default=RiskTier.standard.value)
    status: Mapped[LoadStatus] = mapped_column(Enum(LoadStatus), server_default=LoadStatus.pending.value)
    provider_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    route: Mapped[Optional["Route"]] = relationship("Route", back_populates="loads")
    provider: Mapped[Optional["User"]] = relationship("User", back_populates="loads_posted")
    deals: Mapped[list["Deal"]] = relationship("Deal", back_populates="load")

    def __repr__(self) -> str:
        return f"<Load #{self.id} {self.status.value}>"


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    load_id: Mapped[int] = mapped_column(Integer, ForeignKey("loads.id"), nullable=False)
    driver_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agreed_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    commission: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[DealStatus] = mapped_column(Enum(DealStatus), server_default=DealStatus.active.value)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    load: Mapped["Load"] = relationship("Load", back_populates="deals")
    driver: Mapped["User"] = relationship("User", back_populates="deals_as_driver")
    ratings: Mapped[list["Rating"]] = relationship("Rating", back_populates="deal")

    def __repr__(self) -> str:
        return f"<Deal #{self.id} load={self.load_id} {self.status.value}>"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    plan: Mapped[SubscriptionPlan] = mapped_column(Enum(SubscriptionPlan), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), server_default=SubscriptionStatus.active.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="subscriptions")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus), server_default=TransactionStatus.pending.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="transactions")


class Rating(Base):
    __tablename__ = "ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    deal_id: Mapped[int] = mapped_column(Integer, ForeignKey("deals.id"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–5
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    from_user: Mapped["User"] = relationship(
        "User", foreign_keys=[from_user_id], back_populates="ratings_given"
    )
    to_user: Mapped["User"] = relationship(
        "User", foreign_keys=[to_user_id], back_populates="ratings_received"
    )
    deal: Mapped["Deal"] = relationship("Deal", back_populates="ratings")


class Feedback(Base):
    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LorryListing(Base):
    """LORRY guruhi e'lonlari TARIXI — logist aniqlash (route diversity) uchun.

    Yuk feed'idan (`loads`) alohida: bu jadval 12+ soat saqlanadi (Load 60
    daqiqada o'chadi). Maqsad — bitta telefondan oxirgi 12 soatda nechta
    TURLI yo'nalish chiqqanini sanash. Har bir LORRY xabari (logist bo'lsa
    ham) shu yerga yoziladi; faqat `loads` bazasiga logist tushmaydi.
    """
    __tablename__ = "lorry_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_norm: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # +998XXXXXXXXX
    origin_canon: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dest_canon: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_group: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    classification: Mapped[str] = mapped_column(String(20), server_default="cargo", nullable=False)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # dublikat repostni sanamaslik uchun
    posted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True, server_default=func.now())

    __table_args__ = (
        # 12 soatlik window query (phone + vaqt) tez ishlashi uchun composite index.
        Index("ix_lorry_phone_posted", "phone_norm", "posted_at"),
    )

    def __repr__(self) -> str:
        return f"<LorryListing {self.phone_norm} {self.origin_canon}->{self.dest_canon} {self.classification}>"


class LogistBlocklist(Base):
    """Qo'lda belgilangan logist telefonlari (admin qarori — algoritmdan ustun).

    Bu ro'yxatdagi raqamdan kelgan yuk HECH QAYSI kanaldan yuk bazasiga
    tushmaydi. Admin `/logist` buyrug'i bilan qo'shadi/o'chiradi.
    """
    __tablename__ = "logist_blocklist"

    phone_norm: Mapped[str] = mapped_column(String(20), primary_key=True)  # +998XXXXXXXXX
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<LogistBlocklist {self.phone_norm}>"
