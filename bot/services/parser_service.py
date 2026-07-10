from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Load, LoadStatus, VehicleType

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
    # Imlo/lahja variantlari (guruhlarda tez uchraydi)
    "toshken": "Toshkent", "тошкен": "Toshkent", "towkent": "Toshkent", "тошкан": "Toshkent",
    "кукон": "Qo'qon", "куқон": "Qo'qon", "qoqan": "Qo'qon",
    "bekabod": "Bekobod", "бекобод": "Bekobod", "bekobot": "Bekobod",
    "маргилон": "Marg'ilon", "marģilon": "Marg'ilon",
    # Viloyat nomlari (shahar emas — matnda viloyat yozilsa ham tushunish uchun)
    "sirdaryo": "Sirdaryo", "сирдарё": "Sirdaryo", "сырдарья": "Sirdaryo",
    "surxondaryo": "Surxondaryo", "сурхондарё": "Surxondaryo", "surxondaryo'": "Surxondaryo",
    "сурхандарья": "Surxondaryo", "сурхандар": "Surxondaryo",
    "xorazm": "Xorazm", "horazm": "Xorazm", "хоразм": "Xorazm", "хорезм": "Xorazm",
    "qashqadaryo": "Qashqadaryo", "кашкадарё": "Qashqadaryo", "қашқадарё": "Qashqadaryo",
    "кашкадарья": "Qashqadaryo",
    "qoraqalpog": "Qoraqalpog'iston", "коракалпог": "Qoraqalpog'iston",
    "қорақалпоғ": "Qoraqalpog'iston", "каракалпак": "Qoraqalpog'iston",
    # Toshkent viloyati tumanlari
    "sergeli": "Sergeli", "sergili": "Sergeli", "сергели": "Sergeli", "сергили": "Sergeli",
    "piskent": "Piskent", "пискент": "Piskent",
    "bo'ka": "Bo'ka", "boka": "Bo'ka", "бука": "Bo'ka", "бўка": "Bo'ka",
    "chinoz": "Chinoz", "чиноз": "Chinoz",
    "ohangaron": "Ohangaron", "охангарон": "Ohangaron", "ахангаран": "Ohangaron",
    "yangiyo'l": "Yangiyo'l", "yangiyul": "Yangiyo'l", "янгийул": "Yangiyo'l", "янгийўл": "Yangiyo'l",
    "keles": "Keles", "келес": "Keles",
    # Farg'ona viloyati
    "rishton": "Rishton", "риштон": "Rishton",
    "beshariq": "Beshariq", "бешарик": "Beshariq", "бешариқ": "Beshariq",
    "buvayda": "Buvayda", "бувайда": "Buvayda",
    "bog'dod": "Bog'dod", "bogdod": "Bog'dod", "богдод": "Bog'dod", "боғдод": "Bog'dod",
    "yozyovon": "Yozyovon", "ёзёвон": "Yozyovon",
    "quva": "Quva", "қува": "Quva", "кува": "Quva",
    "uchko'prik": "Uchko'prik", "uchkuprik": "Uchko'prik", "учкуприк": "Uchko'prik",
    # Andijon viloyati
    "shahrixon": "Shahrixon", "shaxrixon": "Shahrixon", "шахрихон": "Shahrixon",
    "asaka": "Asaka", "асака": "Asaka",
    "xonobod": "Xonobod", "хонобод": "Xonobod",
    "paxtaobod": "Paxtaobod", "пахтаобод": "Paxtaobod",
    "xo'jaobod": "Xo'jaobod", "xujaobod": "Xo'jaobod", "хужаобод": "Xo'jaobod", "хўжаобод": "Xo'jaobod",
    "qorasuv": "Qorasuv", "корасув": "Qorasuv", "қорасув": "Qorasuv",
    "marhamat": "Marhamat", "мархамат": "Marhamat",
    # Namangan viloyati
    "chortoq": "Chortoq", "чорток": "Chortoq", "чортоқ": "Chortoq", "chortoq'": "Chortoq",
    "kosonsoy": "Kosonsoy", "косонсой": "Kosonsoy",
    "norin": "Norin", "норин": "Norin",
    "uchqo'rg'on": "Uchqo'rg'on", "uchkurgan": "Uchqo'rg'on", "учкурган": "Uchqo'rg'on",
    "to'raqo'rg'on": "To'raqo'rg'on", "turakurgan": "To'raqo'rg'on", "туракурган": "To'raqo'rg'on",
    "pop tumani": "Pop", "попдан": "Pop", "popdan": "Pop",
    # Samarqand viloyati
    "urgut": "Urgut", "ургут": "Urgut",
    "kattaqo'rg'on": "Kattaqo'rg'on", "kattakurgan": "Kattaqo'rg'on",
    "каттакургон": "Kattaqo'rg'on", "каттақўрғон": "Kattaqo'rg'on", "каттакурган": "Kattaqo'rg'on",
    "jomboy": "Jomboy", "жомбой": "Jomboy",
    "bulung'ur": "Bulung'ur", "bulungur": "Bulung'ur", "булунгур": "Bulung'ur",
    # Buxoro viloyati
    "g'ijduvon": "G'ijduvon", "gijduvon": "G'ijduvon", "гиждувон": "G'ijduvon",
    "kogon": "Kogon", "когон": "Kogon", "kagan": "Kogon", "каган": "Kogon",
    "qorako'l": "Qorako'l", "korakul": "Qorako'l", "коракул": "Qorako'l",
    "vobkent": "Vobkent", "вобкент": "Vobkent",
    # Qashqadaryo viloyati
    "koson": "Koson", "косон": "Koson",
    "kitob": "Kitob", "китоб": "Kitob",
    "muborak": "Muborak", "муборак": "Muborak",
    "qamashi": "Qamashi", "камаши": "Qamashi", "қамаши": "Qamashi",
    # Surxondaryo viloyati
    "sho'rchi": "Sho'rchi", "shurchi": "Sho'rchi", "шурчи": "Sho'rchi", "шўрчи": "Sho'rchi",
    "jarqo'rg'on": "Jarqo'rg'on", "jarkurgan": "Jarqo'rg'on", "жаркургон": "Jarqo'rg'on",
    "boysun": "Boysun", "бойсун": "Boysun",
    "qumqo'rg'on": "Qumqo'rg'on", "кумкургон": "Qumqo'rg'on",
    "sherobod": "Sherobod", "шеробод": "Sherobod",
    # Xorazm viloyati
    "gurlan": "Gurlan", "гурлан": "Gurlan",
    "xonqa": "Xonqa", "xonka": "Xonqa", "хонка": "Xonqa", "хонқа": "Xonqa",
    "shovot": "Shovot", "шовот": "Shovot",
    "hazorasp": "Hazorasp", "hazarasp": "Hazorasp", "хазорасп": "Hazorasp",
    # Qoraqalpog'iston
    "beruniy": "Beruniy", "беруний": "Beruniy",
    "to'rtko'l": "To'rtko'l", "turtkul": "To'rtko'l", "турткул": "To'rtko'l", "тўрткўл": "To'rtko'l",
    "qo'ng'irot": "Qo'ng'irot", "kungirot": "Qo'ng'irot", "кунгирот": "Qo'ng'irot",
    "кунград": "Qo'ng'irot", "qo'ngg'irot": "Qo'ng'irot",
    "xo'jayli": "Xo'jayli", "xujayli": "Xo'jayli", "ходжейли": "Xo'jayli", "хўжайли": "Xo'jayli",
    "chimboy": "Chimboy", "чимбой": "Chimboy",
    # Jizzax viloyati
    "zomin": "Zomin", "зомин": "Zomin",
    "paxtakor": "Paxtakor", "пахтакор": "Paxtakor",
    "do'stlik": "Do'stlik", "dustlik": "Do'stlik", "дустлик": "Do'stlik",
    "g'allaorol": "G'allaorol", "gallaorol": "G'allaorol", "галлаорол": "G'allaorol",
    # Sirdaryo viloyati
    "boyovut": "Boyovut", "боёвут": "Boyovut",
    "xovos": "Xovos", "xavos": "Xovos", "ховос": "Xovos", "хавос": "Xovos",
    # Navoiy viloyati
    "nurota": "Nurota", "нурота": "Nurota",
    "qiziltepa": "Qiziltepa", "кизилтепа": "Qiziltepa",
}

