# Yuk Logistika Marketplace Bot

O'zbekiston ichidagi yuk logistika Telegram bot marketplace — Faza 1 skeleti.

## Tezkor boshlash

### 1. Talablarni o'rnatish

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Muhit o'zgaruvchilarini sozlash

```bash
cp .env.example .env
```

`.env` faylini to'ldiring:

| O'zgaruvchi    | Qayerdan olish                         |
|----------------|----------------------------------------|
| `BOT_TOKEN`    | [@BotFather](https://t.me/BotFather)  |
| `DATABASE_URL` | quyidagi docker-compose dan avtomatik  |
| `REDIS_URL`    | quyidagi docker-compose dan avtomatik  |

### 3. PostgreSQL va Redis-ni ko'tarish

```bash
docker-compose up -d
```

Tekshirish:
```bash
docker-compose ps    # postgres va redis "healthy" bo'lishi kerak
```

### 4. Ma'lumotlar bazasini migratsiya qilish

```bash
alembic upgrade head
```

Muvaffaqiyatli bo'lsa barcha jadvallar yaratiladi:
`users`, `vehicles`, `routes`, `loads`, `deals`,
`subscriptions`, `transactions`, `ratings`, `driver_preferred_routes`

### 5. Botni ishga tushirish

```bash
python -m bot.main
```

Telegram-da `/start` yuboring — `Bot ishlayapti ✅` javobini olishingiz kerak.

---

## Papka strukturasi

```
yuk_marketplace_bot/
├── bot/
│   ├── main.py          # entry point — polling
│   ├── config.py        # pydantic-settings (.env o'qiydi)
│   ├── handlers/
│   │   ├── start.py     # /start handler (ishlaydigan)
│   │   ├── driver.py    # haydovchi oqimi (TODO Faza 1)
│   │   ├── provider.py  # yuk beruvchi oqimi (TODO Faza 1)
│   │   └── admin.py     # admin panel (TODO Faza 1)
│   ├── keyboards/       # inline/reply tugmalar (TODO)
│   ├── states/          # FSM StatesGroup (TODO)
│   └── services/        # biznes-logika (TODO)
├── db/
│   ├── database.py      # async engine, session, Base
│   ├── models.py        # barcha SQLAlchemy modellari
│   └── migrations/      # Alembic (env.py, versions/)
├── docker-compose.yml   # postgres:16 + redis:7
├── alembic.ini
├── requirements.txt
└── .env.example
```

## Foydali buyruqlar

```bash
# Yangi migratsiya yaratish (modellar o'zgarganda)
alembic revision --autogenerate -m "tavsif"

# Migratsiya tarixini ko'rish
alembic history

# Docker konteynerlarni to'xtatish
docker-compose down

# Ma'lumotlar bilan birga tozalash
docker-compose down -v
```

## Keyingi bosqichlar (Faza 1)

1. Haydovchi va yuk beruvchi ro'yxatdan o'tish FSM
2. Yo'nalish tanlash va haydovchi feed
3. Yuk joylash oqimi (yuk beruvchi)
4. Admin moderatsiya navbati
5. AI-parser + Telethon reader
6. Obuna + Payme/Click to'lov integratsiyasi
7. Reyting tizimi
