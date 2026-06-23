from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Load, LoadStatus

# Shahar/tuman variantlari (kichik harf) → kanonik lotin nomi.
# Kirill va lotin variantlar bir xil kanonik nomга moslanadi —
# shunda "Ташкент" va "Toshkent" bitta yo'nalish bo'ladi (bo'linmaydi).
CITY_ALIASES = {
    # 14 viloyat markazi + yirik shaharlar
    "toshkent": "Toshkent", "tashkent": "Toshkent", "тошкент": "Toshkent", "ташкент": "Toshkent",
    "samarqand": "Samarqand", "samarkand": "Samarqand", "самарканд": "Samarqand", "самарқанд": "Samarqand",
    "buxoro": "Buxoro", "buhoro": "Buxoro", "бухоро": "Buxoro", "бухара": "Buxoro",
    "namangan": "Namangan", "наманган": "Namangan",
    "andijon": "Andijon", "andijan": "Andijon", "андижон": "Andijon", "андижан": "Andijon",
    "farg'ona": "Farg'ona", "fargona": "Farg'ona", "fergana": "Farg'ona",
    "фаргона": "Farg'ona", "фарғона": "Farg'ona", "фергана": "Farg'ona",
    "nukus": "Nukus", "нукус": "Nukus",
    "qarshi": "Qarshi", "karshi": "Qarshi", "қарши": "Qarshi", "карши": "Qarshi",
    "termiz": "Termiz", "термиз": "Termiz", "термез": "Termiz",
    "jizzax": "Jizzax", "jizzakh": "Jizzax", "jizax": "Jizzax", "жиззах": "Jizzax", "джизак": "Jizzax",
    "navoiy": "Navoiy", "navoi": "Navoiy", "навоий": "Navoiy", "навои": "Navoiy",
    "urganch": "Urganch", "urgench": "Urganch", "урганч": "Urganch", "ургенч": "Urganch",
    "guliston": "Guliston", "gulistan": "Guliston", "гулистон": "Guliston", "гулистан": "Guliston",
    "nurafshon": "Nurafshon", "нурафшон": "Nurafshon",
    "xiva": "Xiva", "xeva": "Xiva", "хива": "Xiva",
    # Tez-tez uchraydigan tuman/shaharchalar (yuk yo'nalishlarida)
    "chirchiq": "Chirchiq", "чирчик": "Chirchiq",
    "angren": "Angren", "ангрен": "Angren",
    "olmaliq": "Olmaliq", "алмалык": "Olmaliq",
    "bekobod": "Bekobod", "бекабад": "Bekobod",
    "denov": "Denov", "денов": "Denov",
    "qoqon": "Qo'qon", "qo'qon": "Qo'qon", "kokand": "Qo'qon", "коканд": "Qo'qon", "қўқон": "Qo'qon",
    "marg'ilon": "Marg'ilon", "margilon": "Marg'ilon", "маргилан": "Marg'ilon",
    "chust": "Chust", "чуст": "Chust",
    "parkent": "Parkent", "паркент": "Parkent",
    "kibray": "Kibray", "кибрай": "Kibray",
    "oltiariq": "Oltiariq", "олтиарык": "Oltiariq",
    "shahrisabz": "Shahrisabz", "шахрисабз": "Shahrisabz",
    "quvasoy": "Quvasoy", "кувасай": "Quvasoy",
    "yangiyer": "Yangiyer", "янгиер": "Yangiyer",
    "guzar": "G'uzor", "g'uzor": "G'uzor", "guzor": "G'uzor",
    "uchquduq": "Uchquduq", "учкудук": "Uchquduq",
    "zarafshon": "Zarafshon", "зарафшан": "Zarafshon",
}

_WEIGHT_RE = re.compile(
    r"(\d+[.,]?\d*)\s*(tonna|tona|tonn|ton|тонна|тон|tn|тн|т|t)\b",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(
    r"(\d[\d\s]{0,9}(?:[.,]\d+)?)\s*(so[`']?m|so'm|sum|som|сум|сўм|сом|ming|минг|mln|млн)",
    re.IGNORECASE,
)
# Faqat 4–8 raqamli sonlar narx bo'la oladi — 9 raqamli telefon raqamlari chiqib ketadi.
_PRICE_BARE_RE = re.compile(r"\b(\d{4,8})\b")
# Telefon: +998XXXXXXXXX yoki yalang 9 raqamli mahalliy raqam.
_PHONE_RE = re.compile(r"\+?998\d{9}|\b\d{9}\b")
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
    """Matnda eng birinchi uchragan shaharning kanonik nomini qaytaradi."""
    tl = text.lower()
    best_idx = None
    best_city = None
    for alias, canon in CITY_ALIASES.items():
        idx = tl.find(alias)
        if idx != -1 and (best_idx is None or idx < best_idx):
            best_idx = idx
            best_city = canon
    return best_city


def _ordered_cities(text: str) -> list:
    """Matndagi shaharlar paydo bo'lish tartibida (kanonik, takrorsiz)."""
    tl = text.lower()
    hits = []
    for alias, canon in CITY_ALIASES.items():
        idx = tl.find(alias)
        if idx != -1:
            hits.append((idx, canon))
    hits.sort()
    out: list = []
    for _, canon in hits:
        if canon not in out:
            out.append(canon)
    return out


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

    # Fall back: barcha shaharlar paydo bo'lish tartibida
    cities = _ordered_cities(text)
    if len(cities) >= 2:
        return cities[0], cities[1]
    if len(cities) == 1:
        return cities[0], None
    return None, None


_DEST_CUT_RE = re.compile(r"[🚛📦☎️👤💰📍🔹✅🟨🟥🟢⚡️•\d\n]")


def extract_destination_freetext(text: str) -> Optional[str]:
    """LORRY formati uchun: "ORIGIN -> DEST 🚛..." dan DEST ni ajratadi.

    Ma'lum shaharlar ro'yxatiga bog'liq emas — har qanday shaharcha
    (Kattako'rgon, Urgut...) ni ham oladi. Ajratgich (->, -, →) dan keyingi
    matnni birinchi belgi/raqamgacha oladi.
    """
    m = _SEP_RE.search(text)
    if not m:
        return None
    right = text[m.end():]
    chunk = _DEST_CUT_RE.split(right, maxsplit=1)[0]
    dest = chunk.strip(" \t-–—:>.,").strip()
    if 2 <= len(dest) <= 25 and any(ch.isalpha() for ch in dest):
        return dest[:1].upper() + dest[1:].lower()
    return None


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
    for alias in CITY_ALIASES:
        cleaned = re.sub(re.escape(alias), "", cleaned, flags=re.IGNORECASE)
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
) -> Optional[Load]:
    from bot.services.load_service import get_or_create_route

    # Dublikat (repost) — bir xil matnli faol yuk allaqachon bo'lsa, saqlamaymiz.
    dup = await session.execute(
        select(Load.id)
        .where(
            Load.raw_text == raw_text,
            Load.status.in_([LoadStatus.open, LoadStatus.pending, LoadStatus.matched]),
        )
        .limit(1)
    )
    if dup.scalar_one_or_none() is not None:
        return None

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