# Kanonik shahar/tuman → viloyat (menyu LORRY kabi viloyat bo'yicha guruhlanadi).
# Ro'yxatda yo'q nom — o'zi viloyat markazi/nomi sifatida qoladi.
CITY_TO_VILOYAT = {
    "Chirchiq": "Toshkent", "Angren": "Toshkent", "Olmaliq": "Toshkent", "Bekobod": "Toshkent",
    "Parkent": "Toshkent", "Kibray": "Toshkent", "Nurafshon": "Toshkent", "Sergeli": "Toshkent",
    "Piskent": "Toshkent", "Bo'ka": "Toshkent", "Chinoz": "Toshkent", "Ohangaron": "Toshkent",
    "Yangiyo'l": "Toshkent", "Keles": "Toshkent",
    "Qo'qon": "Farg'ona", "Marg'ilon": "Farg'ona", "Quvasoy": "Farg'ona", "Oltiariq": "Farg'ona",
    "Rishton": "Farg'ona", "Beshariq": "Farg'ona", "Buvayda": "Farg'ona", "Bog'dod": "Farg'ona",
    "Yozyovon": "Farg'ona", "Quva": "Farg'ona", "Uchko'prik": "Farg'ona",
    "Shahrixon": "Andijon", "Asaka": "Andijon", "Xonobod": "Andijon", "Paxtaobod": "Andijon",
    "Xo'jaobod": "Andijon", "Qorasuv": "Andijon", "Marhamat": "Andijon",
    "Chust": "Namangan", "Chortoq": "Namangan", "Kosonsoy": "Namangan", "Norin": "Namangan",
    "Uchqo'rg'on": "Namangan", "To'raqo'rg'on": "Namangan", "Pop": "Namangan",
    "Urgut": "Samarqand", "Kattaqo'rg'on": "Samarqand", "Jomboy": "Samarqand", "Bulung'ur": "Samarqand",
    "G'ijduvon": "Buxoro", "Kogon": "Buxoro", "Qorako'l": "Buxoro", "Vobkent": "Buxoro",
    "Qarshi": "Qashqadaryo", "Shahrisabz": "Qashqadaryo", "Koson": "Qashqadaryo",
    "Kitob": "Qashqadaryo", "Muborak": "Qashqadaryo", "Qamashi": "Qashqadaryo", "G'uzor": "Qashqadaryo",
    "Termiz": "Surxondaryo", "Denov": "Surxondaryo", "Sho'rchi": "Surxondaryo",
    "Jarqo'rg'on": "Surxondaryo", "Boysun": "Surxondaryo", "Qumqo'rg'on": "Surxondaryo",
    "Sherobod": "Surxondaryo",
    "Urganch": "Xorazm", "Xiva": "Xorazm", "Gurlan": "Xorazm", "Xonqa": "Xorazm",
    "Shovot": "Xorazm", "Hazorasp": "Xorazm",
    "Nukus": "Qoraqalpog'iston", "Beruniy": "Qoraqalpog'iston", "To'rtko'l": "Qoraqalpog'iston",
    "Qo'ng'irot": "Qoraqalpog'iston", "Xo'jayli": "Qoraqalpog'iston", "Chimboy": "Qoraqalpog'iston",
    "Zomin": "Jizzax", "Paxtakor": "Jizzax", "Do'stlik": "Jizzax", "G'allaorol": "Jizzax",
    "Guliston": "Sirdaryo", "Yangiyer": "Sirdaryo", "Boyovut": "Sirdaryo", "Xovos": "Sirdaryo",
    "Uchquduq": "Navoiy", "Zarafshon": "Navoiy", "Nurota": "Navoiy", "Qiziltepa": "Navoiy",
}

