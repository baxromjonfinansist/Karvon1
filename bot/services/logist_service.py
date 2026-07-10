"""LORRY logist aniqlash — V1 (Route Diversity).

Logist signali = e'lonlar SONI emas, balki bitta telefondan oxirgi 12 soatda
nechta TURLI yo'nalish (origin->dest, shahar darajasi, directional) chiqqani.

    distinct >= HARD_THRESHOLD  -> LOGIST      (yuk bazasiga tushmaydi)
    distinct == SOFT_THRESHOLD  -> SUSPICIOUS  (V1: bazaga tushadi, faqat log)
    distinct <= 2               -> CARGO       (bazaga tushadi)

Sof funksiyalar (parse_route, canonicalize_city, classify_routes, ...) DB'ga
bog'liq EMAS — avval mustaqil test qilinadi. `classify_phone_db` — SQLAlchemy
o'rami (12 soatlik oyna bo'yicha sanaydi).

Bu modul FAQAT LORRY guruhi uchun (settings.LORRY_CHANNEL_IDS). Boshqa
guruhlarda logist tushunchasi yo'q — hamma yuk to'g'ridan bazaga tushadi.
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.parser_service import CITY_ALIASES, _find_city_in, _norm_apostrophe
from db.models import LogistBlocklist, LorryListing

# ---------------------------------------------------------------------------
# Konfiguratsiya (oson sozlanadigan — kodni o'zgartirmasdan tuning qilinadi)
# ---------------------------------------------------------------------------

WINDOW_HOURS = 12     # rolling oyna
HARD_THRESHOLD = 4    # >= shuncha turli yo'nalish -> LOGIST
SOFT_THRESHOLD = 3    # == shuncha turli yo'nalish -> SUSPICIOUS
DIRECTIONAL = True    # yo'nalganlikni saqlash (A->B  !=  B->A)


class Label(str, enum.Enum):
    CARGO = "cargo"
    SUSPICIOUS = "suspicious"
    LOGIST = "logist"


@dataclass
class Decision:
    phone: Optional[str]
    label: Label
    distinct_routes: int
    window_hours: int = WINDOW_HOURS


# Yo'nalish/tuman shovqin so'zlari — shahar nomiga qo'shilib kelsa olib tashlanadi.
# "Andijon vest" -> "Andijon".
_CITY_NOISE = {
    "vest", "west", "g'arb", "garb", "sharq", "east", "shimol", "north",
    "janub", "south", "markaz", "center", "centr", "shahar", "shahri",
    "tuman", "tumani", "rayon", "район", "город", "gorod", "area", "hudud",
}

# Yo'nalish ajratuvchilari (sarlavha qatorida): ➡️ ⬅️ → ← « » -> <- — – - / >
_ROUTE_SEP_RE = re.compile(r"➡️?|⬅️?|→|←|«|»|->|<-|—|–|-|/|>")


# ---------------------------------------------------------------------------
# Sof funksiyalar (DB'siz)
# ---------------------------------------------------------------------------

def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """Raqamni +998XXXXXXXXX (bo'shliqsiz) ko'rinishiga keltiradi.

    Kiruvchi: +998901234567 / 998901234567 / 901234567 / 90 123 45 67.
    Parse bo'lmasa -> None (bunday e'lon klassifikatsiyaga kirmaydi).
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 9:                 # 901234567 -> mahalliy
        digits = "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return "+" + digits
    return None


def canonicalize_city(raw: Optional[str]) -> Optional[str]:
    """Shahar nomini kanonik lotin nomiga keltiradi (Kirill/lotin/shovqin bilan).

    "tashkent"/"ташкент"/"тошкент" -> "Toshkent"; "Andijon vest" -> "Andijon".
    Noma'lum shahar -> None (route hisobiga kirmaydi, sonini oshirmaydi).
    """
    if not raw:
        return None
    s = _norm_apostrophe(raw.lower())
    # Shovqin so'zlarni (vest, tuman, rayon...) olib tashlaymiz.
    tokens = [t for t in re.split(r"[\s,./|>–—-]+", s) if t and t not in _CITY_NOISE]
    cleaned = " ".join(tokens).strip()
    if not cleaned:
        return None
    # Alias jadvalidan eng birinchi uchragan kanonik shaharni qaytaradi.
    return _find_city_in(cleaned)


def parse_route(header: str) -> tuple[Optional[str], Optional[str]]:
    """Yo'nalishni SARLAVHA qatoridan ajratadi (tanadan emas).

    "Andijon ➡️ Toshkent" -> ("Andijon", "Toshkent")
    "ANDIJON - NUKUS"      -> ("Andijon", "Nukus")
    Ajratgich bo'lmasa -> (shahar, None). Har ikki tomon canonicalize qilinadi.
    """
    if not header:
        return (None, None)
    line = header.split("\n", 1)[0]
    m = _ROUTE_SEP_RE.search(line)
    if not m:
        return (canonicalize_city(line), None)
    left = line[: m.start()]
    right = line[m.end():]
    return (canonicalize_city(left), canonicalize_city(right))


