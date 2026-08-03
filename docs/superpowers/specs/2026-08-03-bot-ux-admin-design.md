# Bot UX va admin panel — dizayn (6 faza)

Sana: 2026-08-03. Manba: Baxromjonning 7 ta talabi.

Har faza mustaqil deploy qilinadi va o'z acceptance criteria si bilan tugaydi.

---

## Faza 1 — Yuk oynasi, yuk yoshi, obuna bo'limini yashirish

### 1.1 Yuklar 6 soat turadi (talab #7)

**Muammo:** yuklar soni 200–300 ga tushib, keyin 700–800 ga chiqadi.

**Sabab:** `bot/services/load_service.py` da `FRESH_MINUTES = 120` — 2 soatdan
eski `open`/`pending` yuklar o'chiriladi va feed ham shu oynani ko'rsatadi.
Tozalash faqat haydovchi «📦 Yuklar» bosganda (`delete_stale_loads`,
`bot/handlers/driver.py`) ishlaydi — shuning uchun o'chirish to'lqin-to'lqin
bo'ladi: hech kim bosmasa yuk yig'iladi, kimdir bosishi bilan bir zumda
yuzlab yuk o'chadi.

**Yechim:**
- `FRESH_MINUTES = 360` (6 soat).
- `delete_stale_loads` ni `bot/services/notify_service.py` dagi davriy siklga
  qo'shish (har 10 daqiqada) — yuklar "bitta-bitta" chiqib ketadi, sakrash
  yo'qoladi. Handler'lardagi chaqiruvlar qoladi (zarar qilmaydi, lekin
  endi asosiy tozalovchi fon jarayoni).

**Acceptance:** `FRESH_MINUTES=360`; fon siklda tozalash logi bor; yuk soni
30 daqiqa ichida keskin sakramaydi (>50% tushmaydi).

### 1.2 Yuk kartasida yosh (yangi talab)

Har yuk e'lonida yuk qachon paydo bo'lgani ko'rinsin: `🕒 40 daqiqa oldin`,
`🕒 2 soat oldin`, `🕒 hozir` (5 daqiqagacha).

Manba: `Load.posted_at` (Telegram post vaqti; feed oynasi ham shunga tayanadi).
Formatlash — `bot/handlers/driver.py` dagi `_fmt_load` ichida, yordamchi
sof funksiya `humanize_age(posted_at) -> str` orqali (test yoziladi).

**Acceptance:** yuk kartasida yosh qatori bor; `humanize_age` uchun test
(hozir / daqiqa / soat chegaralari).

### 1.3 «💳 Obunam» bo'limini olib tashlash (talab #5)

- `bot/keyboards/__init__.py`: `main_menu_driver_kb` dan «💳 Obunam» tugmasi
  olib tashlanadi.
