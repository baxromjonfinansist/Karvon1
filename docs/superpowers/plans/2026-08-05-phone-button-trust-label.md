# Telefon-tugma (deep-link) + "1-qo'l" ishonch yorlig'i — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Yuk kartalarida telefon raqamini standart holatda "📞 Qo'ng'iroq qilish" deep-link tugmasiga almashtirish (feed/xabarnomada), maxsus "reveal" nuqtalarida haqiqiy raqamni ko'rsatish, va har bir yukka "1-qo'l" ishonch yorlig'i qo'shish.

**Architecture:** `format_load_card`ga `show_phone: bool = False` parametri qo'shiladi (default — tugma, `True` — matn). Yangi sof modul `bot/services/deeplink.py` deep-link URL qurish/parsing uchun. `/start load_<id>` ni `cmd_start` qabul qiladi; ro'yxatdan o'tgan user uchun darhol, yangi user uchun telefon bosqichidan keyin yukni `show_phone=True` bilan ko'rsatadi. "1-qo'l" yorlig'i `save_parsed_load`da hisoblanib, `Load.first_time_phone` ustunida saqlanadi.

**Tech Stack:** Python, aiogram 3, SQLAlchemy (async), Alembic, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-05-phone-button-trust-label-design.md` — barcha talablar shu yerdan.
- Har vazifa: avval tushadigan test, keyin minimal implementatsiya, keyin `python3 -m pytest tests/ -q` to'liq yashil, keyin commit.
- Kod izohlari va nomlanish — mavjud repo konvensiyasi bo'yicha (o'zbekcha izohlar, `snake_case`).
- Migratsiya zanjiri: joriy head — `20260804_app_settings`.
- `.env`/parol/token hech qachon kodga yozilmaydi (bu loyihada allaqachon amal qiladi, o'zgarish yo'q).

---

### Task 1: `Load.first_time_phone` ustuni + migratsiya

**Files:**
- Modify: `db/models.py` (Load klassi, taxminan 198–221 qatorlar)
- Create: `db/migrations/versions/20260805_load_first_time_phone.py`
- Test: `tests/test_load_service.py` (yangi fayl — hozir yo'q, shu vazifada yaratiladi)

**Interfaces:**
- Produces: `Load.first_time_phone: Mapped[bool]` — DB ustuni, default `True` (server_default `"true"`), boolean.

- [ ] **Step 1: Migratsiya faylini yozish**

`db/migrations/versions/20260805_load_first_time_phone.py`:

```python
"""loads.first_time_phone ustuni qo'shildi (1-qo'l ishonch yorlig'i uchun).

Revision ID: 20260805_load_first_time_phone
Revises: 20260804_app_settings
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260805_load_first_time_phone"
down_revision = "20260804_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "loads",
        sa.Column(
            "first_time_phone", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("loads", "first_time_phone")
```

- [ ] **Step 2: `db/models.py`ga ustun qo'shish**

`Load` klassidagi `posted_at` qatoridan keyin (taxminan 214-qator, `posted_at: Mapped[datetime] = ...` dan keyin):

```python
    first_time_phone: Mapped[bool] = mapped_column(Boolean, server_default=sa.true())
```

`Boolean` va `sa` (yoki to'g'ridan `sqlalchemy.true`) import qilinganiga ishonch hosil qiling — fayl boshidagi importlarni tekshiring (`from sqlalchemy import ...`); kerak bo'lsa `Boolean` va `true` qo'shing.

- [ ] **Step 3: Migratsiyani lokal tekshirish (agar lokal Postgres bo'lsa) yoki import orqali tekshirish**

Run: `python3 -c "from db.models import Load; print(Load.__table__.c.first_time_phone)"`
Expected: xatosiz `loads.first_time_phone` chiqarilishi.

- [ ] **Step 4: Testlar va import tekshiruvi**

Run: `python3 -m pytest tests/ -q`
Expected: barcha mavjud testlar hali yashil (bu vazifa hali testga ega emas — faqat model+migratsiya).

- [ ] **Step 5: Commit**

```bash
git add db/models.py db/migrations/versions/20260805_load_first_time_phone.py
git commit -m "DB: loads.first_time_phone ustuni (1-qo'l ishonch yorlig'i uchun)"
```

---

### Task 2: `first_time_phone` hisoblovchi funksiya

**Files:**
- Modify: `bot/services/parser_service.py` (yangi funksiya `_is_first_time_phone`, `save_parsed_load` 785–831 qatorlar atrofida chaqiradi)
- Test: `tests/test_parser_load_save.py` (yangi fayl)

**Interfaces:**
- Consumes: Task 1 dagi `Load.first_time_phone` ustuni (faqat nom sifatida — bu vazifa haqiqiy DB'ga ulanmaydi).
- Produces: `_is_first_time_phone(session, phone: Optional[str]) -> bool` — sinab bo'ladigan mustaqil funksiya. `save_parsed_load` uni chaqirib natijani `Load(first_time_phone=...)`ga uzatadi.

**Eslatma (loyiha konvensiyasi):** bu repo `save_parsed_load`/`get_or_create_route` kabi ko'p-so'rovli funksiyalarni HECH QACHON real DB yoki `pytest-asyncio`/`aiosqlite` bilan test qilmaydi (tekshirib ko'rilgan — bunday test hozir umuman yo'q). Barcha mavjud testlar (`tests/test_admin_users.py`, `tests/test_instruction.py`, `tests/test_role_simplification.py`) sinov uchun qo'lda yozilgan `FakeSession`/`_Result` klasslaridan foydalanadi (`session.execute` — bitta oldindan tayyorlangan natija qaytaradigan `async def`, natija obyektida faqat kerakli metod — masalan `scalar_one_or_none()`). Shu sabab bu vazifada **yangi dependency (pytest-asyncio/aiosqlite) QO'SHILMAYDI** — yangi mantiq bitta, kichik, mustaqil funksiyaga chiqarilib, xuddi shu Fake pattern bilan test qilinadi.

- [ ] **Step 1: Tushadigan test yozish**

`tests/test_parser_load_save.py` (yangi fayl, `tests/test_instruction.py`dagi
`_Result`/`FakeSettingsSession` uslubida):

```python
"""_is_first_time_phone — "1-qo'l" ishonch yorlig'i uchun sof tekshiruv."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from bot.services.parser_service import _is_first_time_phone  # noqa: E402


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeSession:
    """execute() — oldindan berilgan bitta natijani qaytaradi (query e'tiborsiz)."""

    def __init__(self, existing_id):
        self._result = _Result(existing_id)

    async def execute(self, query):
        return self._result


