import re
import os
import urllib.parse
import asyncio
import logging
from typing import Any, List, Optional, Dict, Tuple
import aiosqlite
from config import settings

logger = logging.getLogger("database")


def clean_postgres_dsn(raw_url: str) -> Tuple[str, bool]:
    """
    Очищує та адаптує DSN для asyncpg (сумісність із Neon.tech / Render):
    - Нормалізує префікс до postgresql://
    - Видаляє libpq-специфічні query-параметри на кшталт channel_binding
    - Визначає необхідність SSL (для Neon.tech завжди обов'язковий)
    """
    if not raw_url:
        return "", False

    clean_url = re.sub(r"^(postgres|postgresql\+[a-zA-Z0-9_-]+)://", "postgresql://", raw_url.strip())
    parsed = urllib.parse.urlsplit(clean_url)

    query_params = urllib.parse.parse_qs(parsed.query)

    # Видаляємо channel_binding та несумісні для asyncpg параметри
    query_params.pop("channel_binding", None)
    query_params.pop("gssencmode", None)

    # Визначаємо SSL режим
    sslmode = query_params.pop("sslmode", [""])[0].lower()
    needs_ssl = (
        sslmode in ("require", "verify-ca", "verify-full")
        or "neon.tech" in parsed.netloc.lower()
        or "supabase.co" in parsed.netloc.lower()
    )
    query_params.pop("ssl", None)

    # Збираємо чистий DSN
    new_query = urllib.parse.urlencode({k: v[0] for k, v in query_params.items()})
    final_dsn = urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        new_query,
        parsed.fragment
    ))
    return final_dsn, needs_ssl


