# Parser qoidalari va Logist aniqlash logikasi

> **Maqsad:** LOGISTBOT hozirda ACTUAL bo'lib turgan (2026-07-10 holatiga) parser
> va logist aniqlash logikasini bir joyda tushuntirish. Bu hujjat kodga havola
> qiladi — asl haqiqat har doim koddir, bu faqat xarita.

## 1. Umumiy oqim (pipeline)

```
Telegram kanal xabari
        │
        ▼
[channel_reader.py]  ── xabarni o'qiydi, forum-mavzu (viloyat) ni aniqlaydi
        │
        ▼
[parser_service.py]  ── matndan: yo'nalish, telefon, vazn, yuk turi, izoh ajratadi
        │
        ▼
[logist_service.py]  ── FAQAT LORRY kanalida: telefon logistmi? (route diversity)
        │
        ▼
   PostgreSQL (loads)  ── logist/blocklist bo'lmasa, yuk bazasiga tushadi
```

Uchta asosiy fayl:

| Fayl | Vazifasi | Qatorlar |
|------|----------|----------|
| `bot/services/channel_reader.py` | Telethon polling, kanaldan o'qish, mavzu→viloyat | 296 |
| `bot/services/parser_service.py` | Matn parsing (regex + LLM fallback) | 748 |
| `bot/services/logist_service.py` | Logist aniqlash (route diversity V1) + blocklist | 307 |

---

## 2. Kanal o'quvchi — `channel_reader.py`

Telethon (user account) orqali sozlangan kanallarni pollab turadi (`POLL_INTERVAL = 30`s),
ishga tushganda `BACKFILL_LIMIT = 200` eski xabarni ham o'qiydi.

### 2.1. Forum mavzu → viloyat xaritasi (`_build_topic_map`, ~42-79)

Forum guruhida har bir mavzu (topic) bitta viloyatga tegishli. Bu funksiya
`{topic_id: "Viloyat"}` xaritasini quradi.

**MUHIM QOIDA (2026-07-10 tuzatildi):** faqat 13 rasmiy viloyatga mos keladigan
mavzular qabul qilinadi. Aniqlash `parser_service.to_viloyat(_find_city_in(title))`
orqali, natija `load_service.ALL_VILOYATS` ro'yxatida bo'lishi shart.

```python
viloyat = to_viloyat(_find_city_in(title))
if viloyat not in ALL_VILOYATS:
    continue   # "Premium — barcha yuklar", "🚛 haydovchi e'lonlari" va h.k. — tashlanadi
region_by_topic[tid] = viloyat
```

> Nega kerak: aks holda kanaldagi "Premium", "haydovchi e'lonlari", "import yuklar"
> kabi mavzular ham "viloyat" sifatida bazaga tushib, haydovchi menyusida
> begona tugma bo'lib chiqadi.

### 2.2. Xabarni qayta ishlash (`_process_message`, ~72-174)

1. **Yo'nalish (origin/destination):**
   - Forum guruh: `origin = mavzu viloyati`, `destination = matndan` (`extract_destination_freetext`).
   - Oddiy guruh (forum emas): `origin, destination = _extract_route(text)`, so'ng `origin = to_viloyat(origin)` (viloyatga aylanadi, menyu toza qolsin).
2. **Telefon majburiy:** `_extract_contact(text)` — topilmasa xabar tashlanadi.
3. **Blocklist tekshiruvi:** `is_blocklisted(contact)` — qo'lda-logist ro'yxatidagi raqam har qaysi kanalda tashlanadi.
4. **LORRY kanalida logist aniqlash** (2.3 quyida). Boshqa kanallarda logist tushunchasi yo'q — to'g'ridan bazaga.
5. **Saqlash:** `save_parsed_load(...)`.

---

## 3. Matn parseri — `parser_service.py`

### 3.1. Shahar lug'atlari (eng muhim ma'lumot bazasi)

| Struktura | Vazifasi | Qatorlar |
|-----------|----------|----------|
| `CITY_ALIASES` | kichik harf variant (lotin/kirill/imlo) → kanonik shahar nomi | ~18-160 |
| `CITY_TO_VILOYAT` | kanonik shahar/tuman → viloyat | ~163-195 |

- **`_find_city_in(text)`** (~285) — matndan eng birinchi uchragan shaharni topadi.
  **2026-07-10 tuzatildi:** apostrofsiz yozuvni ham taniydi (`Kattaqorgon` = `Kattaqo'rg'on`),
  chunki xabarlarda `g'/o'` tovushlari ko'pincha apostrofsiz yoziladi. Buni
  `_strip_apostrophe` yordamchisi orqali qiladi.