def test_no_prior_load_is_first_time():
    session = _FakeSession(existing_id=None)   # hech narsa topilmadi
    assert asyncio.run(_is_first_time_phone(session, "+998901112233")) is True


def test_existing_load_is_not_first_time():
    session = _FakeSession(existing_id=42)     # boshqa yozuv bor
    assert asyncio.run(_is_first_time_phone(session, "+998901112233")) is False


def test_empty_phone_is_treated_as_first_time():
    """Telefon bo'lmasa (nazariy holat) — DB'ga so'rov yuborilmasdan True."""
    session = _FakeSession(existing_id=999)  # chaqirilmasligi kerak bo'lgan natija
    assert asyncio.run(_is_first_time_phone(session, None)) is True
```

- [ ] **Step 2: Testni ishga tushirib, xato ekanini ko'rish**

Run: `python3 -m pytest tests/test_parser_load_save.py -q`
Expected: FAIL — `ImportError: cannot import name '_is_first_time_phone'`.

- [ ] **Step 3: Funksiyani yozish va `save_parsed_load`ga ulash**

`bot/services/parser_service.py`da, `save_parsed_load`dan OLDIN (785-qator atrofida) yangi funksiya:

```python
async def _is_first_time_phone(session: AsyncSession, phone: Optional[str]) -> bool:
    """Shu telefon `loads` jadvalida ilgari uchraganmi ("1-qo'l" yorlig'i uchun).

    Telefon bo'lmasa — DB'ga murojaat qilinmaydi, `True` qaytariladi (nazariy
    holat, `prepare_message` telefonsiz xabarni allaqachon tashlaydi).

    Eslatma: yuklar 6 soatdan keyin (band bo'lmasa) butunlay o'chadi
    (`delete_stale_loads`) — shu sabab bir xil raqam uzoq tanaffusdan keyin
    qayta "birinchi marta" bo'lib chiqishi mumkin. Ongli qabul qilingan
    soddalashtirish (spec: 2026-08-05-phone-button-trust-label-design.md).
    """
    if not phone:
        return True
    result = await session.execute(
        select(Load.id).where(Load.contact_phone == phone).limit(1)
    )
    return result.scalar_one_or_none() is None
```

`save_parsed_load` ichida, `Load(...)` qurishdan OLDIN:

```python
    first_time_phone = await _is_first_time_phone(session, parsed.contact)
```

va `Load(...)` konstruktoriga qo'shing:

```python
        first_time_phone=first_time_phone,
```

- [ ] **Step 4: Testni qayta ishga tushirish**

Run: `python3 -m pytest tests/test_parser_load_save.py -q`
Expected: PASS (3/3).

- [ ] **Step 5: To'liq test suite**

Run: `python3 -m pytest tests/ -q`
Expected: barchasi yashil.

- [ ] **Step 6: Commit**

```bash
git add bot/services/parser_service.py tests/test_parser_load_save.py
git commit -m "Parser: _is_first_time_phone — save_parsed_load first_time_phone hisoblaydi"
```

---

### Task 3: `bot/services/deeplink.py` — sof deep-link funksiyalari

**Files:**
- Create: `bot/services/deeplink.py`
- Test: `tests/test_deeplink.py`

**Interfaces:**
- Produces:
  - `set_bot_username(username: str) -> None`
  - `build_load_deeplink(load_id: int) -> str` — `"https://t.me/<username>?start=load_<id>"`; username sozlanmagan bo'lsa `RuntimeError` ko'taradi.
  - `parse_load_start_payload(args: str | None) -> int | None` — `"load_42"` → `42`; noto'g'ri/bo'sh/`None` → `None`.

- [ ] **Step 1: Tushadigan testlarni yozish**

`tests/test_deeplink.py`:

```python
"""Deep-link (yuk raqamini ko'rsatish uchun /start payload) — sof funksiyalar."""
from __future__ import annotations

import pytest

from bot.services import deeplink as dl


def test_build_load_deeplink_requires_username():
    dl.set_bot_username(None)  # reset
    with pytest.raises(RuntimeError):
        dl.build_load_deeplink(42)


def test_build_load_deeplink_with_username():
    dl.set_bot_username("Yukchibrat_bot")
    assert dl.build_load_deeplink(42) == "https://t.me/Yukchibrat_bot?start=load_42"


def test_parse_load_start_payload_valid():
    assert dl.parse_load_start_payload("load_42") == 42


def test_parse_load_start_payload_none():
    assert dl.parse_load_start_payload(None) is None


def test_parse_load_start_payload_empty():
    assert dl.parse_load_start_payload("") is None


def test_parse_load_start_payload_wrong_prefix():
    assert dl.parse_load_start_payload("ref_42") is None


def test_parse_load_start_payload_non_numeric():
    assert dl.parse_load_start_payload("load_abc") is None
```

- [ ] **Step 2: Testni ishga tushirib, xato ekanini ko'rish**

Run: `python3 -m pytest tests/test_deeplink.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.services.deeplink'`.

