from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Load, LoadStatus

UZBEK_CITIES = [
    "Toshkent", "Samarqand", "Buxoro", "Namangan", "Andijon",
    "Farg'ona", "Nukus", "Qarshi", "Termiz", "Jizzax",
    "Navoiy", "Urganch", "Guliston", "Sirdaryo", "Shahrisabz",
]

_WEIGHT_RE = re.compile(
    r"(\d+[.,]?\d*)\s*(tonna|tonn|ton\b|t\b)",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(
    r"(\d[\d\s]{0,9}(?:[.,]\d+)?)\s*(so[`']?m|ming|mln|млн)",
    re.IGNORECASE,
)
_PRICE_BARE_RE = re.compile(r"(\d{4,})")  # bare large numbers (>= 1000)
_PHONE_RE = re.compile(r"\+?998\d{9}")
_SEP_RE = re.compile(r"[-–—→/]")

# Yuk turi kalit so'zlari → normallashtirilgan kategoriya.
# Kalit so'z matnda (kichik harfda) uchrasa, shu kategoriya qaytariladi.
CARGO_KEYWORDS = {
    # Aniqroq (multi-word) kalitlar yuqorida — umumiyroqdan oldin tekshiriladi.
    "muzlatilgan": "Muzlatilgan mahsulot",
    "qurilish": "Qurilish materiallari",
    "sement": "Qurilish materiallari",
    "g'isht": "Qurilish materiallari",
    "gisht": "Qurilish materiallari",
    "beton": "Qurilish materiallari",
    "armatura": "Qurilish materiallari",
    "metall": "Metall",
    "temir": "Metall",
    "oziq": "Oziq-ovqat",
    "ovqat": "Oziq-ovqat",
    "mahsulot": "Oziq-ovqat",
    "don": "Oziq-ovqat",
    "bug'doy": "Oziq-ovqat",
    "bugdoy": "Oziq-ovqat",
    "un ": "Oziq-ovqat",
    "gosht": "Oziq-ovqat",
    "go'sht": "Oziq-ovqat",
    "sut": "Oziq-ovqat",
    "meva": "Oziq-ovqat",
    "sabzavot": "Oziq-ovqat",
    "elektronika": "Elektronika",
    "texnika": "Elektronika",
    "maishiy": "Elektronika",
    "mebel": "Mebel",
    "kimyo": "Kimyo",
    "kimyoviy": "Kimyo",
    "paxta": "Paxta",
    "kiyim": "Kiyim-kechak",
    "mato": "Kiyim-kechak",
    "neft": "Neft mahsulotlari",
    "benzin": "Neft mahsulotlari",
    "gaz": "Neft mahsulotlari",
}

# Yuk turini aniqlashda e'tiborga olinmaydigan so'zlar (shovqin).
_CARGO_STOPWORDS = {
    "narx", "narxi", "tel", "telefon", "raqam", "dan", "ga", "uchun",
    "kerak", "kerakli", "bor", "yuk", "yuklar", "fura", "isuzu", "mashina",
    "kelishamiz", "kelishiladi", "kelishilgan", "som", "so'm", "sum",
    "ming", "mln", "tonna", "ton", "kg", "narxda", "haqida", "bilan",
    "yetkazib", "berish", "olib", "boring",
}


@dataclass
class ParsedLoad:
    origin: Optional[str]
    destination: Optional[str]
    cargo_type: Optional[str]
    weight_t: Optional[float]
    price: Optional[float]
    contact: Optional[str]
    confidence: float  # 0.0 – 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_city_in(text: str) -> Optional[str]:
    tl = text.lower()
    for city in UZBEK_CITIES:
        if city.lower() in tl:
            return city
    return None


def _extract_route(text: str):
    sep = _SEP_RE.search(text)
    if sep:
        left = text[: sep.start()].strip()
        # destination is first word/phrase after separator up to comma
        right = text[sep.end() :].split(",")[0].strip()
        o = _find_city_in(left)
        d = _find_city_in(right)
        if o and d and o != d:
            return o, d

    # Fall back: find all cities in order of appearance
    tl = text.lower()
    hits = []
    for city in UZBEK_CITIES:
        idx = tl.find(city.lower())
        if idx != -1:
            hits.append((idx, city))
    hits.sort()
    cities = [c for _, c in hits]
    if len(cities) >= 2:
        return cities[0], cities[1]
    if len(cities) == 1:
        return cities[0], None
    return None, None


def _extract_weight(text: str) -> Optional[float]:
    m = _WEIGHT_RE.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


def _extract_price(text: str) -> Optional[float]:
    # Telefon raqamini olib tashlaymiz — aks holda uning raqamlari narx
    # sifatida noto'g'ri o'qiladi (masalan 998901112233).
    text = _PHONE_RE.sub(" ", text)

    # First try patterns with explicit currency unit
    for m in _PRICE_RE.finditer(text):
        raw = m.group(1).replace(" ", "").replace(",", ".")
        unit = m.group(2).lower().replace("`", "'")
        try:
            value = float(raw)
        except ValueError:
            continue
        if value <= 0:
            continue
        if "ming" in unit:
            value *= 1_000
        elif "mln" in unit or "млн" in unit:
            value *= 1_000_000
        return value

    # Fall back: bare large number (likely a price in so'm)
    for m in _PRICE_BARE_RE.finditer(text):
        try:
            value = float(m.group(1))
        except ValueError:
            continue
        # Exclude numbers that match weight (< 500 without unit are probably weights)
        if value >= 10_000:
            return value

    return None


def _extract_contact(text: str) -> Optional[str]:
    m = _PHONE_RE.search(text)
    return m.group(0) if m else None


def _extract_cargo_type(text: str) -> Optional[str]:
    tl = text.lower()

    # 1) Kalit so'z bo'yicha aniq kategoriya
    for keyword, category in CARGO_KEYWORDS.items():
        if keyword in tl:
            return category

    # 2) Fallback: shahar/vazn/narx/telefonni olib tashlab, qolgan
    #    "ma'noli" so'zlarni qaytaramiz (stopword'larsiz).
    cleaned = text
    cleaned = _PHONE_RE.sub("", cleaned)
    cleaned = _WEIGHT_RE.sub("", cleaned)
    cleaned = _PRICE_RE.sub("", cleaned)
    cleaned = _PRICE_BARE_RE.sub("", cleaned)
    for city in UZBEK_CITIES:
        cleaned = re.sub(re.escape(city), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[-–—→/,;:+\d]+", " ", cleaned)

    tokens = [
        t.strip()
        for t in cleaned.split()
        if len(t.strip()) >= 3 and t.strip().lower() not in _CARGO_STOPWORDS
    ]
    if tokens:
        return " ".join(tokens[:4])
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_with_regex(text: str) -> ParsedLoad:
    origin, destination = _extract_route(text)
    weight_t = _extract_weight(text)
    price = _extract_price(text)
    contact = _extract_contact(text)
    cargo_type = _extract_cargo_type(text)

    fields = [origin, destination, cargo_type, weight_t, price]
    filled = sum(1 for f in fields if f is not None)
    confidence = filled / len(fields)

    return ParsedLoad(
        origin=origin,
        destination=destination,
        cargo_type=cargo_type,
        weight_t=weight_t,
        price=price,
        contact=contact,
        confidence=confidence,
    )


async def parse_with_llm(text: str, openai_api_key: str) -> ParsedLoad:
    if not openai_api_key:
        raise NotImplementedError("OpenAI API key sozlanmagan.")
    try:
        import httpx
    except ImportError:
        raise NotImplementedError("httpx o'rnatilmagan: pip install httpx")

    system_prompt = (
        "Extract logistics load info from Uzbek/Russian text. "
        "Return JSON only with keys: "
        '{"origin": string|null, "destination": string|null, '
        '"cargo_type": string|null, "weight_t": number|null, '
        '"price_uzs": number|null, "contact": string|null}'
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_api_key}"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 200,
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
            content = json.loads(resp.json()["choices"][0]["message"]["content"])

        origin = content.get("origin") or None
        destination = content.get("destination") or None
        cargo_type = content.get("cargo_type") or None
        wt = content.get("weight_t")
        pr = content.get("price_uzs")
        contact = content.get("contact") or None

        weight_t = float(wt) if wt is not None else None
        price = float(pr) if pr is not None else None

        fields = [origin, destination, cargo_type, weight_t, price]
        filled = sum(1 for f in fields if f is not None)
        confidence = filled / len(fields)

        return ParsedLoad(
            origin=origin,
            destination=destination,
            cargo_type=cargo_type,
            weight_t=weight_t,
            price=price,
            contact=contact,
            confidence=confidence,
        )
    except Exception:
        return ParsedLoad(None, None, None, None, None, None, confidence=0.0)


async def parse_load(text: str, openai_api_key: str = "") -> ParsedLoad:
    regex_result = parse_with_regex(text)
    if regex_result.confidence >= 0.7:
        return regex_result
    try:
        llm_result = await parse_with_llm(text, openai_api_key)
        if llm_result.confidence > regex_result.confidence:
            return llm_result
    except NotImplementedError:
        pass
    return regex_result


async def save_parsed_load(
    session: AsyncSession,
    parsed: ParsedLoad,
    raw_text: str,
    source_channel: str,
    auto_approve_threshold: float = 0.85,
) -> Load:
    from bot.services.load_service import get_or_create_route

    route_id = None
    if parsed.origin and parsed.destination:
        route = await get_or_create_route(session, parsed.origin, parsed.destination)
        route_id = route.id

    status = (
        LoadStatus.open
        if parsed.confidence >= auto_approve_threshold
        else LoadStatus.pending
    )

    load = Load(
        source_channel=source_channel,
        raw_text=raw_text,
        route_id=route_id,
        cargo_type=parsed.cargo_type,
        weight_t=Decimal(str(round(parsed.weight_t, 2))) if parsed.weight_t else None,
        price=Decimal(str(round(parsed.price, 2))) if parsed.price else None,
        status=status,
    )
    session.add(load)
    await session.flush()
    return load
