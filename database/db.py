import aiosqlite
import logging
from config import settings

logger = logging.getLogger("database")


async def init_db() -> None:
    """Ініціалізація та надійна міграція бази даних SQLite."""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")

        # 1. Міграція/Створення таблиці events
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events';") as cur:
            has_events = await cur.fetchone() is not None

        if has_events:
            async with db.execute("PRAGMA table_info(events);") as cur:
                e_cols = {row[1] for row in await cur.fetchall()}
            if "event_type" in e_cols:
                logger.info("Міграція структури таблиці events...")
                await db.execute("ALTER TABLE events RENAME TO events_old;")
                await db.execute("""
                    CREATE TABLE events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        event_name TEXT NOT NULL,
                        payload TEXT,
                        created_at TEXT NOT NULL
                    );
                """)
                await db.execute("""
                    INSERT INTO events (id, user_id, event_name, payload, created_at)
                    SELECT id, user_id, COALESCE(event_name, event_type), payload, created_at FROM events_old;
                """)
                await db.execute("DROP TABLE events_old;")

        # Створення таблиці events якщо її немає
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_name TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """)

        # 2. Таблиця користувачів
        await db.execute("""
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
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );
        """)

        # Міграція колонок users
        async with db.execute("PRAGMA table_info(users);") as cur:
            u_cols = {row[1] for row in await cur.fetchall()}

        if "birth_date" not in u_cols:
            await db.execute("ALTER TABLE users ADD COLUMN birth_date TEXT;")
        if "utm_source" not in u_cols:
            await db.execute("ALTER TABLE users ADD COLUMN utm_source TEXT DEFAULT 'direct';")
            if "source" in u_cols:
                await db.execute("UPDATE users SET utm_source = source WHERE utm_source IS NULL OR utm_source = 'direct';")
        if "referrer_id" not in u_cols:
            await db.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER;")
        if "free_tarot_credits" not in u_cols:
            await db.execute("ALTER TABLE users ADD COLUMN free_tarot_credits INTEGER DEFAULT 1;")
        if "paid_tarot_credits" not in u_cols:
            await db.execute("ALTER TABLE users ADD COLUMN paid_tarot_credits INTEGER DEFAULT 0;")

        # 3. Ліміти на сумісність
        await db.execute("""
            CREATE TABLE IF NOT EXISTS compat_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date_str TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                UNIQUE(user_id, date_str),
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """)

        # 4. Платежі (Telegram Stars)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_type TEXT NOT NULL,
                stars_amount INTEGER NOT NULL,
                telegram_payment_charge_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """)

        # 5. Платні Аркани
        await db.execute("""
            CREATE TABLE IF NOT EXISTS arcana_unlocks (
                user_id INTEGER PRIMARY KEY,
                unlocked_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );
        """)

        # Створення індексів
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_name ON events(event_name);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_utm ON users(utm_source);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);")

        await db.commit()
    logger.info("База даних успішно ініціалізована та мігрована.")