def distinct_route_count(routes: list[tuple[Optional[str], Optional[str]]]) -> int:
    """Turli (origin, dest) juftliklari soni — faqat ikkala shahar ham aniq bo'lganlar.

    Directional: (A,B) va (B,A) alohida sanaladi. None bo'lgan tomonli
    yo'nalishlar umuman sanoqqa kirmaydi.
    """
    if DIRECTIONAL:
        pairs = {(o, d) for (o, d) in routes if o and d}
    else:
        pairs = {frozenset((o, d)) for (o, d) in routes if o and d}
    return len(pairs)


def classify_routes(routes: list[tuple[Optional[str], Optional[str]]]) -> Label:
    """Turli yo'nalishlar soniga qarab yorliq (sof, DB'siz yadro)."""
    n = distinct_route_count(routes)
    if n >= HARD_THRESHOLD:
        return Label.LOGIST
    if n == SOFT_THRESHOLD:
        return Label.SUSPICIOUS
    return Label.CARGO


# ---------------------------------------------------------------------------
# DB o'rami (SQLAlchemy)
# ---------------------------------------------------------------------------

async def _is_duplicate(session: AsyncSession, raw_text: str) -> bool:
    """Bir xil matn (repost) allaqachon yozilganmi — qayta sanamaslik uchun."""
    result = await session.execute(
        select(LorryListing.id).where(LorryListing.raw_text == raw_text).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def classify_phone_db(
    session: AsyncSession,
    phone_raw: str,
    *,
    now: Optional[datetime] = None,
    current_route: Optional[tuple[Optional[str], Optional[str]]] = None,
) -> Decision:
    """Telefonni 12 soatlik oyna bo'yicha klassifikatsiya qiladi.

    Oxirgi 12 soatdagi `lorry_listings` yozuvlaridan turli yo'nalishlarni
    yig'adi. `current_route` berilsa (hali yozilmagan bo'lsa) qo'shib sanaydi.
    """
    phone = normalize_phone(phone_raw)
    if phone is None:
        return Decision(phone=None, label=Label.CARGO, distinct_routes=0)

    now = now or datetime.utcnow()
    window_start = now - timedelta(hours=WINDOW_HOURS)

    result = await session.execute(
        select(LorryListing.origin_canon, LorryListing.dest_canon).where(
            LorryListing.phone_norm == phone,
            LorryListing.posted_at >= window_start,
        )
    )
    routes: list[tuple[Optional[str], Optional[str]]] = [(o, d) for (o, d) in result.all()]

    if current_route is not None:
        routes.append((canonicalize_city(current_route[0]), canonicalize_city(current_route[1])))

    return Decision(
        phone=phone,
        label=classify_routes(routes),
        distinct_routes=distinct_route_count(routes),
    )


async def evaluate_and_record(
    session: AsyncSession,
    *,
    phone_raw: Optional[str],
    origin: Optional[str],
    dest: Optional[str],
    source_group: str,
    raw_text: str,
    posted_at: Optional[datetime] = None,
) -> Optional[Decision]:
    """LORRY xabarini tarixga yozadi va telefonni klassifikatsiya qiladi.

    Qaytaradi:
      - `Decision` — baholandi (LOGIST/SUSPICIOUS/CARGO).
      - `None` — telefon parse bo'lmadi yoki dublikat (repost) -> e'tiborsiz.

    Har bir (yangi) LORRY xabari tarixga yoziladi — logist bo'lsa ham
    (sanash uchun kerak). Load bazasiga qo'shish/qo'shmaslik qarorini
    chaqiruvchi (channel_reader) `Decision.label` bo'yicha qiladi.
    """
    phone = normalize_phone(phone_raw)
    if phone is None:
        return None
    if await _is_duplicate(session, raw_text):
        return None

    posted_at = posted_at or datetime.utcnow()
    if posted_at.tzinfo is not None:
        posted_at = posted_at.replace(tzinfo=None)

    listing = LorryListing(
        phone_norm=phone,
        origin_canon=canonicalize_city(origin),
        dest_canon=canonicalize_city(dest),
        source_group=source_group,
        raw_text=raw_text,
        posted_at=posted_at,
    )
    session.add(listing)
    await session.flush()

    # Endi tarixda (shu yozuv ham) — oyna bo'yicha sanaymiz.
    decision = await classify_phone_db(session, phone, now=posted_at)
    listing.classification = decision.label.value
    await session.flush()
    return decision


# ---------------------------------------------------------------------------
# Qo'lda logist ro'yxati (manual blocklist) — admin qarori, algoritmdan ustun.
# Bu raqamdan kelgan yuk HECH QAYSI kanaldan bazaga tushmaydi.
# ---------------------------------------------------------------------------

# Jarayon ichida keshlanadi (channel_reader va admin handlerlar bir process'da).
_blocklist_cache: set[str] = set()


async def refresh_blocklist(session: AsyncSession) -> int:
    """Blocklist'ni DB'dan keshga qayta yuklaydi. Reader startup + har poll'da."""
    global _blocklist_cache
    result = await session.execute(select(LogistBlocklist.phone_norm))
    _blocklist_cache = {row[0] for row in result.all()}
    return len(_blocklist_cache)


def is_blocklisted(phone_raw: Optional[str]) -> bool:
    """Telefon qo'lda-logist ro'yxatidami (kesh bo'yicha, sinxron, tez)."""
    phone = normalize_phone(phone_raw)
    return phone is not None and phone in _blocklist_cache


async def add_logist_phone(
    session: AsyncSession, phone_raw: str, note: Optional[str] = None
) -> Optional[str]:
    """Raqamni qo'lda-logist ro'yxatiga qo'shadi. Normallashgan raqam yoki None."""
    phone = normalize_phone(phone_raw)
    if phone is None:
        return None
    if await session.get(LogistBlocklist, phone) is None:
        session.add(LogistBlocklist(phone_norm=phone, note=note))
        await session.flush()
    _blocklist_cache.add(phone)   # keshni darhol yangilaymiz
    return phone


async def remove_logist_phone(session: AsyncSession, phone_raw: str) -> Optional[str]:
    """Raqamni ro'yxatdan o'chiradi. Normallashgan raqam yoki None."""
    phone = normalize_phone(phone_raw)
    if phone is None:
        return None
    obj = await session.get(LogistBlocklist, phone)
    if obj is not None:
        await session.delete(obj)
        await session.flush()
    _blocklist_cache.discard(phone)
    return phone


async def list_logist_phones(session: AsyncSession) -> list[tuple[str, Optional[str]]]:
    """Ro'yxatdagi barcha raqamlar (yangi qo'shilgani birinchi)."""
    result = await session.execute(
        select(LogistBlocklist.phone_norm, LogistBlocklist.note)
        .order_by(LogistBlocklist.created_at.desc())
    )
    return [(r[0], r[1]) for r in result.all()]


async def purge_old_listings(session: AsyncSession, older_than_hours: int = 48) -> int:
    """Oynadan ancha eski (default 48s) tarix yozuvlarini o'chiradi — jadval shishmasin."""
    result = await session.execute(
        delete(LorryListing).where(
            LorryListing.posted_at < datetime.utcnow() - timedelta(hours=older_than_hours)
        )
    )
    return result.rowcount or 0


# ---------------------------------------------------------------------------
# Admin diagnostika va feedback
# ---------------------------------------------------------------------------

async def get_phone_stats(
    session: AsyncSession,
    phone_raw: str,
    *,
    hours: int = WINDOW_HOURS,
) -> dict:
    """Telefon bo'yicha logist tahlili — admin uchun (nima uchun bloklandi?).

    Qaytaradi:
        {
            "phone": "+998901234567",
            "window_hours": 12,
            "distinct_routes": 3,
            "label": "cargo",
            "routes": [("Toshkent", "Farg'ona"), ...],
            "in_blocklist": False,
        }
    """
    from bot.services.logist_service import is_blocklisted  # noqa: circular import workaround

    phone = normalize_phone(phone_raw)
    if phone is None:
        return {"error": "Telefon noto'g'ri format"}

    now = datetime.utcnow()
    window_start = now - timedelta(hours=hours)

    result = await session.execute(
        select(LorryListing.origin_canon, LorryListing.dest_canon, LorryListing.posted_at)
        .where(
            LorryListing.phone_norm == phone,
            LorryListing.posted_at >= window_start,
        )
        .order_by(LorryListing.posted_at.desc())
    )
    rows = result.all()
    routes = [(r[0], r[1]) for r in rows]
    decision = classify_routes(routes)

    return {
        "phone": phone,
        "window_hours": hours,
        "distinct_routes": distinct_route_count(routes),
        "label": decision.value,
        "routes": routes,
        "in_blocklist": is_blocklisted(phone),
    }


def record_logist_false_positive(phone_raw: str, note: str = "") -> None:
    """Logist sifatida noto'g'ri bloklangan raqamni feedback log ga yozadi.

    Admin `/unblock` buyrug'i berilganda chaqiriladi — keyinchalik threshold
    va window sozlash uchun ma'lumot yig'adi.

    Fayl: logs/parse_corrections.jsonl (parser_service bilan bitta fayl).
    """
    from bot.services.parser_service import record_parse_correction
    phone = normalize_phone(phone_raw)
    record_parse_correction(
        load_id=0,
        raw_text=f"phone={phone}",
        wrong_field="logist_fp",
        wrong_value="logist",
        correct_value="cargo",
    )
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "⚠️ Logist FP qayd etildi: tel=%s note=%s", phone, note
    )