def to_viloyat(city: Optional[str]) -> Optional[str]:
    """Kichik shahar/tumanni o'z viloyatiga aylantiradi.

    Faqat ORIGIN uchun ishlatiladi — viloyat menyusi LORRY kabi toza
    (~14 tugma) bo'lib qolishi uchun. Destination granular qoladi.
    """
    if not city:
        return city
    return CITY_TO_VILOYAT.get(city, city)


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
# Telefon: +998 90 123 45 67 / 998901234567 / 90 123 45 67 / 901234567 / 94 1981464.
# (?<!\d)/(?!\d) — \b o'rniga: harfga bevosita yopishgan raqamni ham topadi
# (masalan "тел500033100"), lekin uzun raqam ketma-ketligi ichidan bo'lak olmaydi.
_PHONE_RE = re.compile(
    r"\+?998[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"  # +998 XX XXX XX XX
    r"|(?<!\d)\d{2}[\s\-]\d{3}[\s\-]\d{2}[\s\-]\d{2}(?!\d)"   # XX XXX XX XX (mahalliy)
    r"|(?<!\d)\d{2}[\s\-]\d{7}(?!\d)"                          # XX XXXXXXX (bo'sh joysiz qism)
    r"|(?<!\d)\d{9}(?!\d)"                                     # XXXXXXXXX (yalang 9)
)
# Ajratgich: emoji strelkalar (➡️ ⬅️) va oddiy belgilar.
_SEP_RE = re.compile(r"➡️?|⬅️?|→|«|»|[-–—/><]")

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
    contact: Optional[str]      # normallashtirilgan: +998 XX XXX XX XX
    note: Optional[str]         # yuk haqida izoh (tur, vazn, talab)
    confidence: float  # 0.0 – 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_apostrophe(s: str) -> str:
    """Apostrof variantlarini (’ ʼ `) bitta ' ga keltiradi — Qo'qon/Qo'qon birlashadi."""
    return s.replace("’", "'").replace("ʼ", "'").replace("`", "'")