- [ ] **Step 3: Modulni yozish**

`bot/services/deeplink.py`:

```python
from __future__ import annotations

from typing import Optional

_bot_username: Optional[str] = None

_LOAD_PREFIX = "load_"


def set_bot_username(username: Optional[str]) -> None:
    """Bot username'ini keshlaydi — `main.py` startup'da bir marta chaqiradi."""
    global _bot_username
    _bot_username = username


def build_load_deeplink(load_id: int) -> str:
    """Yukni ko'rsatuvchi deep-link: `https://t.me/<bot>?start=load_<id>`.

    Bot username hali sozlanmagan bo'lsa (`set_bot_username` chaqirilmagan)
    — xato ko'taradi, jim noto'g'ri link qaytarmaydi.
    """
    if not _bot_username:
        raise RuntimeError(
            "Bot username hali sozlanmagan — set_bot_username() chaqirilmagan."
        )
    return f"https://t.me/{_bot_username}?start={_LOAD_PREFIX}{load_id}"


def parse_load_start_payload(args: Optional[str]) -> Optional[int]:
    """`/start load_42` argumentidan yuk ID sini ajratadi. Mos kelmasa `None`."""
    if not args or not args.startswith(_LOAD_PREFIX):
        return None
    try:
        return int(args[len(_LOAD_PREFIX):])
    except ValueError:
        return None
```

- [ ] **Step 4: Testni qayta ishga tushirish**

Run: `python3 -m pytest tests/test_deeplink.py -q`
Expected: PASS (7/7).

- [ ] **Step 5: To'liq test suite**

Run: `python3 -m pytest tests/ -q`
Expected: barchasi yashil.

- [ ] **Step 6: Commit**

```bash
git add bot/services/deeplink.py tests/test_deeplink.py
git commit -m "Deep-link: yuk raqamini botga tortish uchun sof funksiyalar"
```

---

### Task 4: `format_load_card` — `show_phone` parametri + ishonch yorlig'i

**Files:**
- Modify: `bot/services/load_service.py:format_load_card` (58–76 qatorlar)
- Test: `tests/test_load_card.py` (mavjud fayl — yangi testlar qo'shiladi)
- Test: `tests/test_driver_menu.py` (71-83 qatorlar — mavjud test moslashtiriladi, Step 6)

**Interfaces:**
- Consumes: Task 3 dagi `bot.services.deeplink.build_load_deeplink`.
- Produces: `format_load_card(load, now=None, show_phone=False) -> str` — endi:
  - `show_phone=False`: "📞" qatori YO'Q (chaqiruvchi kod tugmani o'zi qo'shadi).
  - `show_phone=True`: "📞 {phone}" qatori matn sifatida bor.
  - Ikkala holatda ham route qatoridan keyin ishonch yorlig'i qatori bor:
    `load.first_time_phone` True → `"💯 100% 1-qo'l (birinchi marta)"`,
    False → `"✅ 1-qo'l — dispetcher/logist yo'q"`.

- [ ] **Step 1: Mavjud `tests/test_load_card.py`ni o'qib, uslubga moslash**

Run: `cat tests/test_load_card.py` — mavjud fixture/mock Load obyekti qanday qurilganini ko'ring (`load.route`, `load.contact_phone`, `load.posted_at`, `load.raw_text`, `load.note`, `load.cargo_type` maydonlari kerak bo'ladi + endi `load.first_time_phone`).

- [ ] **Step 2: Tushadigan testlarni qo'shish**

`tests/test_load_card.py` oxiriga qo'shing (mavjud faylda ishlatilgan soxta `Load` klassi/fixture'idan foydalaning; agar u oddiy `types.SimpleNamespace` yoki shunga o'xshash bo'lsa, o'sha patternni davom ettiring, `first_time_phone` maydonini qo'shib):

```python
def test_card_hides_phone_by_default(load_with_route):
    load_with_route.first_time_phone = True
    text = format_load_card(load_with_route)
    assert "📞" not in text
    assert load_with_route.contact_phone not in text


def test_card_shows_phone_when_requested(load_with_route):
    load_with_route.first_time_phone = True
    text = format_load_card(load_with_route, show_phone=True)
    assert f"📞 {load_with_route.contact_phone}" in text


def test_card_shows_100_percent_label_for_first_time_phone(load_with_route):
    load_with_route.first_time_phone = True
    text = format_load_card(load_with_route)
    assert "100% 1-qo'l" in text


def test_card_shows_no_dispatcher_label_for_repeat_phone(load_with_route):
    load_with_route.first_time_phone = False
    text = format_load_card(load_with_route)
    assert "dispetcher" in text.lower() or "logist" in text.lower()
    assert "100%" not in text
```

Eslatma: mavjud fayldagi fixture nomi boshqacha bo'lishi mumkin (masalan `sample_load` yoki qo'lda qurilgan obyekt har test ichida) — shu holda fixture'ni ishlatmasdan, mavjud testlardagi Load qurish patternini nusxalab, har test boshida `first_time_phone` maydonini qo'shib qo'ying.

- [ ] **Step 3: Testni ishga tushirib, xato ekanini ko'rish**

Run: `python3 -m pytest tests/test_load_card.py -q`
Expected: FAIL — kamida "hides_phone_by_default" va "100_percent_label" testlari (chunki hozircha `format_load_card` doim telefonni ko'rsatadi va yorliq yo'q).

- [ ] **Step 4: `format_load_card`ni yangilash**

`bot/services/load_service.py:58-76`:

```python
def format_load_card(load, now: Optional[datetime] = None, show_phone: bool = False) -> str:
    """Yuk kartasining umumiy ko'rinishi — feed va xabarnoma bir xil bo'lsin.

    `show_phone=False` (standart): telefon matn sifatida YO'Q — chaqiruvchi
    kod uni deep-link tugma orqali ko'rsatadi (`bot/services/deeplink.py`,
    "📞 Qo'ng'iroq qilish"). Bu — tashqi haydovchilar guruhiga ulashilganda
    raqam faqat botga kirgach ko'rinishi uchun (spec: 2026-08-05).
    `show_phone=True` — faqat maxsus "reveal" nuqtalarida (deep-link orqali
    kirgan/telefon bosqichini tugatgan user) haqiqiy raqam matnda beriladi.
    """
    route = f"{load.route.origin} → {load.route.destination}" if load.route else "—"
    body = (
        extract_body(load.raw_text or "", load.contact_phone)
        or load.note or load.cargo_type or "—"
    )
    trust_line = (
        "💯 100% 1-qo'l (birinchi marta)"
        if getattr(load, "first_time_phone", False)
        else "✅ 1-qo'l — dispetcher/logist yo'q"
    )
    lines = [
        f"🚚 <b>{route}</b>",
        trust_line,
    ]
    if show_phone:
        lines.append(f"📞 {load.contact_phone or '—'}")
    age = humanize_age(getattr(load, "posted_at", None), now)
    if age:
        lines.append(f"🕒 {age}")
    lines.append(f"📝 {escape(body)}")
    return "\n".join(lines)
```

- [ ] **Step 5: Testni qayta ishga tushirish**

Run: `python3 -m pytest tests/test_load_card.py -q`
Expected: PASS (barchasi).

- [ ] **Step 6: `tests/test_driver_menu.py`dagi eski testni moslashtirish**

Run: `python3 -m pytest tests/test_driver_menu.py -q`
Expected: FAIL — `test_driver_kartasi_umumiy_formatlovchini_ishlatadi`
(`"📞 +998901234567" in text` — endi standart holatda telefon matnda yo'q,
o'rniga ishonch yorlig'i bor).

`tests/test_driver_menu.py`da (71-83 qatorlar) shu testni ALMASHTIRING
(eskisini o'chirib, o'rniga qo'ying). `driver_handlers._fmt_load` bu Task
doirasida hali eski imzoda (`_fmt_load(load)`, parametrsiz) — Task 5da
`show_phone` parametri qo'shiladi, shu sabab bu yerda faqat STANDART
(parametrsiz) chaqiruv tekshiriladi:

```python
def test_driver_kartasi_default_holatda_telefon_yashirin():
    """Standart chaqiruvda (_fmt_load(load)) telefon matnda YO'Q,
    o'rniga ishonch yorlig'i bor — tugma keyingi vazifada qo'shiladi."""
    load = SimpleNamespace(
        id=1,
        route=SimpleNamespace(origin="Toshkent", destination="Samarqand"),
        contact_phone="+998901234567",
        raw_text="",
        note="Paxta",
        cargo_type=None,
        posted_at=datetime.utcnow() - timedelta(minutes=40),
        first_time_phone=True,
    )
    text = driver_handlers._fmt_load(load)
    assert "🕒 40 daqiqa oldin" in text
    assert "+998901234567" not in text
    assert "100% 1-qo'l" in text
