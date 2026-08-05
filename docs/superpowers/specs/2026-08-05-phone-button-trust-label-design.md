# Telefon-tugma (deep-link) + "1-qo'l" ishonch yorlig'i — dizayn

Sana: 2026-08-05. Manba: Baxromjonning so'rovi + tasdiqlangan misol (Qo'ng'iroq
qilish tugmali e'lon boti).

## Maqsad

Yuk kartalarida telefon endi matn emas — **"📞 Qo'ng'iroq qilish"** tugmasi.
Bu ikki narsaga xizmat qiladi:

1. **O'sish kanali**: Baxromjon yuk kartalarini turli haydovchilar guruhiga
   qo'lda tashlaydi (forward/copy). Tugma bosilsa — botga hali start
   bosmagan odam ro'yxatdan o'tishga yo'naltiriladi, ro'yxatdan o'tgach o'sha
   yukning raqami ko'rsatiladi. Shu orqali guruhlardan botga foydalanuvchi
   oqimi keladi.
2. **Ishonch**: yangi ishonch yorlig'i — raqam bazada birinchi marta
   ko'rinsa "💯 100% 1-qo'l", aks holda "✅ 1-qo'l — dispetcher/logist yo'q".

## 1. Karta formati

`format_load_card(load, now=None, show_phone=False)` — yangi parametr:

- `show_phone=False` (**standart** — feed, avtomatik xabarnoma): "📞" qatori
  yo'q. O'rniga chaqiruvchi kod inline URL-tugma qo'shadi:
  `InlineKeyboardButton(text="📞 Qo'ng'iroq qilish", url=build_load_deeplink(load.id))`.
- `show_phone=True` (faqat "reveal" nuqtasida — pastga qarang): haqiqiy
  raqam matn qatorida ko'rsatiladi ("📞 {phone}"), tugma qo'shilmaydi.

Ishonch yorlig'i — route qatoridan keyin, HAR IKKI rejimda ham:
- `load.first_time_phone == True` → `"💯 100% 1-qo'l (birinchi marta)"`
- aks holda → `"✅ 1-qo'l — dispetcher/logist yo'q"`

Bu o'zgarish **hamma joyda** qo'llaniladi: `driver.py` feed (`_fmt_load`/
`_take_kb`) va `notify_service.py` avtomatik xabarnoma (`_take_kb`). Har
ikkalasida ham mavjud tugma ("🤝 Olish" / "🔕 Xabarnomani o'chirish") bilan
BIRGA "📞 Qo'ng'iroq qilish" tugmasi qo'shiladi (alohida qator).

## 2. Deep-link va "reveal" nuqtasi

Yangi modul `bot/services/deeplink.py` (sof funksiyalar, test qilinadi):

```python
def set_bot_username(username: str) -> None: ...      # main.py startup'da 1 marta
def build_load_deeplink(load_id: int) -> str: ...      # "https://t.me/<u>?start=load_<id>"
def parse_load_start_payload(args: str | None) -> int | None: ...  # "load_42" -> 42
```

`main.py`: Bot yaratilgandan keyin `me = await bot.get_me()`,
`set_bot_username(me.username)`.

`bot/handlers/start.py` `cmd_start`:

- Argumentni ajratib oladi (`message.text` dan `/start <args>`).
- `load_id = parse_load_start_payload(args)`.
- **Ro'yxatdan o'tgan user + load_id bor**: o'sha yukni bazadan o'qiydi.
  Topilsa — `format_load_card(load, show_phone=True)` + `_take_kb(load.id)`
  ko'rsatiladi, keyin asosiy menyu. Topilmasa (o'chirilgan/band) — "Bu yuk
  endi mavjud emas, lekin yangi yuklar bor 👇" + asosiy menyu.
- **Yangi user + load_id bor**: `state.update_data(pending_load_id=load_id)`
  qilingandan keyin oddiy oqim (instruksiya → rol → ism → telefon) davom
  etadi.
- `load_id` yo'q (oddiy `/start`) — hozirgi xatti-harakat o'zgarmaydi.

**Telefon berilgach reveal** (tanlangan variant: ism+telefon, mashina
turidan OLDIN):

- `DriverReg`: `driver_phone_contact`/`driver_phone_text` telefonni
  saqlagandan keyin, `waiting_vehicle_type`ga o'tishdan OLDIN —
  `pending_load_id` bor-yo'qligini tekshiradi. Bor bo'lsa yukni ko'rsatadi
  (`show_phone=True`) va state'dan `pending_load_id`ni tozalaydi, so'ng
  odatdagidek mashina turi so'raladi.
- `ProviderReg`: `_finish_provider_reg` (yagona, yakuniy qadam) — user
  yaratilgach, "✅ Ro'yxatdan o'tdingiz" xabaridan keyin xuddi shu tekshiruv
  va ko'rsatish.
- Yuk topilmasa (band/eskirgan) — "Bu yuk endi mavjud emas" + oqim davom
  etadi (xatolik emas, oqim to'xtamaydi).

## 3. "1-qo'l" ishonch yorlig'i — hisoblash

`save_parsed_load` (`parser_service.py`) — yuk saqlanishidan OLDIN:

```python
exists = await session.execute(
    select(Load.id).where(Load.contact_phone == parsed.contact).limit(1)
)
first_time = exists.scalar_one_or_none() is None
```

`Load.first_time_phone: Mapped[bool]` — yangi ustun (Alembic migratsiya,
`server_default="true"` — eski yozuvlar tarixiy, ta'sir qilmaydi).

**Cheklov (ongli qabul qilingan, oddiy variant tanlandi):** yuklar 6
soatdan keyin (band bo'lmasa) bazadan butunlay o'chadi (`delete_stale_loads`).
Shu sabab bir xil raqam 6+ soat tanaffusdan keyin qayta "birinchi marta"
bo'lib chiqishi mumkin. Doimiy ro'yxat (logist_service'dagi kabi) qurish —
keyingi bosqich, hozir so'ralmagan.

## Testlar

- `deeplink.py`: `build_load_deeplink`/`parse_load_start_payload` — sof
  funksiya testlari (to'g'ri/noto'g'ri payload, none holatlar).
- `format_load_card(show_phone=...)`: ikkala rejim uchun testlar (tugma
  bor/yo'q, raqam matn ko'rinishida bor/yo'q, ishonch yorlig'i ikkala
  holatda ham bor).
- `save_parsed_load`: birinchi marta vs qaytariluvchi raqam uchun
  `first_time_phone` to'g'ri hisoblanishi.
- `start.py`: deep-link bilan `/start` — ro'yxatdan o'tgan user uchun
  darhol ko'rsatish; yangi user uchun `pending_load_id` saqlanishi va
  telefon bosqichida ko'rsatilishi; yuk topilmasa oqim buzilmasligi.

## Qamrov (ta'sir qiluvchi fayllar)

- `bot/services/deeplink.py` — yangi
- `bot/services/load_service.py` — `format_load_card` (show_phone param)
- `bot/services/parser_service.py` — `save_parsed_load` (first_time_phone)
- `bot/handlers/driver.py` — `_take_kb`/`_fmt_load` chaqiruvlari
- `bot/services/notify_service.py` — `_take_kb`
- `bot/handlers/start.py` — `cmd_start`, `driver_phone_*`, `_finish_provider_reg`
- `bot/main.py` — `set_bot_username` chaqiruvi
- `db/models.py` + yangi Alembic migratsiya — `Load.first_time_phone`