def _find_city_in(text: str) -> Optional[str]:
    """Matnda eng birinchi uchragan shaharning kanonik nomini qaytaradi."""
    tl = _norm_apostrophe(text.lower())
    best_idx = None
    best_city = None
    for alias, canon in CITY_ALIASES.items():
        idx = tl.find(_norm_apostrophe(alias))
        if idx != -1 and (best_idx is None or idx < best_idx):
            best_idx = idx
            best_city = canon
    return best_city


def _ordered_cities(text: str) -> list:
    """Matndagi shaharlar paydo bo'lish tartibida (kanonik, takrorsiz)."""
    tl = _norm_apostrophe(text.lower())
    hits = []
    for alias, canon in CITY_ALIASES.items():
        idx = tl.find(_norm_apostrophe(alias))
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


_DEST_CUT_RE = re.compile(r"[🚚🚛📦☎️📞👤💰📍🔹✅🟨🟥🟢⚡️•,;\d\n]")


def extract_destination_freetext(text: str) -> Optional[str]:
    """LORRY formati uchun: "ORIGIN ➡️ DEST 🚛..." dan DEST ni ajratadi.

    Avval ajratgichdan keyin ma'lum shaharni qidiradi (Buxoro, Qo'qon...).
    Topilmasa — noma'lum shaharcha (Kattako'rgon, Urgut) uchun birinchi
    toza so'zni oladi.
    """
    m = _SEP_RE.search(text)
    if not m:
        return None
    right = text[m.end():]

    # 1) Ma'lum shahar bo'lsa — kanonik nomni qaytaramiz (eng ishonchli).
    city = _find_city_in(right)
    if city:
        return city

    # 2) Noma'lum shaharcha — birinchi belgi/raqamgacha, faqat 1-2 so'z.
    chunk = _DEST_CUT_RE.split(right, maxsplit=1)[0]
    dest = " ".join(chunk.strip(" \t-–—:>.,").split()[:2])
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