- **`to_viloyat(city)`** (~198) — kichik shahar/tumanni viloyatga aylantiradi
  (`Chirchiq → Toshkent`). FAQAT origin uchun (menyu ~13 tugma bo'lib qolsin);
  destination granular qoladi.

> Yangi shahar/tuman qo'shish: uni HAM `CITY_ALIASES` ga (kichik harf kalit),
> HAM `CITY_TO_VILOYAT` ga qo'shish kerak. Faqat bittasi yetarli emas.

### 3.2. Regex ajratgichlari (asosiy qoidalar)

| Regex | Nima topadi | Qator |
|-------|-------------|-------|
| `_PHONE_RE` | telefon (`+998 XX...`, mahalliy, yalang 9 raqam) | ~200 |
| `_WEIGHT_RE` | vazn (`15 tonna`, `8t`, `15 т`) | ~187 |
| `_PRICE_RE` / `_PRICE_BARE_RE` | narx (so'm/sum/ming/mln) | ~191 |
| `_SEP_RE` / `_ROUTE_SEP_RE` | yo'nalish ajratgichi (`➡️`, `→`, `-`, `/`) | ~207 |
| `CARGO_KEYWORDS` | yuk turi kalit so'zlari → kategoriya | ~211 |

### 3.3. Telefon normalizatsiyasi — `normalize_phone` (~410)

**2026-07-10 tuzatildi:** natija **bo'shliqsiz** `+998XXXXXXXXX` formatida.

```python
digits = re.sub(r"\D", "", raw)
if len(digits) == 9:  digits = "998" + digits   # mahalliy 90 123 45 67
if len(digits) == 12 and digits.startswith("998"):
    return "+" + digits                          # +998901234567
return None                                       # noto'g'ri -> None
```

> Diqqat: loyihada 3 ta bir xil nomli `normalize_phone` bor —
> `parser_service` (yuk telefoni), `logist_service` (logist sanashda),
> `handlers/start.py` (foydalanuvchi o'z raqami). Uchalasi ham endi
> **bo'shliqsiz** formatga keltiradi.

### 3.4. Yo'nalish ajratish

- **`_extract_route(text)`** (~307) — avval ajratgich (`➡️`) bo'yicha chap/o'ng,
  topilmasa matndagi shaharlar tartibi bo'yicha (`_ordered_cities`).
- **`extract_destination_freetext(text)`** (~330) — LORRY formati uchun
  (`ORIGIN ➡️ DEST 🚛...`) faqat destination ajratadi.

### 3.5. Izoh va tana (note/body)

- **`extract_note(text)`** (~467) — yuk haqidagi izoh (tur, vazn, talab) bitta
  qatorga. Telefon, shahar, narx, link, footer, hashtag, mention olib tashlanadi.
- **`extract_body(text, phone)`** (~501) — shablonning 3-qatori uchun; `extract_note`dan
  yumshoqroq — narx/vazn/yuk turi SAQLANADI.
- **`extract_price_line(text)`** (~448) — narxni "taxmin qilmaydi", faqat aniq
  yozilganini oladi (`💰` qatori yoki valyutali summa).

### 3.6. Yuk turi va mashina turi

- **`_extract_cargo_type(text)`** (~536) — `CARGO_KEYWORDS` bo'yicha kategoriya,
  topilmasa qolgan ma'noli so'zlar.
- **`classify_vehicle(text, weight_t)`** (~681) — mashina aniq yozilgan bo'lsa shuni,
  aks holda vazn bo'yicha:
  - `<= 2t` → **Kichik** (Porter/labo)
  - `<= 10t` → **Isuzu**
  - `> 10t` (yoki noma'lum) → **Fura**

### 3.7. Public API (parsing kirish nuqtalari)

| Funksiya | Vazifasi | Qator |
|----------|----------|-------|
| `parse_with_regex(text)` | regex-asosli parser, `confidence` bilan | ~569 |
| `parse_with_llm(text, key)` | OpenAI `gpt-4o-mini` fallback (JSON) | ~591 |
| `parse_load(text, key)` | orkestrator: regex `>=0.7` bo'lsa uni, yo'q bo'lsa LLM | ~652 |
| `save_parsed_load(...)` | Load yozuvini bazaga saqlaydi (dublikat tekshiruvi bilan) | ~702 |

**Confidence:** `origin, destination, cargo_type, weight_t` — nechtasi topilgan / 4.
`>= auto_approve_threshold` (0.85) → `status=open` (darhol ko'rinadi),
aks holda `status=pending` (moderatsiya).

> Eslatma: kanal o'quvchi (channel_reader) hozir `parse_load`ni EMAS, balki
> to'g'ridan `_extract_*` funksiyalarini chaqiradi va telefon+yo'nalish bo'lsa
> `confidence=1.0` beradi (yo'nalish mavzudan aniq). LLM fallback asosan
> `parse_load` orqali chaqiriladigan yo'llarda ishlatiladi.

---

## 4. Logist aniqlash — `logist_service.py`

> **FAQAT LORRY guruhida** (`settings.LORRY_CHANNEL_IDS`). Boshqa kanallarda
> logist tushunchasi yo'q — hamma yuk to'g'ridan bazaga tushadi.

### 4.1. Asosiy g'oya — Route Diversity V1

Logist signali = e'lonlar SONI emas, balki **bitta telefondan oxirgi 12 soatda
nechta TURLI yo'nalish** (origin→dest, directional) chiqqani.

```
distinct >= HARD_THRESHOLD (4)  ->  LOGIST      (yuk bazasiga TUSHMAYDI)
distinct == SOFT_THRESHOLD (3)  ->  SUSPICIOUS  (bazaga tushadi, faqat log)
distinct <= 2                   ->  CARGO       (bazaga tushadi)
```

Sozlamalar (kodni o'zgartirmasdan tuning, ~35-38):
`WINDOW_HOURS=12`, `HARD_THRESHOLD=4`, `SOFT_THRESHOLD=3`, `DIRECTIONAL=True`.

### 4.2. Sof funksiyalar (DB'siz yadro — avval mustaqil test qilinadi)

| Funksiya | Vazifasi | Qator |
|----------|----------|-------|
| `normalize_phone(raw)` | `+998XXXXXXXXX` (bo'shliqsiz) yoki None | ~71 |
| `canonicalize_city(raw)` | shahar → kanonik lotin nomi (shovqin/kirill bilan) | ~85 |
| `parse_route(header)` | sarlavha qatoridan `(origin, dest)` | ~103 |
| `distinct_route_count(routes)` | turli `(origin,dest)` juftliklar soni (ikkalasi ham aniq) | ~121 |
| `classify_routes(routes)` | son → `Label` (LOGIST/SUSPICIOUS/CARGO) | ~134 |

`canonicalize_city` shovqin so'zlarni (`vest`, `tuman`, `rayon`...) olib tashlaydi
(`_CITY_NOISE`, ~57), noma'lum shahar → None (route sanoqqa kirmaydi).

### 4.3. DB o'rami

| Funksiya | Vazifasi | Qator |
|----------|----------|-------|
| `classify_phone_db(session, phone, ...)` | 12s oyna bo'yicha `lorry_listings`dan sanaydi | ~156 |
| `evaluate_and_record(session, ...)` | xabarni tarixga yozadi + klassifikatsiya | ~193 |
| `purge_old_listings(session)` | 48s+ eski tarix yozuvlarini o'chiradi | ~300 |

`evaluate_and_record` har (yangi, dublikat bo'lmagan) LORRY xabarini `LorryListing`
jadvaliga yozadi — logist bo'lsa ham (sanash uchun kerak). Yuk bazasiga qo'shish
qarorini chaqiruvchi (`channel_reader`) `Decision.label` bo'yicha qiladi.

### 4.4. Qo'lda-logist ro'yxati (manual blocklist)

Admin qarori, algoritmdan **ustun**. Bu raqamdan kelgan yuk HECH QAYSI kanaldan
bazaga tushmaydi. Jarayon ichida keshlanadi (`_blocklist_cache`).

| Funksiya | Vazifasi | Qator |
|----------|----------|-------|
| `refresh_blocklist(session)` | DB→kesh (startup + har poll) | ~250 |
| `is_blocklisted(phone)` | sinxron, tez tekshiruv | ~258 |
| `add_logist_phone` / `remove_logist_phone` | ro'yxatga qo'shish/o'chirish | ~264 / ~278 |
| `list_logist_phones` | barcha raqamlar | ~291 |

---

## 5. Bog'liq fayllar (tegilmasligi kerak bo'lgan asosiy joylar)

| Fayl | Nimasi muhim |
|------|--------------|
| `bot/services/load_service.py` | `ALL_VILOYATS` (13 rasmiy viloyat), `get_or_create_route`, menyu uchun `get_origin_regions_with_open_loads` |
| `db/models.py` | `Load`, `Route`, `LorryListing`, `LogistBlocklist` modellari |
| `scripts/fix_premium_origins.py` | bir martalik migratsiya: eski noto'g'ri origin'larni matndan qayta aniqlash |

---

## 6. So'nggi o'zgarishlar (2026-07-10)

1. **Viloyat menyusi filtri** — forum mavzu nomlari `ALL_VILOYATS` bilan whitelist
   qilinadi (`channel_reader._build_topic_map`).
2. **Telefon formati** — `normalize_phone` bo'shliqsiz `+998XXXXXXXXX` qaytaradi.
3. **Shahar lug'ati kengaytmasi** — apostrofsiz yozuv (`_strip_apostrophe`) va
   17+ yangi tuman/qishloq nomi (`CITY_ALIASES` + `CITY_TO_VILOYAT`).
4. **Baza tozalash** — 287 ta noto'g'ri origin'li yuk tuzatildi/o'chirildi
   (`scripts/fix_premium_origins.py` orqali).
5. **Avtomatik deploy** — `.github/workflows/deploy.yml`: har push'da serverga
   `git pull` + migration + `systemctl restart yukbot`.