```

`driver_handlers` — mavjud faylning boshida allaqachon
`from bot.handlers import driver as driver_handlers` bilan import qilingan
(agar boshqacha nom bo'lsa, faylning import blokidagi haqiqiy nomdan
foydalaning).

- [ ] **Step 7: To'liq test suite**

Run: `python3 -m pytest tests/ -q`
Expected: barchasi yashil (bu Task o'z-o'zidan to'liq, keyingi vazifaga
qaram emas).

- [ ] **Step 8: Commit**

```bash
git add bot/services/load_service.py tests/test_load_card.py tests/test_driver_menu.py
git commit -m "load_service: format_load_card show_phone param + 1-qo'l yorlig'i"
```

---

### Task 5: `driver.py` — feed va "Olish" oqimida tugma/reveal

**Files:**
- Modify: `bot/handlers/driver.py` (`_fmt_load`, `_take_kb`, va chaqiruvchi joylar: ~200, 421-424, 452-455, 464-467, 496)
- Test: `tests/test_driver_menu.py` (mavjud — kerakli testlar qo'shiladi/moslashtiriladi)

**Interfaces:**
- Consumes: Task 3 (`build_load_deeplink`), Task 4 (`format_load_card(show_phone=...)`).
- Produces: `_fmt_load(load, show_phone=False)`, `_take_kb(load_id, load=None)` — `load` berilsa "📞 Qo'ng'iroq qilish" tugmasi qo'shiladi. Feed ro'yxatida telefon tugma orqali; "Olish" tasdiqlash/tasdiqlangan holatlarida haqiqiy raqam matnda (mavjud xatti-harakat saqlanadi — kod izohi: "Telefon o'chib qolmasligi uchun").

- [ ] **Step 1: `_fmt_load` va `_take_kb`ni yangilash**

`bot/handlers/driver.py:64-74`:

```python
def _fmt_load(load, show_phone: bool = False) -> str:
    """Yuk kartasi — umumiy formatlovchi (feed va xabarnoma bir xil ko'rinadi)."""
    return format_load_card(load, show_phone=show_phone)