class DatabaseAdapter:
    def __init__(self):
        self._raw_url = (settings.DATABASE_URL or "").strip()
        self._is_postgres = bool(self._raw_url)
        self._sqlite_path = settings.DATABASE_PATH
        self._pool = None

    @property
    def is_postgres(self) -> bool:
        return self._is_postgres

    async def get_pool(self):
        if self._is_postgres:
            if self._pool is None or getattr(self._pool, "_closed", False) or getattr(self._pool, "_closing", False):
                import asyncpg
                dsn, needs_ssl = clean_postgres_dsn(self._raw_url)
                logger.info("Підключення до PostgreSQL пулу через asyncpg (Neon.tech / Cloud)...")
                
                pool_kwargs: Dict[str, Any] = {
                    "dsn": dsn,
                    "min_size": 1,
                    "max_size": 5,
                    "max_inactive_connection_lifetime": 60.0,
                    "command_timeout": 30.0
                }
                if needs_ssl:
                    pool_kwargs["ssl"] = "require"

                self._pool = await asyncpg.create_pool(**pool_kwargs)
        return self._pool

    def translate_query(self, query: str) -> str:
        """
        Перетворює плейсхолдери '?' на '$1', '$2', ... для asyncpg (PostgreSQL).
        Безпечно ігнорує знаки '?' усередині рядкових літералів '...'.
        """
        if not self._is_postgres:
            return query

        out = []
        param_idx = 1
        in_single_quotes = False
        for ch in query:
            if ch == "'":
                in_single_quotes = not in_single_quotes
                out.append(ch)
            elif ch == "?" and not in_single_quotes:
                out.append(f"${param_idx}")
                param_idx += 1
            else:
                out.append(ch)
        return "".join(out)

    async def execute(self, query: str, *args) -> None:
        if self._is_postgres:
            q = self.translate_query(query)
            for attempt in range(2):
                try:
                    pool = await self.get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute(q, *args)
                    return
                except Exception as conn_err:
                    err_name = conn_err.__class__.__name__
                    if attempt == 0 and ("Connection" in err_name or "Reset" in err_name or "Pipe" in err_name):
                        logger.warning(f"PostgreSQL з'єднання перервано ({err_name}). Відновлення пулу...")
                        self._pool = None
                        await asyncio.sleep(0.5)
                        continue
                    raise
        else:
            async with aiosqlite.connect(self._sqlite_path) as conn:
                await conn.execute(query, args)
                await conn.commit()

    async def fetch_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        if self._is_postgres:
            q = self.translate_query(query)
            for attempt in range(2):
                try:
                    pool = await self.get_pool()
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow(q, *args)
                        return dict(row) if row else None
                except Exception as conn_err:
                    err_name = conn_err.__class__.__name__
                    if attempt == 0 and ("Connection" in err_name or "Reset" in err_name or "Pipe" in err_name):
                        logger.warning(f"PostgreSQL з'єднання перервано ({err_name}). Відновлення пулу...")
                        self._pool = None
                        await asyncio.sleep(0.5)
                        continue
                    raise
        else:
            async with aiosqlite.connect(self._sqlite_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(query, args) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None

    async def fetch_all(self, query: str, *args) -> List[Dict[str, Any]]:
        if self._is_postgres:
            q = self.translate_query(query)
            for attempt in range(2):
                try:
                    pool = await self.get_pool()
                    async with pool.acquire() as conn:
                        rows = await conn.fetch(q, *args)
                        return [dict(r) for r in rows]
                except Exception as conn_err:
                    err_name = conn_err.__class__.__name__
                    if attempt == 0 and ("Connection" in err_name or "Reset" in err_name or "Pipe" in err_name):
                        logger.warning(f"PostgreSQL з'єднання перервано ({err_name}). Відновлення пулу...")
                        self._pool = None
                        await asyncio.sleep(0.5)
                        continue
                    raise
        else:
            async with aiosqlite.connect(self._sqlite_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(query, args) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]

    async def fetch_val(self, query: str, *args) -> Any:
        if self._is_postgres:
            q = self.translate_query(query)
            for attempt in range(2):
                try:
                    pool = await self.get_pool()
                    async with pool.acquire() as conn:
                        return await conn.fetchval(q, *args)
                except Exception as conn_err:
                    err_name = conn_err.__class__.__name__
                    if attempt == 0 and ("Connection" in err_name or "Reset" in err_name or "Pipe" in err_name):
                        logger.warning(f"PostgreSQL з'єднання перервано ({err_name}). Відновлення пулу...")
                        self._pool = None
                        await asyncio.sleep(0.5)
                        continue
                    raise
        else:
            async with aiosqlite.connect(self._sqlite_path) as conn:
                async with conn.execute(query, args) as cur:
                    row = await cur.fetchone()
                    return row[0] if row else None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


db = DatabaseAdapter()


async def init_db() -> None:
    """
    Ініціалізація та міграція схеми для PostgreSQL (Neon.tech / Render / Cloud)
    або SQLite (локальний fallback).
    """
    if db.is_postgres:
        logger.info("Ініціалізація PostgreSQL через asyncpg...")
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            # 1. Таблиця користувачів
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    birth_date TEXT,
                    utm_source TEXT DEFAULT 'direct',
                    referrer_id BIGINT,
                    free_tarot_credits INTEGER DEFAULT 1,
                    paid_tarot_credits INTEGER DEFAULT 0,
                    free_compat_credits INTEGER DEFAULT 1,
                    paid_compat_credits INTEGER DEFAULT 0,
                    nudge_sent INTEGER DEFAULT 0,
                    is_blocked INTEGER DEFAULT 0,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );
            """)

            # Авто-міграції для додавання нових колонок у PG
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS birth_date TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS utm_source TEXT DEFAULT 'direct';")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS free_tarot_credits INTEGER DEFAULT 1;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS paid_tarot_credits INTEGER DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS free_compat_credits INTEGER DEFAULT 1;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS paid_compat_credits INTEGER DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS nudge_sent INTEGER DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked INTEGER DEFAULT 0;")

            # 2. Таблиця подій воронки
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    event_name TEXT NOT NULL,
                    payload TEXT,
                    created_at TEXT NOT NULL
                );
            """)

            # 3. Таблиця платежів
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    product_type TEXT NOT NULL,
                    stars_amount INTEGER NOT NULL,
                    telegram_payment_charge_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # 4. Таблиця розблокованих платних Арканів
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS arcana_unlocks (
                    user_id BIGINT PRIMARY KEY,
                    unlocked_at TEXT NOT NULL
                );
            """)

            # 5. Таблиця лімітів сумісності (legacy / backward-compatibility)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS compat_daily (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    date_str TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    UNIQUE(user_id, date_str)
                );
            """)

            # 6. Кэш розрахованих Арканів (базовий та любовний)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS arcana_cache (
                    user_id BIGINT NOT NULL,
                    birth_date TEXT NOT NULL,
                    base_portrait TEXT,
                    love_scenario TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, birth_date)
                );
            """)

            # 7. Історія успішних розкладів
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS readings_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    reading_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # 8. Використання токенів LLM (юніт-економіка)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_usage (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    feature TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # Індекси
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_events_name ON events(event_name);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_utm ON users(utm_source);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_user ON readings_history(user_id, id DESC);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at);")

        logger.info("PostgreSQL база даних успішно підключена та мігрована.")
    else:
        logger.info("Ініціалізація локальної SQLite бази даних...")
        async with aiosqlite.connect(settings.DATABASE_PATH) as conn:
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")

            # 1. Міграція таблиці events якщо вона існувала зі старим полем event_type
            async with conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events';") as cur:
                has_events = await cur.fetchone() is not None

            if has_events:
                async with conn.execute("PRAGMA table_info(events);") as cur:
                    e_cols = {row[1] for row in await cur.fetchall()}
                if "event_type" in e_cols:
                    logger.info("Міграція структури таблиці events (SQLite)...")
                    await conn.execute("ALTER TABLE events RENAME TO events_old;")
                    await conn.execute("""
                        CREATE TABLE events (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            event_name TEXT NOT NULL,
                            payload TEXT,
                            created_at TEXT NOT NULL
                        );
                    """)
                    await conn.execute("""
                        INSERT INTO events (id, user_id, event_name, payload, created_at)
                        SELECT id, user_id, COALESCE(event_name, event_type), payload, created_at FROM events_old;
                    """)
                    await conn.execute("DROP TABLE events_old;")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    event_name TEXT NOT NULL,
                    payload TEXT,
                    created_at TEXT NOT NULL
                );
            """)

            # 2. Таблиця користувачів
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    birth_date TEXT,
                    utm_source TEXT DEFAULT 'direct',
                    referrer_id INTEGER,
                    free_tarot_credits INTEGER DEFAULT 1,
                    paid_tarot_credits INTEGER DEFAULT 0,
                    free_compat_credits INTEGER DEFAULT 1,
                    paid_compat_credits INTEGER DEFAULT 0,
                    nudge_sent INTEGER DEFAULT 0,
                    is_blocked INTEGER DEFAULT 0,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );
            """)

            # Перевірка та міграція колонок users в SQLite
            async with conn.execute("PRAGMA table_info(users);") as cur:
                u_cols = {row[1] for row in await cur.fetchall()}

            if "birth_date" not in u_cols:
                await conn.execute("ALTER TABLE users ADD COLUMN birth_date TEXT;")
            if "utm_source" not in u_cols:
                await conn.execute("ALTER TABLE users ADD COLUMN utm_source TEXT DEFAULT 'direct';")
                if "source" in u_cols:
                    await conn.execute("UPDATE users SET utm_source = source WHERE utm_source IS NULL OR utm_source = 'direct';")
            if "referrer_id" not in u_cols:
                await conn.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER;")
            if "free_tarot_credits" not in u_cols:
                await conn.execute("ALTER TABLE users ADD COLUMN free_tarot_credits INTEGER DEFAULT 1;")
            if "paid_tarot_credits" not in u_cols:
                await conn.execute("ALTER TABLE users ADD COLUMN paid_tarot_credits INTEGER DEFAULT 0;")
            if "free_compat_credits" not in u_cols:
                await conn.execute("ALTER TABLE users ADD COLUMN free_compat_credits INTEGER DEFAULT 1;")
            if "paid_compat_credits" not in u_cols:
                await conn.execute("ALTER TABLE users ADD COLUMN paid_compat_credits INTEGER DEFAULT 0;")
            if "nudge_sent" not in u_cols:
                await conn.execute("ALTER TABLE users ADD COLUMN nudge_sent INTEGER DEFAULT 0;")
            if "is_blocked" not in u_cols:
                await conn.execute("ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0;")

            # 3. Сумісність (legacy)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS compat_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    date_str TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    UNIQUE(user_id, date_str)
                );
            """)

            # 4. Платежі
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    product_type TEXT NOT NULL,
                    stars_amount INTEGER NOT NULL,
                    telegram_payment_charge_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # 5. Аркани
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS arcana_unlocks (
                    user_id INTEGER PRIMARY KEY,
                    unlocked_at TEXT NOT NULL
                );
            """)

            # 6. Кэш розрахованих Арканів
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS arcana_cache (
                    user_id INTEGER NOT NULL,
                    birth_date TEXT NOT NULL,
                    base_portrait TEXT,
                    love_scenario TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, birth_date)
                );
            """)

            # 7. Історія успішних розкладів
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS readings_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    reading_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # 8. Юніт-економіка LLM
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    feature TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # Індекси
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_events_name ON events(event_name);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_utm ON users(utm_source);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_user ON readings_history(user_id, id DESC);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at);")

            await conn.commit()
            logger.info("SQLite база даних успішно ініціалізована та мігрована.")