- `bot/handlers/driver.py`: obuna tekshiruvi (`is_subscribed` gate'lari)
  foydalanuvchini to'smaydi; «💳 Obunam» handleri o'chiriladi.
- Kod (`Subscription` model, `grant_sub` admin buyrug'i) **saqlanadi** —
  keyingi bosqichda qaytariladi.

**Acceptance:** haydovchi menyusida obuna tugmasi yo'q; obunasiz user
yuklarni to'liq ko'radi; admin `/grant_sub` hali ishlaydi.

---

## Faza 2 — «⬅️ Orqaga» BARCHA ko'p qadamli oqimlarda (talab #1)

**Qoida:** foydalanuvchi qayerda bo'lmasin, bitta qadam orqaga qayta olsin.
Asosiy menyuga sakrash faqat «🏠 Asosiy bo'lim» orqali bo'ladi.

**Qamrov (har bir bosqich):**

1. Yuk qidirish oqimi (`bot/handlers/driver.py`, inline):
   viloyat → mashina turi → manzil → ro'yxat (sahifalash) → yuk kartasi.
   Har bosqichda inline «⬅️ Orqaga» — oldingi ro'yxatga qaytadi.
2. Haydovchi ro'yxatdan o'tishi (`DriverReg`): ism → telefon → mashina turi →
   tonnaj → chiqish viloyati → manzil → xabarnoma.
3. Yuk beruvchi ro'yxatdan o'tishi (`ProviderReg`): ism → telefon.
4. Yuk joylash (`LoadPost`): yo'nalish → yuk turi → vazn → narx → tasdiq.
5. Sozlamalar va reyting oqimlari (`settings.py`, `RatingFlow`).

**Texnik yondashuv:**
- Inline oqim uchun callback_data allaqachon holatni saqlaydi
  (`veh|origin|...`) — «Orqaga» shu ma'lumotdan oldingi bosqichni tiklaydi,
  yangi state kerak emas.
- FSM oqimlari uchun har state'da «⬅️ Orqaga» reply tugmasi; handler
  oldingi state'ga qaytaradi va o'sha savolni qayta so'raydi.
- Umumiy yordamchi: `bot/keyboards/__init__.py` da `back_row(callback_data)`
  va `back_reply_kb(...)`.

**Acceptance:** yuqoridagi 5 oqimning har bir qadamida orqaga tugmasi bor va
bosilganda aynan bitta qadam orqaga qaytadi (asosiy menyuga emas); har oqim
uchun kamida bitta test.

---

## Faza 3 — Rollar 2 taga qisqaradi + mashina ma'lumoti saqlanadi (talab #6)

### 3.1 Ro'yxatga olish

`role_choice_kb` da faqat: **🚛 Haydovchi**, **📦 Yuk beruvchi**.
`asset_owner` va `staff_driver` yangi ro'yxatga olinmaydi. Enum'dagi
qiymatlar **saqlanadi** (eski yozuvlar buzilmasin).

### 3.2 Mavjud userlarni ko'chirish

`asset_owner` va `staff_driver` rolidagi userlarga bir martalik so'rov:

```
Botda rollar soddalashtirildi. Iltimos, o'zingizga mos rolni tanlang:
[🚛 Haydovchi]  [📦 Yuk beruvchi]
```

Bosilgach rol yangilanadi va mos asosiy menyu yuboriladi. Yuborish —
admin buyrug'i orqali (`/migrate_roles`), bir marta, natijasi hisobot bilan.

### 3.3 Mashina turi bazaga saqlanadi

**Muammo:** `DriverReg` da mashina turi va tonnaj so'raladi, lekin
`create_user` ularni qabul qilmaydi — ma'lumot yo'qoladi.

**Yechim:** `users` jadvaliga `vehicle_type` (Enum) va `capacity_t`
(Numeric(6,2)) ustunlari + Alembic migratsiya. `create_user` va
`update_user_role` ularni qabul qiladi, `start.py` uzatadi.

**Acceptance:** yangi ro'yxatdan o'tgan haydovchining mashina turi va tonnaji
bazada; rol tanlash so'rovi ishlaydi; migratsiya `alembic upgrade head` bilan
o'tadi.

---

## Faza 4 — Admin: yangi user xabarnomasi + userlar ro'yxati (talab #2)

Yangi modul: `bot/handlers/admin_users.py` (admin.py 510 qator — o'smasin).

### 4.1 Yangi user xabarnomasi

Ro'yxatdan o'tish tugagach barcha adminlarga:

```
🆕 Yangi foydalanuvchi
Ism: Alisher Qodirov
Tel: +998901234567
Rol: 🚛 Haydovchi
Mashina: Isuzu, 5 t
```

Xabar yuborilmasa (bot bloklangan) — asosiy oqim buzilmaydi.

### 4.2 Userlar ro'yxati

Admin panel → «📇 Userlar ro'yxati»:
- Sahifalash: 10 tadan, «◀️ Oldingi / Keyingi ▶️».
- Filtr: barchasi / 🚛 haydovchilar / 📦 yuk beruvchilar.
- Har qatorda: ism, telefon, rol, mashina turi + tonnaj, ro'yxatdan o'tgan sana.

**Acceptance:** yangi user qo'shilganda adminlarga xabar keladi; ro'yxat
sahifalanadi va filtr ishlaydi.

---

## Faza 5 — Broadcast: matn va media (talab #3)

Yangi modul: `bot/handlers/admin_broadcast.py`.

Admin panel → «📢 Xabarnoma» → qabul qiluvchini tanlash:

1. **Barcha userlar**
2. **Guruh bo'yicha** — rol (haydovchi / yuk beruvchi) yoki viloyat
   (`pref_origin`)
3. **Ro'yxatdan belgilash** — sahifalangan ro'yxat, har biri ☑️/⬜️,
   tanlanganlar FSM state'da saqlanadi

Keyin kontent: matn **yoki** media (video, rasm, hujjat, izoh bilan).
Bot `copy_message` bilan yuboradi (forward emas — manba ko'rinmasin).

Yuborishdan oldin: qabul qiluvchilar soni + preview + «✅ Yuborish / ❌ Bekor».

Yuborish: sekundiga ~20 xabar (flood limitdan saqlanish), `TelegramForbiddenError`
(bloklaganlar) alohida sanaladi. Oxirida hisobot: yuborildi / bloklangan / xato.

**Acceptance:** uchala tanlov usuli ishlaydi; matn va video yetib boradi;
bloklagan userlar broadcastni to'xtatmaydi; hisobot chiqadi.

---

## Faza 6 — Bot instruksiyasi (talab #4)

Yangi modul: `bot/handlers/instruction.py` + `app_settings` jadvali
(`key` PK, `value` text, `file_id` text, `updated_at`) — kelajakda boshqa
sozlamalar uchun ham ishlatiladi.

### 6.1 Admin tomoni

Admin panel → «🎬 Instruksiya»:
- «📹 Video yuklash» — admin video yuboradi, `file_id` saqlanadi.
- «📝 Matn» — tushuntirish matni saqlanadi.
- «👁 Ko'rish» — hozirgi instruksiyani ko'rsatadi.

### 6.2 Foydalanuvchi tomoni

`/start` (yangi user): instruksiya bo'lsa — video + matn, so'ng
«✅ Ko'rdim» / «⏭ Keyinroq» tugmalari. **Ixtiyoriy** — ikkalasi ham rol
tanlashga olib boradi. Instruksiya sozlanmagan bo'lsa — to'g'ridan rol tanlash.

Mavjud userlar uchun: «📖 Instruksiya» tugmasi asosiy menyuda.

**Acceptance:** admin video+matn yuklaydi; yangi user `/start` da ko'radi va
ikkala tugma ham rol tanlashga o'tkazadi; instruksiya yo'q bo'lsa oqim
buzilmaydi.

---

## Bajarish tartibi

```
Faza 1  ──►  Faza 2  ──►  Faza 3  ──►  Faza 4
                                  └──►  Faza 5  (parallel)
                                  └──►  Faza 6  (parallel)
```

Faza 4 Faza 3 dagi `users.vehicle_type` ustuniga bog'liq. Faza 5 va 6
bir-biriga bog'liq emas va alohida modullarda yoziladi.

## Umumiy talablar

- Har faza: testlar + `python3 -m pytest tests/ -q` yashil.
- Migratsiya bo'lsa — alohida Alembic revision, qo'lda tekshirilgan.
- Deploy: `main` ga push → GitHub Actions → server.
- Har fazadan keyin prod'da tekshirish (bot menyusi va loglar).
