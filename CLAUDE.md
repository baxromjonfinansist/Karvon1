# LOGISTBOT — Loyiha Konteksti va Ishlash Qoidalari

> Bu fayl har bir chatda avtomatik o'qiladi. Maqsad: kontekstni qayta tushuntirmaslik, tokenni tejash, javoblarni to'g'ridan-to'g'ri va amaliy qilish.

## 1. Loyiha (bir marta o'qi, qayta so'ramaslik uchun)

Ikki tomonlama (two-sided) yuk-logistika marketplace, Telegram-asosida, O'zbekiston bozori uchun. To'rt foydalanuvchi turi: (1) yuk qidiruvchi haydovchilar (Isuzu/fura), (2) yuk beruvchilar, (3) bo'sh transportini ijaraga beruvchi egalar, (4) mashinasiz tajribali haydovchilar. Ikkinchi biznes — lizing/fleet (6-9 oy keyinga qoldirilgan, hozircha e'tiborga olinmasin, agar aniq so'ralmasa).

**Arxitektura:** Telegram kanal o'quvchi → AI parser → inson moderatsiyasi → PostgreSQL matching dvigateli → bot interfeyslari.

**Stek:** Python, aiogram, PostgreSQL, SQLAlchemy, Alembic, Redis, Docker Compose.

**Metodologiya:** Lean Startup + Zero to One. Concierge/qo'lda MVP → keyin avtomatlashtirish. Bosqichma-bosqich (stage-gated) qurilmoqda: har bosqich aniq acceptance criteria bilan tugaydi, keyingisiga o'tiladi.

**Daromad modeli:** Obuna (subscription) > komissiya (disintermediation xavfi tufayli). Yuk taklifi birinchi jalb qilinadi (chicken-and-egg yechimi), keyin haydovchilar o'zi keladi.

## 2. Javob berish tartibi — TOKEN TEJASH QOIDALARI

- **Arxitekturani, biznes-modelni yoki metodologiyani qayta tushuntirma** — yuqoridagi kontekst yetarli. To'g'ridan-to'g'ri so'ralgan ishga o't.
- **Faqat so'ralgan bosqichni yoz.** Keyingi bosqichlarni oldindan generatsiya qilma, faqat nomlarini 1 qatorda tilga ol.
- Kod javoblarida — kod + zarur bo'lsa 2-3 qatorlik izoh. Uzun preambula, "bu nima uchun kerak" degan ta'limiy matnlar shart emas (bular allaqachon bilingan).
- Agar savol noaniq bo'lsa, eng oqilona savol ber.
- Jadval/checklist kerak bo'lsa — qisqa va amaliy, uzun tavsif emas.
- Har javobda "Lean Startup", "Zero to One" tamoyillarini qayta tuzmang — ular allaqachon qabul qilingan asos, faqat yangi qaror kerak bo'lsa 1 jumla bilan bog'lang.

## 3. Kod konventsiyalari

- SQLAlchemy modellar: `snake_case`, jadval nomlari ko'plik (`drivers`, `cargo_loads`, `matches`).
- Har bir yangi model uchun Alembic migration alohida yaratiladi (auto-generate + qo'lda tekshirish).
- aiogram handlerlar: `handlers/<domain>.py` bo'yicha bo'lingan (masalan `handlers/driver.py`, `handlers/cargo.py`).
- Feature logikasi hozircha minimal — faqat scaffold/skelet darajasida ishlanadi, avtomatlashtirish keyingi bosqichlarda.
- .env orqali sirlar; hech qachon kodga hardcode qilinmaydi.

## 4. Biznes qoidalari (kod yozayotganda yodda tut)

- Bitta yo'nalish + bitta yuk turi bilan boshlanadi (masalan: Toshkent↔Farg'ona, qurilish materiallari) — ko'p yo'nalishli logikani oldindan generatsiya qilma.
- Matching manual/yarim-manual boshlanadi — to'liq avtomatik matching algoritmini so'ralmaguncha yozma.
- Ishonch/reyting tizimi — asosiy moat, lekin keyingi bosqich (hozir kerak bo'lmasa qo'shma).
- Metrikalar: fill rate, GMV, take rate, LTV/CAC, cohort retention — vanity metrikalarga (ro'yxatdan o'tganlar soni) e'tibor berma.

## 5. Nima qilmaslik kerak

- Lizing/fleet biznesi haqida kod yozma, agar aniq so'ralmasa.
- Bir vaqtda bir nechta bosqichni (masalan ro'yxatdan o'tish + matching + to'lov) birga generatsiya qilma — stage-gated tartibga rioya qil.
- Uzun business-case tushuntirishlar yozma — bu Cursor/Claude Code konteksti, mentor uchun emas.

## 6. Til

Kod va texnik izohlar — ingliz tilida (standart amaliyot). Foydalanuvchiga (Baxromjonga) javoblar — o'zbek tilida, qisqa va amaliy.