def _take_kb(load_id: int, load=None) -> InlineKeyboardMarkup:
    """Feed'dagi «Olish» tugmasi. `load` berilsa — «📞 Qo'ng'iroq qilish»
    deep-link tugmasi ham qo'shiladi (feed'da telefon matnda emas)."""
    rows = [[InlineKeyboardButton(text="🤝 Olish", callback_data=f"take_{load_id}")]]
    if load is not None:
        rows.append([InlineKeyboardButton(
            text="📞 Qo'ng'iroq qilish", url=build_load_deeplink(load_id),
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
```

Fayl boshiga import qo'shing (12-16 qatorlar atrofida, `bot.services.load_service` import blokidan keyin):

```python
from bot.services.deeplink import build_load_deeplink
```

- [ ] **Step 2: Feed chaqiruvini yangilash (200-qator)**

```python
        await callback.message.answer(_fmt_load(load), reply_markup=_take_kb(load.id, load=load))
```

(`_fmt_load(load)` — `show_phone` default `False` qoladi, tugma qo'shiladi.)

- [ ] **Step 3: "Olish" oqimidagi 3 ta joyni `show_phone=True` bilan yangilash**

421-424, 452-455, 464-467 qatorlar — har birida `_fmt_load(load)` →
`_fmt_load(load, show_phone=True)`. Bu uch joy: tasdiq so'rash, band
qilingan (rad), va "✅ Olindi" — hammasida driver allaqachon "Olish"ni
bosgan, shu sabab raqam to'g'ridan ko'rsatiladi (mavjud kod izohi —
463-qator — buni talab qiladi, o'zgartirmaymiz).

496-qator (`take_decline_cb` — bekor qilindi, kartaga qaytish):

```python
        await callback.message.edit_text(_fmt_load(load), reply_markup=_take_kb(load_id, load=load))
```

(Bu — declined holat, foydalanuvchi hali olmagan, feed holatiga qaytadi — tugma bilan.)

- [ ] **Step 4: Yangi testlarni qo'shish**

Task 4 `tests/test_driver_menu.py`ga `test_driver_kartasi_default_holatda_telefon_yashirin`
testini allaqachon qo'shgan (standart, parametrsiz chaqiruv). Bu Task shu
faylga endi YANGI `show_phone=True` va `_take_kb` testlarini qo'shadi
(oldingi testni QAYTA YOZMANG — u joyida qoladi):

```python
def test_driver_kartasi_show_phone_true_bilan_raqam_koradi():
    load = SimpleNamespace(
        id=1,
        route=SimpleNamespace(origin="Toshkent", destination="Samarqand"),
        contact_phone="+998901234567",
        raw_text="",
        note="Paxta",
        cargo_type=None,
        posted_at=datetime.utcnow() - timedelta(minutes=40),
        first_time_phone=False,
    )
    text = driver_handlers._fmt_load(load, show_phone=True)
    assert "📞 +998901234567" in text
    assert "dispetcher" in text.lower() or "logist" in text.lower()
```

Xuddi shu faylga `_take_kb` uchun ham test qo'shing:

```python
def test_take_kb_load_bilan_qongiroq_tugmasi_qoshadi(monkeypatch):
    monkeypatch.setattr(
        "bot.services.deeplink.build_load_deeplink",
        lambda load_id: f"https://t.me/TestBot?start=load_{load_id}",
    )
    load = SimpleNamespace(id=7)
    kb = driver_handlers._take_kb(7, load=load)
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert "🤝 Olish" in texts
    assert "📞 Qo'ng'iroq qilish" in texts


def test_take_kb_loadsiz_faqat_olish_tugmasi():
    kb = driver_handlers._take_kb(7)
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert texts == ["🤝 Olish"]
```

- [ ] **Step 5: To'liq test suite**

Run: `python3 -m pytest tests/ -q`
Expected: barchasi yashil.

- [ ] **Step 6: Commit**

```bash
git add bot/handlers/driver.py tests/test_driver_menu.py
git commit -m "driver.py: feed'da telefon-tugma, Olish oqimida raqam matnda"
```

---

### Task 6: `notify_service.py` — avtomatik xabarnomada tugma

**Files:**
- Modify: `bot/services/notify_service.py` (`_fmt`, `_take_kb`, ~37-51 qatorlar)
- Test: `tests/test_notify_cleanup.py` (mavjud — kerakli testlar qo'shiladi/moslashtiriladi)

**Interfaces:**
- Consumes: Task 3 (`build_load_deeplink`).
- Produces: `_take_kb(load_id, load)` — endi "🤝 Olish" + "📞 Qo'ng'iroq qilish" + "🔕 Xabarnomani o'chirish" uchta qator.

- [ ] **Step 1: `_take_kb`ni yangilash**

`bot/services/notify_service.py:42-51`:

```python
def _take_kb(load_id: int, load) -> InlineKeyboardMarkup:
    """Xabarnoma tugmalari: yukni olish, raqamni ko'rish (deep-link), o'chirish.

    "📞 Qo'ng'iroq qilish" — telefon karta matnida yo'q (`format_load_card`
    `show_phone=False`), faqat shu tugma orqali (botga kirib) ko'rinadi.
    "🔕 O'chirish" — foydalanuvchi xabarnomadan bezovta bo'lsa, shu yerdan
    darhol o'chira olsin (Sozlamalarga borishga hojat qolmasin).
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Olish", callback_data=f"take_{load_id}")],
        [InlineKeyboardButton(
            text="📞 Qo'ng'iroq qilish", url=build_load_deeplink(load_id),
        )],
        [InlineKeyboardButton(text="🔕 Xabarnomani o'chirish", callback_data="notify_off")],
    ])
```

Fayl boshiga import qo'shing (13-17 qatorlar atrofida):

```python
from bot.services.deeplink import build_load_deeplink
```

- [ ] **Step 2: `_take_kb` chaqiruvchi joyni yangilash**

`grep -n "_take_kb(" bot/services/notify_service.py` bilan chaqiruv joyini
toping (`_notify_driver` ichida) va `_take_kb(load.id)` ni
`_take_kb(load.id, load)` ga o'zgartiring.

- [ ] **Step 3: Mavjud testlarni ishga tushirish**

Run: `python3 -m pytest tests/test_notify_cleanup.py -q`
Expected: PASS — bu fayldagi yagona karta testi
(`test_xabarnoma_kartasida_yosh_bor`, 119-132 qatorlar) faqat yosh va
sarlavha qatorini tekshiradi, telefon yoki klaviaturani tekshirmaydi,
shu sabab o'zgarishsiz yashil qoladi. Klaviatura (`_take_kb`) uchun
alohida test yo'q edi — shu vazifada yangi test qo'shing:

```python
def test_take_kb_ichida_qongiroq_tugmasi_bor(monkeypatch):
    monkeypatch.setattr(
        "bot.services.deeplink.build_load_deeplink",
        lambda load_id: f"https://t.me/TestBot?start=load_{load_id}",
    )
    load = SimpleNamespace(id=7)
    kb = ns._take_kb(7, load)
    texts = [b.text for row in kb.inline_keyboard for b in row]
    urls = [b.url for row in kb.inline_keyboard for b in row if b.url]
    assert "📞 Qo'ng'iroq qilish" in texts
    assert "https://t.me/TestBot?start=load_7" in urls
```

Buni faylning oxiriga (`test_xabarnoma_kartasida_yosh_bor`dan keyin) qo'shing.

- [ ] **Step 4: To'liq test suite**

Run: `python3 -m pytest tests/ -q`
Expected: barchasi yashil.

- [ ] **Step 5: Commit**

```bash
git add bot/services/notify_service.py tests/test_notify_cleanup.py
git commit -m "notify_service: avtomatik xabarnomada telefon-tugma"
```

---

### Task 7: `main.py` — bot username'ini keshlash

**Files:**
- Modify: `bot/main.py` (`main()` funksiyasi, Bot yaratilgandan keyin — ~90-93 qatorlar)

**Interfaces:**
- Consumes: Task 3 (`bot.services.deeplink.set_bot_username`).

- [ ] **Step 1: Import qo'shish**

`bot/main.py` boshiga:

```python
from bot.services.deeplink import set_bot_username
```

- [ ] **Step 2: `Bot(...)` yaratilgandan keyin username'ni olish**

```python
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    me = await bot.get_me()
    set_bot_username(me.username)
    log.info("Bot username: @%s", me.username)
```

- [ ] **Step 3: Import xatosi yo'qligini tekshirish**

Run: `python3 -c "import bot.main"`
Expected: xatosiz import (funksiya chaqirilmaydi, faqat syntax/import tekshiruvi).

- [ ] **Step 4: To'liq test suite**

Run: `python3 -m pytest tests/ -q`
Expected: barchasi yashil (bu vazifa test talab qilmaydi — runtime-only, `main()` testlanmaydi loyihada allaqachon shunday).

- [ ] **Step 5: Commit**

```bash
git add bot/main.py
git commit -m "main.py: bot username'ini deep-link uchun keshlash"
```

---

### Task 8: `start.py` — deep-link qabul qilish va "reveal" nuqtalari

**Files:**
- Modify: `bot/handlers/start.py` (`cmd_start` ~187-214; `driver_phone_contact`/`driver_phone_text` ~274-294; `_finish_provider_reg` ~542-581)
- Test: `tests/test_start_deeplink.py` (yangi fayl)

**Interfaces:**
- Consumes: Task 3 (`parse_load_start_payload`), Task 4 (`format_load_card(show_phone=True)`), `get_load_detail` (`bot.services.load_service`).
- Produces: to'liq deep-link oqimi (spec 2-bo'lim).

- [ ] **Step 1: Yordamchi funksiyani loyihalash — `_show_deeplinked_load`**

`bot/handlers/start.py`ga yangi import va yordamchi funksiya qo'shiladi
(fayl boshiga, mavjud importlardan keyin):

```python
from bot.services.deeplink import parse_load_start_payload
from bot.services.load_service import format_load_card, get_load_detail
```

(`get_load_detail` — `bot/services/load_service.py:115`, mavjud funksiya.)

Yordamchi (fayl oxiriga yaqin, `_finish_provider_reg`dan oldin joylashtiring):

```python
async def _show_deeplinked_load(message: Message, session: AsyncSession, load_id: int) -> None:
    """Deep-link orqali so'ralgan yukni ko'rsatadi (raqam ochiq holda).

    Yuk topilmasa (band bo'lgan/eskirgan — 6 soatda o'chadi) — muloyim
    xabar, oqim to'xtamaydi.
    """
    load = await get_load_detail(session, load_id)
    if load is None:
        await message.answer("Bu yuk endi mavjud emas, lekin yangi yuklar bor 👇")
        return
    await message.answer(
        "📦 Siz ko'rmoqchi bo'lgan yuk:\n\n" + format_load_card(load, show_phone=True)
    )
```

- [ ] **Step 2: `cmd_start`ni yangilash (deep-link payload)**

`bot/handlers/start.py:187-214` ni almashtiring:

```python
@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    # /start har doim ishlashi kerak — hatto foydalanuvchi biror jarayonda
    # (masalan yo'nalish tanlashda) "qotib qolgan" bo'lsa ham qutqaradi.
    await state.clear()

    parts = (message.text or "").split(maxsplit=1)
    deep_link_load_id = parse_load_start_payload(parts[1] if len(parts) > 1 else None)

    user = await get_or_none(session, message.from_user.id)
    if user:
        if deep_link_load_id is not None:
            await _show_deeplinked_load(message, session, deep_link_load_id)
        await _send_main_menu(message, user.role)
        return

    if deep_link_load_id is not None:
        await state.update_data(pending_load_id=deep_link_load_id)

    # Faza 6: yangi (hali ro'yxatdan o'tmagan) user uchun — instruksiya
    # sozlangan bo'lsa (video va/yoki matn) avval shuni ko'rsatamiz, keyin
    # «✅ Ko'rdim»/«⏭ Keyinroq» — IKKALASI HAM rol tanlashga o'tkazadi.
    # Sozlanmagan bo'lsa — to'g'ridan rol tanlash (eski xatti-harakat).
    instruction = await get_instruction(session)
    if instruction["video_file_id"] or instruction["text"]:
        if instruction["video_file_id"]:
            await message.answer_video(instruction["video_file_id"])
        if instruction["text"]:
            await message.answer(instruction["text"])
        await message.answer(
            "Botdan qanday foydalanishni ko'rsatib berdik. Davom etamizmi?",
            reply_markup=_instruction_ack_kb(),
        )
        return

    await message.answer(WELCOME_TEXT, reply_markup=role_choice_kb())
```

Diqqat: `state.update_data(pending_load_id=...)` — `state.clear()`dan KEYIN
chaqiriladi (yuqorida ko'rsatilganidek), aks holda `clear()` uni
o'chirib tashlaydi.

- [ ] **Step 3: `DriverReg.waiting_phone` handlerlarida reveal**

`bot/handlers/start.py:274-294` (`driver_phone_contact` va
`driver_phone_text`) — ikkalasida ham `state.set_state(DriverReg.waiting_vehicle_type)`
dan OLDIN pending yukni ko'rsatish kerak. `session: AsyncSession`
parametrini handler imzosiga qo'shing (hozir yo'q):

```python
@router.message(DriverReg.waiting_phone, F.contact)
async def driver_phone_contact(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    await _reveal_pending_load_if_any(message, state, session)
    await state.set_state(DriverReg.waiting_vehicle_type)
    await _ask_vehicle_type(message)


@router.message(DriverReg.waiting_phone, F.text)
async def driver_phone_text(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    phone = _normalize_phone(message.text or "")
    if phone is None:
        await message.answer(
            "Noto'g'ri format. Raqamni +998XXXXXXXXX shaklida kiriting yoki "
            "«📱 Raqamni yuborish» tugmasini bosing."
        )
        return

    await state.update_data(phone=phone)
    await _reveal_pending_load_if_any(message, state, session)
    await state.set_state(DriverReg.waiting_vehicle_type)
    await _ask_vehicle_type(message)
```

Yordamchi funksiya (`_show_deeplinked_load`dan keyin qo'shing):

```python
async def _reveal_pending_load_if_any(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Deep-link orqali kutilayotgan yuk bo'lsa — ko'rsatadi va state'ni tozalaydi."""
    data = await state.get_data()
    load_id = data.get("pending_load_id")
    if load_id is None:
        return
    await _show_deeplinked_load(message, session, load_id)
    await state.update_data(pending_load_id=None)
```

- [ ] **Step 4: `_finish_provider_reg`da reveal**

`bot/handlers/start.py:542-581` — yakuniy xabardan keyin qo'shing:

```python
    await message.answer(
        f"✅ Ro'yxatdan o'tdingiz!\n\n"
        f"Ism: {user.full_name}\n"
        f"Rol: Yuk beruvchi\n\n"
        f"Asosiy menyu:",
        reply_markup=main_menu_provider_kb(),
    )

    pending_load_id = data.get("pending_load_id")
    if pending_load_id is not None:
        await _show_deeplinked_load(message, session, pending_load_id)
```

(`data` — funksiya ichida allaqachon `data = await state.get_data()` bilan
olingan, 549-qator; `state.clear()` bu qatordan keyin, 569-qatorda —
`pending_load_id`ni `data`dan o'qiymiz, `clear()`dan OLDIN emas, muammo
yo'q chunki `data` local o'zgaruvchi.)

- [ ] **Step 5: Tushadigan testlarni yozish**

`tests/test_start_deeplink.py` — loyihaning haqiqiy konvensiyasi bo'yicha
(`tests/test_role_simplification.py`, `tests/test_admin_users.py` bilan
bir xil): qo'lda yozilgan `FakeMessage`/`FakeState`/`FakeSession` klasslari,
real DB yoki `AsyncMock` YO'Q. `monkeypatch.setattr` orqali
`start_handlers.get_load_detail` ni almashtiramiz (haqiqiy DB so'rovi
kerak emas — faqat berilgan `Load`-shu narsa obyektini qaytaradigan soxta
funksiya).

```python
"""Deep-link (/start load_<id>) — yuk raqamini ochish oqimi."""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from bot.handlers import start as start_handlers  # noqa: E402
from bot.states import DriverReg  # noqa: E402
from db.models import UserRole  # noqa: E402


class FakeMessage:
    def __init__(self, text: str = "", user_id: int = 1):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id, full_name="Test User")
        self.contact = None
        self.answers: list[tuple] = []

    async def answer(self, text, reply_markup=None, **kw):
        self.answers.append((text, reply_markup))
        return self

    async def answer_video(self, *a, **kw):
        return self


class FakeState:
    def __init__(self, state=None, data: dict | None = None):
        self.state = state
        self.data = dict(data or {})

    async def set_state(self, state):
        self.state = state

    async def get_state(self):
        return self.state

    async def update_data(self, **kw):
        self.data.update(kw)
        return dict(self.data)

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.state = None
        self.data = {}


class FakeSession:
    async def commit(self):
        pass


def _load(load_id=42, phone="+998901112233"):
    route = SimpleNamespace(origin="Toshkent", destination="Andijon")
    return SimpleNamespace(
        id=load_id, route=route, contact_phone=phone, raw_text="",
        note=None, cargo_type=None, posted_at=None, first_time_phone=True,
    )


def _user(role=UserRole.driver):
    return SimpleNamespace(telegram_id=1, role=role)


# ---------------------------------------------------------------------------
# 1) Ro'yxatdan o'tgan user + deep-link -> darhol ko'rsatiladi
# ---------------------------------------------------------------------------

def test_existing_user_deeplink_shows_load(monkeypatch):
    load = _load()

    async def fake_get_load_detail(session, load_id):
        assert load_id == 42
        return load

    async def fake_get_or_none(session, telegram_id):
        return _user()

    monkeypatch.setattr(start_handlers, "get_load_detail", fake_get_load_detail)
    monkeypatch.setattr(start_handlers, "get_or_none", fake_get_or_none)

    message = FakeMessage(text="/start load_42")
    state = FakeState()
    asyncio.run(start_handlers.cmd_start(message, FakeSession(), state))

    joined = "\n".join(a[0] for a in message.answers)
    assert load.contact_phone in joined   # show_phone=True — raqam matnda


def test_existing_user_deeplink_load_missing(monkeypatch):
    async def fake_get_load_detail(session, load_id):
        return None

    async def fake_get_or_none(session, telegram_id):
        return _user()

    monkeypatch.setattr(start_handlers, "get_load_detail", fake_get_load_detail)
    monkeypatch.setattr(start_handlers, "get_or_none", fake_get_or_none)

    message = FakeMessage(text="/start load_999")
    state = FakeState()
    asyncio.run(start_handlers.cmd_start(message, FakeSession(), state))

    joined = "\n".join(a[0] for a in message.answers)
    assert "mavjud emas" in joined


# ---------------------------------------------------------------------------
# 2) Yangi user + deep-link -> pending_load_id state'da saqlanadi
# ---------------------------------------------------------------------------

def test_new_user_deeplink_saves_pending_load_id(monkeypatch):
    async def fake_get_or_none(session, telegram_id):
        return None   # hali ro'yxatdan o'tmagan

    async def fake_get_instruction(session):
        return {"video_file_id": None, "text": None}

    monkeypatch.setattr(start_handlers, "get_or_none", fake_get_or_none)
    monkeypatch.setattr(start_handlers, "get_instruction", fake_get_instruction)

    message = FakeMessage(text="/start load_42")
    state = FakeState()
    asyncio.run(start_handlers.cmd_start(message, FakeSession(), state))

    assert state.data.get("pending_load_id") == 42


# ---------------------------------------------------------------------------
# 3) DriverReg: telefon berilgach pending yuk ko'rsatiladi, oqim davom etadi
# ---------------------------------------------------------------------------

def test_driver_phone_reveals_pending_load_then_asks_vehicle(monkeypatch):
    load = _load()

    async def fake_get_load_detail(session, load_id):
        return load

    monkeypatch.setattr(start_handlers, "get_load_detail", fake_get_load_detail)

    message = FakeMessage(text="901234567")
    state = FakeState(
        state=DriverReg.waiting_phone,
        data={"role": UserRole.driver.value, "full_name": "Test", "pending_load_id": 42},
    )
    asyncio.run(start_handlers.driver_phone_text(message, state, FakeSession()))

    joined = "\n".join(a[0] for a in message.answers)
    assert load.contact_phone in joined
    assert state.state == DriverReg.waiting_vehicle_type
    assert state.data.get("pending_load_id") is None   # tozalangan
```

- [ ] **Step 6: Testlarni ishga tushirib, xato ekanini ko'rish**

Run: `python3 -m pytest tests/test_start_deeplink.py -q`
Expected: FAIL — hozircha `cmd_start`/`driver_phone_text` deep-link'ni
tushunmaydi (`pending_load_id` state'ga tushmaydi, `get_load_detail` chaqirilmaydi).

- [ ] **Step 7: To'liq test suite**

Run: `python3 -m pytest tests/ -q`
Expected: barchasi yashil.

- [ ] **Step 8: Commit**

```bash
git add bot/handlers/start.py tests/test_start_deeplink.py
git commit -m "start.py: deep-link bilan /start — yuk raqamini ochish oqimi"
```

---

### Task 9: Uchdan-uchgacha qo'lda tekshirish (server tegilmaydi)

**Files:** yo'q (faqat tekshiruv)

- [ ] **Step 1: To'liq test suite yakuniy tekshiruv**

Run: `python3 -m pytest tests/ -q`
Expected: barcha testlar (yangi + eski, jami taxminan 230+) yashil.

- [ ] **Step 2: `python3 -m compileall -q bot db` bilan sintaksis tekshiruvi**

Run: `python3 -m compileall -q bot db`
Expected: xatosiz.

- [ ] **Step 3: Foydalanuvchiga xulosa va deploy so'rovi**

Bu qadam kod emas — implementatsiya tugagach foydalanuvchidan prodga
chiqarish uchun ruxsat so'rash (avvalgi ikki marta shu tartibda
qilingan: reader tuzatishi va parser tuzatishi commit qilingandan keyin
`git push origin main` faqat aniq ruxsatdan keyin bajarilgan).

---

## Self-Review Eslatmasi (implementatsiya boshlashdan oldin o'qing)

- Task 4 dan keyin Task 5/6 gacha oraliqda ba'zi mavjud testlar vaqtincha
  tushishi MUMKIN (chunki `format_load_card` allaqachon telefonni
  yashiryapti, lekin chaqiruvchi kod hali tugma qo'shmagan) — bu KUTILGAN,
  Task 5/6 tugagach tuzaladi. Har Task oxirida **to'liq** suite yashil
  bo'lishi shart, oraliqda emas.
- Yangi dependency (pytest-asyncio, aiosqlite va h.k.) QO'SHILMAYDI — loyiha
  hech qachon real DB/async-test kutubxonasi bilan test qilmaydi (tekshirib
  ko'rilgan: `save_parsed_load`, `get_or_create_route`, barcha aiogram
  handlerlar — hammasi qo'lda yozilgan `FakeSession`/`FakeState`/
  `FakeMessage` + `_Result.scalar_one_or_none()` patterni bilan test
  qilinadi, ko'rish uchun `tests/test_instruction.py`,
  `tests/test_role_simplification.py`). Task 2 va Task 8 shu patternga
  moslab yozilgan — implementatsiyada boshqa yondashuvga o'tilmasin.