def _extract_contact(text: str) -> Optional[str]:
    """Matndan telefon raqamini topib, normallashtirib qaytaradi."""
    m = _PHONE_RE.search(text)
    return normalize_phone(m.group(0)) if m else None


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """Raqamni +998XXXXXXXXX (bo'shliqsiz) ko'rinishiga keltiradi.

    Kiruvchi: +998901234567 / 998901234567 / 901234567 / 90 123 45 67.
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 9:            # 901234567 → mahalliy
        digits = "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return "+" + digits
    return None


# Bezak emoji va belgilar — izohni tozalashda olib tashlanadi.
_NOISE_RE = re.compile(r"[🚚🚛📦☎️📞📱💬👤💰📍💵🚗🔹✅🟨🟥🟢⚡️•*_➡️⬅️#|]+")
# @mention (@Muhammad, @vodiystar7) — izohda keraksiz.
_MENTION_RE = re.compile(r"@\w+")
# Yorliq so'zlar (izohda ma'no bermaydi) — "tel:", "narx", "kontakt"...
_NOTE_LABEL_RE = re.compile(
    r"\b(tel|telefon|aloqa|murojaat|narx|narxi|raqam|kontakt|контакт)\b\.?:?",
    re.IGNORECASE,
)
# Yalang son (ID, narx, masofa) — vazndan tashqari 3+ raqamli sonlar shovqin.
_BARE_NUM_RE = re.compile(r"\b\d{3,}\b(?!\s*(?:tonna|tona|ton|kg))", re.IGNORECASE)
# O'zbekcha kelishik qo'shimchasi — shahar nomiga bevosita yopishgan bo'lsa
# ham birga olib tashlanadi (masalan "Namangandan", "Buxoroga").
_UZ_SUFFIX_RE = r"(?:dan|dagi|ga|ka|qa|da|дан|даги|га|ка|қа|да)?"
# LORRY bot shovqini: markdown link, URL, footer qatorlari, hashtag/ID.
_MDLINK_RE = re.compile(r"\[[^\]]*\]\([^)]*\)")         # [Контакт](tg://user?id=..)
_URL_RE = re.compile(r"(?:https?://|tg://|t\.me/)\S+")  # linklar
_FOOTER_RE = re.compile(r"^.*(?:🇺🇿|🤖|@\w+bot).*$", re.MULTILINE)  # footer qatorlari
_HASHTAG_RE = re.compile(r"#\S+")                       # #11453823, #SURXONDARYO
# LORRY '💰 ...' qatori — to'lov/narx (Naqd, Karta, 130 | Naqd, 8 000 000 sum).
_PRICE_LINE_RE = re.compile(r"💰\s*([^\n]+)")


def extract_price_line(text: str) -> Optional[str]:
    """Narx/to'lov matnini qaytaradi — LORRY '💰' qatoridan (yoki valyutali summa).

    Raqamni "taxmin qilmaydi" — faqat aniq yozilganini oladi. Shu sabab
    hech qachon noto'g'ri narx chiqmaydi. Masalan: "Naqd", "130 Naqd",
    "8 000 000 sum".
    """
    m = _PRICE_LINE_RE.search(text)
    if m:
        val = re.sub(r"\s*\|\s*", ", ", m.group(1))   # "130 | Naqd" -> "130, Naqd"
        val = re.sub(r"\s+", " ", val).strip(" ,.;:-")
        return val[:40] or None
    # Erkin format uchun: aniq valyutali summa (masalan "500 000 so'm")
    m2 = _PRICE_RE.search(text)
    if m2:
        return re.sub(r"\s+", " ", m2.group(0)).strip()
    return None


def extract_note(text: str) -> Optional[str]:
    """Yuk haqidagi izoh: tur, vazn, talablar — bitta qatorga jamlaydi.

    Telefon, shahar nomlari, narx, linklar va footer olib tashlanadi.
    Qolgan "ma'noli" matn izoh sifatida qaytariladi.
    """
    # LORRY tuzilmali xabarida 1-qator yo'nalish (masalan "ANDIJON -> ...") —
    # u alohida ko'rsatiladi, izohdan tashlaymiz. Bir qatorli xabarda tegmaymiz.
    lines = text.split("\n")
    if len(lines) > 1 and _SEP_RE.search(lines[0]):
        lines = lines[1:]
    # '💰' (to'lov/narx) qatorini ham izohdan chiqaramiz — u alohida ko'rsatiladi.
    lines = [ln for ln in lines if "💰" not in ln]
    t = "\n".join(lines)

    t = _MDLINK_RE.sub(" ", t)         # [Контакт](tg://...) — butunlay
    t = _URL_RE.sub(" ", t)            # linklar
    t = _FOOTER_RE.sub(" ", t)         # 🇺🇿 / 🤖 / @bot footer qatorlari
    t = _HASHTAG_RE.sub(" ", t)        # #11453823, #SURXONDARYO
    t = _MENTION_RE.sub(" ", t)        # @Muhammad, @vodiystar7
    t = _PHONE_RE.sub(" ", t)
    t = _NOISE_RE.sub(" ", t)
    t = _PRICE_RE.sub(" ", t)          # narxni izohdan chiqarib tashlaymiz
    t = _NOTE_LABEL_RE.sub(" ", t)     # "tel:", "narx" kabi yorliqlarni olib tashlaymiz
    t = _BARE_NUM_RE.sub(" ", t)       # ID/narx/masofa — yalang sonlar
    for alias in CITY_ALIASES:          # shahar nomlarini (qo'shimchasi bilan) olib tashlaymiz
        t = re.sub(re.escape(alias) + _UZ_SUFFIX_RE, " ", t, flags=re.IGNORECASE)
    t = _SEP_RE.sub(" ", t)
    t = re.sub(r"[ \t]*\n[ \t\n]*", ", ", t)   # ko'p qatorlarni verguldan ajratamiz
    t = re.sub(r"\s+", " ", t).strip(" ,.;:|-")
    t = re.sub(r"(?:,\s*){2,}", ", ", t)       # ketma-ket vergullarni birlashtiramiz
    return t[:120] if len(t) >= 2 else None


def extract_body(text: str, phone: Optional[str] = None) -> Optional[str]:
    """Manba xabaridagi BARCHA ma'lumot — yo'nalish va telefondan tashqari.

    Shablonning 3-qatori uchun (1-qator: yo'nalish, 2-qator: telefon,
    3-qator: shu). `extract_note` dan yumshoqroq — narx, vazn, yuk turi,
    talablar SAQLANADI; faqat yo'nalish sarlavhasi, telefon, linklar,
    footer, mention va hashtaglar olib tashlanadi.
    """
    lines = text.split("\n")
    # 1-qator yo'nalish sarlavhasi bo'lsa (ajratgichli, masalan "ANDIJON ➡️ ...") — tashlaymiz.
    if lines and _SEP_RE.search(lines[0]):
        lines = lines[1:]

    kept: list[str] = []
    for ln in lines:
        # Footer qatori (🇺🇿 / 🤖 / @...bot) — butun qatorni tashlaymiz.
        if re.search(r"🇺🇿|🤖|@\w+bot", ln):
            continue
        s = _MDLINK_RE.sub(" ", ln)     # [Kontakt](tg://...) — butunlay
        s = _URL_RE.sub(" ", s)         # linklar
        s = _HASHTAG_RE.sub(" ", s)     # #11453823
        s = _MENTION_RE.sub(" ", s)     # @user
        s = _PHONE_RE.sub(" ", s)       # telefon (2-qatorda alohida)
        s = _NOTE_LABEL_RE.sub(" ", s)  # "tel:", "aloqa", "raqam" yorliqlari
        s = re.sub(r"[*_`📞☎️📱👤🔹]+", " ", s)   # markdown/kontakt bezaklari
        s = re.sub(r"\s+", " ", s).strip(" ,.;:|-•")
        # Ma'noli belgi bo'lmasa (faqat emoji/tinish) — tashlaymiz.
        if s and re.search(r"[0-9A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ]", s):
            kept.append(s)

    body = ", ".join(kept)
    body = re.sub(r"(?:,\s*){2,}", ", ", body).strip(" ,.;:|-")
    return body[:300] if body else None


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
    contact = _extract_contact(text)
    cargo_type = _extract_cargo_type(text)
    note = extract_note(text)

    fields = [origin, destination, cargo_type, weight_t]
    filled = sum(1 for f in fields if f is not None)
    confidence = filled / len(fields)

    return ParsedLoad(
        origin=origin,
        destination=destination,
        cargo_type=cargo_type,
        weight_t=weight_t,
        contact=contact,
        note=note,
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
        contact = normalize_phone(content.get("contact")) or None

        weight_t = float(wt) if wt is not None else None
        note = extract_note(text)

        fields = [origin, destination, cargo_type, weight_t]
        filled = sum(1 for f in fields if f is not None)
        confidence = filled / len(fields)

        return ParsedLoad(
            origin=origin,
            destination=destination,
            cargo_type=cargo_type,
            weight_t=weight_t,
            contact=contact,
            note=note,
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


_ISUZU_KEYWORDS = ("isuzu", "isyzi", "isuzi", "исузи", "изузи", "усузи", "исузу", "исузий")
_FURA_KEYWORDS = ("fura", "фура")
# Isuzudan kichik yuk mashinalari: Hyundai Porter, labo, damas va sh.k.
_KICHIK_KEYWORDS = (
    "hyundai", "xyundai", "хундай", "хёндай", "хендай",
    "porter", "портер", "portor",
    "labo", "лабо",
    "damas", "дамас", "damask",
    "kichik mashina", "kichik yuk", "kichkina",
)

KICHIK_MAX_WEIGHT_T = 2   # <=2 tonna  -> Kichik (Porter/labo)
ISUZU_MAX_WEIGHT_T = 10   # 2–10 tonna -> Isuzu
FURA_MAX_WEIGHT_T = 30    # 10–30 tonna -> Fura


def classify_vehicle(text: str, weight_t: Optional[float]) -> VehicleType:
    """Kichik / Isuzu / Fura toifasiga ajratadi.

    Matnda mashina turi ANIQ yozilgan bo'lsa — shuni oladi (vazndan qat'i
    nazar). Aks holda vazn bo'yicha: <=2t Kichik, <=10t Isuzu, >10t Fura.
    Hech biri yo'q bo'lsa — Fura (bu guruhlarda asosiy oqim shu).
    """
    tl = text.lower()
    if any(k in tl for k in _KICHIK_KEYWORDS):
        return VehicleType.kichik
    if any(k in tl for k in _ISUZU_KEYWORDS):
        return VehicleType.isuzu
    if any(k in tl for k in _FURA_KEYWORDS):
        return VehicleType.fura
    if weight_t is not None and weight_t <= KICHIK_MAX_WEIGHT_T:
        return VehicleType.kichik
    if weight_t is not None and weight_t <= ISUZU_MAX_WEIGHT_T:
        return VehicleType.isuzu
    return VehicleType.fura


async def save_parsed_load(
    session: AsyncSession,
    parsed: ParsedLoad,
    raw_text: str,
    source_channel: str,
    auto_approve_threshold: float = 0.85,
    posted_at: Optional[datetime] = None,
) -> Optional[Load]:
    from bot.services.load_service import get_or_create_route

    # Dublikat (repost) — bir xil matn ilgari kelgan bo'lsa, qayta saqlamaymiz.
    # Status'dan qat'i nazar: aks holda bot qayta ishga tushganda backfill
    # logist deb bekor qilingan (cancelled) eski xabarlarni qayta tiriltiradi.
    dup = await session.execute(
        select(Load.id).where(Load.raw_text == raw_text).limit(1)
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
        contact_phone=parsed.contact,
        note=parsed.note,
        vehicle_type=classify_vehicle(raw_text, parsed.weight_t),
        status=status,
    )
    if posted_at is not None:
        load.posted_at = posted_at
    session.add(load)
    await session.flush()

    return load
