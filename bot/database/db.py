import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any
from bot.config import settings


async def init_db() -> None:
    """Инициализация таблиц базы данных."""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                source TEXT DEFAULT 'direct',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                clicks_count INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        await db.commit()


async def register_user_start(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    source: Optional[str] = None
) -> bool:
    """
    Регистрирует /start.
    Возвращает True, если пользователь новый, и False, если уже был в базе.
    """
    now = datetime.utcnow().isoformat()
    clean_source = source.strip() if source and source.strip() else "direct"

    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute(
            "SELECT user_id, clicks_count FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            existing = await cursor.fetchone()

        if existing:
            # Пользователь уже был
            await db.execute(
                """
                UPDATE users 
                SET last_seen = ?, clicks_count = clicks_count + 1, username = ?, first_name = ?, last_name = ?
                WHERE user_id = ?
                """,
                (now, username, first_name, last_name, user_id)
            )
            # Логируем событие повторного старта
            await db.execute(
                "INSERT INTO events (user_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                (user_id, "start_repeat", clean_source, now)
            )
            await db.commit()
            return False
        else:
            # Новый пользователь
            await db.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name, source, first_seen, last_seen, clicks_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (user_id, username, first_name, last_name, clean_source, now, now)
            )
            await db.execute(
                "INSERT INTO events (user_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                (user_id, "start_new", clean_source, now)
            )
            await db.commit()
            return True


async def log_event(user_id: int, event_type: str, payload: str) -> None:
    """Логирование клика или действия пользователя."""
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO events (user_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (user_id, event_type, payload, now)
        )
        await db.commit()


async def get_statistics() -> Dict[str, Any]:
    """Сбор общей статистики для команды /stats."""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Всего уникальных пользователей
        async with db.execute("SELECT COUNT(*) as count FROM users") as cur:
            row = await cur.fetchone()
            total_users = row["count"] if row else 0

        # Статистика по источникам (TikTok креативы и UTM)
        async with db.execute(
            "SELECT source, COUNT(*) as count FROM users GROUP BY source ORDER BY count DESC"
        ) as cur:
            sources_rows = await cur.fetchall()
            sources = {r["source"]: r["count"] for r in sources_rows}

        # Статистика по нажатиям на кнопки (что людям больше всего было интересно)
        async with db.execute(
            """
            SELECT payload, COUNT(*) as count 
            FROM events 
            WHERE event_type = 'button_click' 
            GROUP BY payload 
            ORDER BY count DESC
            """
        ) as cur:
            buttons_rows = await cur.fetchall()
            buttons = {r["payload"]: r["count"] for r in buttons_rows}

        # Переходов за последние 24 часа
        async with db.execute(
            """
            SELECT COUNT(DISTINCT user_id) as count 
            FROM events 
            WHERE created_at >= datetime('now', '-1 day')
            """
        ) as cur:
            row = await cur.fetchone()
            last_24h = row["count"] if row else 0

        return {
            "total_users": total_users,
            "last_24h": last_24h,
            "sources": sources,
            "button_interests": buttons
        }


async def get_all_users_export() -> List[Dict[str, Any]]:
    """Получение всех пользователей для экспорта в CSV."""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, username, first_name, last_name, source, first_seen, clicks_count FROM users ORDER BY first_seen DESC"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
