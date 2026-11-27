# 🕯 Velara — Естетичний Telegram-бот Таро та психології стосунків

Сучасний, повністю асинхронний продакшен-бот на **Python 3.11+**, **aiogram 3.x**, **PostgreSQL** (`asyncpg`) / **SQLite** (`aiosqlite`) та **AsyncOpenAI** в ніші сучасного Таро, психології стосунків, сумісності та Арканів за датою народження.

---

## ✦ Головні філософські принципи:
* **Жодного «ШІ-слопу»**: Суворі анти-слоп промпти з бан-листом слів («Всесвіт», «вібрації», «трансформація», «кармічний урок»).
* **Ніякого підручника з Таро**: Одразу переклад сенсу карт на реальну життєву ситуацію без води та загравань.
* **Детермінована математика у Python**: Нейромережа ніколи не рахує дати та Аркани самостійно.

---

## 🛠 Технічний стек:
* **Фреймворк:** `aiogram 3.x` (FSM, Роутери, Middleware).
* **База даних:** Dual-engine адаптер з підтримкою **PostgreSQL** (хмарний продакшен Render/Supabase через `asyncpg`) та автоматичним fallback на **SQLite** (`aiosqlite`). Повна авто-міграція колонок та таблиць.
* **LLM клієнт:** `AsyncOpenAI` (OpenAI, OpenRouter, Google Gemini, Groq, Claude) з обмеженням `max_tokens=650`, `timeout=30.0` та захистом від збоїв HTML-парсингу Telegram.
* **Монетизація:** Нативна оплата `Telegram Stars` (`XTR`), динамічне налаштування цін з `.env`, команди `/paysupport` та `/refund`.
* **Безпека:** In-memory Throttling lock від подвійних кліків і паралельних генерацій, валідація запитання (5–500 символів).

---

## 📂 Структура проєкту:
```
gadalka_bot/
├── main.py                     # Вхідна точка, aiohttp healthcheck сервер + Telegram polling
├── config.py                   # Pydantic Settings з підтримкою PostgreSQL, динамічних цін та прапорців
├── database/
│   ├── db.py                   # Dual-Engine адаптер (PostgreSQL asyncpg / SQLite aiosqlite, авто-міграції)
│   ├── models.py               # Dataclass моделі User (із балансом Таро та сумісності), Payment, Event
│   └── repository.py           # Чистий шар репозиторію з уніфікованими SQL-запитами
├── middlewares/
│   └── throttling.py           # Захист від подвійних кліків та блокування на час генерації LLM
├── services/
│   ├── arcana_math.py          # Точна математика розрахунку 22 Старших Арканів у Python
│   ├── tarot_deck.py           # Повна колода з 78 карт Таро українською мовою
│   └── llm.py                  # Клієнт LLM, ретраї, HTML-санітайзер для Telegram
├── prompts/
│   ├── tarot_prompt.py         # Промпт Таро (Суть / Що приховано / Що робити)
│   ├── compatibility_prompt.py # Промпт сумісності (Де іскра / Головні граблі / Реальний прогноз)
│   └── arcana_prompt.py        # Промпти для базового та глибокого любовного сценарію
├── keyboards/
│   ├── menu.py                 # Головне меню, скасування, профіль
│   ├── tarot_kb.py             # Інтерактивна сітка вибору карт [ ✦ ], динамічні пейволи Таро та Сумісності
│   └── payment_kb.py           # Інвойси та кнопки Telegram Stars (динамічні ціни)
├── handlers/
│   ├── start.py                # /start, deep-link (utm/ref), +1 Таро та +1 Сумісність за подругу
│   ├── tarot.py                # FSM Таро (5-500 символів), списання кредитів, HTML fallback
│   ├── compatibility.py        # Сумісність (1 безкоштовна перевірка, далі Stars або рефералка)
│   ├── arcana.py               # Мій Аркан, безкоштовний портрет + платний любовний сценарій
│   ├── payments.py             # Telegram Stars, каталог товарів, обробка оплат, /paysupport
│   └── admin.py                # /admin (воронка по utm_source), /export (CSV), /refund (повернення Stars)
├── assets/cards/               # Локальні зображення карт (опціонально)
└── static/tarot.html           # Інтерактивний Telegram Mini App віджет
```

---

## 🚀 Швидкий запуск:

### 1. Встановлення залежностей:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Налаштування `.env`:
Створіть `.env` на основі `.env.example`:
```bash
cp .env.example .env
```
Основні змінні:
* `BOT_TOKEN` — токен від [@BotFather](https://t.me/BotFather).
* `ADMIN_IDS` — ваш числовий Telegram ID.
* `DATABASE_URL` — (опціонально) рядок підключення до PostgreSQL (наприклад, на Render). Якщо порожній — використовується локальний SQLite.
* `LLM_API_KEY` — ключ API (OpenAI або OpenRouter).
* `PRICE_TAROT_1`, `PRICE_TAROT_3`, `PRICE_ARCANA_LOVE`, `PRICE_COMPAT` — гнучке налаштування цін у Stars.
* `SUPPORT_USERNAME` — юзернейм підтримки для команди `/paysupport`.
* `ENABLE_WEBAPP` — `false` (за замовчуванням: чисті inline-кнопки в чаті) або `true`.

### 3. Запуск бота:
```bash
python main.py
```

---

## 📊 Маркетинг та команди:

### Посилання та бонуси:
* Реклама в каналах: `https://t.me/Velara_bot?start=ukrogoroskop`
* Реферальна програма: `https://t.me/Velara_bot?start=ref_<user_id>` (дає запросившому **+1 розклад Таро** та **+1 перевірку сумісності**).

### Команди:
* `/paysupport` — інформація про безпеку платежів у Telegram Stars, умови повернення та контакт підтримки.
* `/admin` — зведена аналітика та воронка за UTM-джерелами трафіку.
* `/export` — вивантаження бази лідів у CSV (сумісне з SQLite та PostgreSQL).
* `/refund <user_id> <charge_id>` — повернення платежу Stars користувачеві безпосередньо через Telegram API.
