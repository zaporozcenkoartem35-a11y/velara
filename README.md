# 🕯 Velara — Естетичний Telegram-бот Таро та психології стосунків

Сучасний, повністю асинхронний продакшен-бот на **Python 3.11+**, **aiogram 3.x**, **aiosqlite** та **AsyncOpenAI** в ніші сучасного Таро, психології стосунків, сумісності та Арканів за датою народження.

---

## ✦ Головні філософські принципи:
* **Жодного «ШІ-слопу»**: Суворі анти-слоп промпти з бан-листом слів («Всесвіт», «вібрації», «трансформація», «кармічний урок»).
* **Ніякого підручника з Таро**: Одразу переклад сенсу карт на реальну життєву ситуацію без води та загравань.
* **Детермінована математика у Python**: Нейромережа ніколи не рахує дати та Аркани самостійно.

---

## 🛠 Технічний стек:
* **Фреймворк:** `aiogram 3.x` (FSM, Роутери, Middleware).
* **База даних:** `SQLite` (`aiosqlite`), чистий шар репозиторіїв `UserRepository` (готовий до міграції на PostgreSQL).
* **LLM клієнт:** `AsyncOpenAI` (підтримка OpenAI, OpenRouter, Google Gemini, Groq, Claude).
* **Монетизація:** Нативна оплата `Telegram Stars` (`XTR`).
* **Безпека:** In-memory Throttling lock від паралельних запитів до LLM.

---

## 📂 Структура проєкту:
```
gadalka_bot/
├── main.py                     # Вхідна точка, aiohttp сервер + Telegram polling
├── config.py                   # Pydantic Settings з валідацією
├── database/
│   ├── db.py                   # Ініціалізація SQLite (WAL-mode, foreign keys, індекси)
│   ├── models.py               # Dataclass моделі User, Payment, Event
│   └── repository.py           # Асинхронні операції з базою (юзери, баланси, ліміти, воронка)
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
│   ├── tarot_kb.py             # Інтерактивна сітка вибору 3 карт [ ✦ ], пейвол
│   └── payment_kb.py           # Інвойси та кнопки Telegram Stars
├── handlers/
│   ├── start.py                # /start, deep-link (utm/ref), +1 кредит за подругу
│   ├── tarot.py                # FSM-сценарій розкладу, ритуал, списання кредитів
│   ├── compatibility.py        # Сумісність, валідація ДД.ММ.РРРР, ліміт 3/день
│   ├── arcana.py               # Мій Аркан, безкоштовний портрет + апсейл
│   ├── payments.py             # Telegram Stars (pre_checkout, successful_payment)
│   └── admin.py                # /admin (воронка по utm_source), /export
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
Заповніть обов'язкові поля:
* `BOT_TOKEN` — токен від [@BotFather](https://t.me/BotFather).
* `ADMIN_IDS` — ваш числовий Telegram ID (дізнатися у [@userinfobot](https://t.me/userinfobot)).
* `LLM_API_KEY` — ключ API (OpenAI або OpenRouter). Якщо ключа немає — автоматично спрацює інтелектуальний евристичний фоллбек без падіння бота.

### 3. Запуск бота:
```bash
python main.py
```

---

## 📊 Маркетинг та аналітика:

### Deep-links:
* Реклама в каналі: `https://t.me/Velara_bot?start=ukrogoroskop`
* Рефералка: `https://t.me/Velara_bot?start=ref_1092164380`

### Команда `/admin`:
Виводить повну зведену аналітику та **конверсійну воронку за кожним джерелом трафіку**:
`Джерело ➔ Стартів ➔ Завершили 1-й розклад ➔ Клікнули оплату ➔ Оплатили Stars (Конверсія %)`.
