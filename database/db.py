import re
import os
import logging
from typing import Any, List, Optional, Dict
import aiosqlite
from config import settings

logger = logging.getLogger("database")


def normalize_pg_url(url: str) -> str:
    """
    Забезпечує коректний префікс URL для asyncpg:
    перетворює postgres:// або postgresql+asyncpg:// на postgresql://
    """
    if not url:
        return ""
    return re.sub(r"^(postgres|postgresql\+[a-zA-Z0-9_-]+)://", "postgresql://", url.strip())


class DatabaseAdapter:
    def __init__(self):
        self._raw_url = (settings.DATABASE_URL or "").strip()
        self._is_postgres = bool(self._raw_url)
        self._pg_url = normalize_pg_url(self._raw_url) if self._is_postgres else ""
        self._sqlite_path = settings.DATABASE_PATH
        self._pool = None

    @property
    def is_postgres(self) -> bool:
        return self._is_postgres

    async def get_pool(self):
        if self._is_postgres and self._pool is None:
            import asyncpg
            logger.info("Підключення до PostgreSQL пулу через asyncpg...")
            self._pool = await asyncpg.create_pool(dsn=self._pg_url, min_size=1, max_size=10)
        return self._pool

    def translate_query(self, query: str) -> str:
        """
        Перетворює плейсхолдери '?' на '$1', '$2', ... для asyncpg (PostgreSQL).
        """
        if not self._is_postgres:
            return query
        parts = query.split("?")
        if len(parts) <= 1:
            return query
        new_parts = []
        for i, part in enumerate(parts[:-1]):
            new_parts.append(part)
            new_parts.append(f"${i + 1}")
        new_parts.append(parts[-1])
        return "".join(new_parts)

    async def execute(self, query: str, *args) -> None:
        if self._is_postgres:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                q = self.translate_query(query)
                await conn.execute(q, *args)
        else:
            async with aiosqlite.connect(self._sqlite_path) as conn:
                await conn.execute(query, args)
                await conn.commit()

    async def fetch_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        if self._is_postgres:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                q = self.translate_query(query)
                row = await conn.fetchrow(q, *args)
                return dict(row) if row else None
        else:
            async with aiosqlite.connect(self._sqlite_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(query, args) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None

    async def fetch_all(self, query: str, *args) -> List[Dict[str, Any]]:
        if self._is_postgres:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                q = self.translate_query(query)
                rows = await conn.fetch(q, *args)
                return [dict(r) for r in rows]
        else:
            async with aiosqlite.connect(self._sqlite_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(query, args) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]

    async def fetch_val(self, query: str, *args) -> Any:
        if self._is_postgres:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                q = self.translate_query(query)
                return await conn.fetchval(q, *args)
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
    Ініціалізація та міграція схеми для PostgreSQL (Render / Cloud)
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

            # Індекси
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_events_name ON events(event_name);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_utm ON users(utm_source);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);")

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

            # Індекси
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_events_name ON events(event_name);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_utm ON users(utm_source);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);")

            await conn.commit()
            logger.info("SQLite база даних успішно ініціалізована та мігрована.")
