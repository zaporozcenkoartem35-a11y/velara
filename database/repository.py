import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from config import settings
from .models import User


class UserRepository:
    @staticmethod
    def _now_iso() -> str:
        return datetime.utcnow().isoformat()

    @classmethod
    async def get_or_create_user(
        cls,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
        utm_source: Optional[str] = None,
        referrer_id: Optional[int] = None
    ) -> Tuple[User, bool]:
        """
        Получает или регистрирует пользователя.
        Возвращает (User, is_new: bool).
        """
        now = cls._now_iso()
        clean_source = (utm_source.strip() if utm_source and utm_source.strip() else "direct")[:64]

        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()

            if row:
                # Обновляем профиль и активность
                await db.execute(
                    """
                    UPDATE users 
                    SET last_seen = ?, username = ?, first_name = ?, last_name = ?
                    WHERE user_id = ?
                    """,
                    (now, username, first_name, last_name, user_id)
                )
                await db.commit()
                user = User(
                    user_id=row["user_id"],
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    birth_date=row["birth_date"],
                    utm_source=row["utm_source"],
                    referrer_id=row["referrer_id"],
                    free_tarot_credits=row["free_tarot_credits"],
                    paid_tarot_credits=row["paid_tarot_credits"],
                    first_seen=row["first_seen"],
                    last_seen=now
                )
                return user, False
            else:
                # Новый пользователь: даём 1 стартовый бесплатный расклад
                valid_referrer: Optional[int] = None
                if referrer_id and referrer_id != user_id:
                    # Проверяем существование пригласившего
                    async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,)) as r_cur:
                        if await r_cur.fetchone():
                            valid_referrer = referrer_id

                await db.execute(
                    """
                    INSERT INTO users (
                        user_id, username, first_name, last_name, birth_date,
                        utm_source, referrer_id, free_tarot_credits, paid_tarot_credits,
                        first_seen, last_seen
                    ) VALUES (?, ?, ?, ?, NULL, ?, ?, 1, 0, ?, ?);
                    """,
                    (user_id, username, first_name, last_name, clean_source, valid_referrer, now, now)
                )

                # Если есть валидный реферер — начисляем ему +1 расклад
                if valid_referrer:
                    await db.execute(
                        "UPDATE users SET free_tarot_credits = free_tarot_credits + 1 WHERE user_id = ?",
                        (valid_referrer,)
                    )
                    await db.execute(
                        "INSERT INTO events (user_id, event_name, payload, created_at) VALUES (?, 'referral_bonus', ?, ?)",
                        (valid_referrer, str(user_id), now)
                    )

                await db.execute(
                    "INSERT INTO events (user_id, event_name, payload, created_at) VALUES (?, 'bot_start', ?, ?)",
                    (user_id, clean_source, now)
                )
                await db.commit()

                user = User(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    birth_date=None,
                    utm_source=clean_source,
                    referrer_id=valid_referrer,
                    free_tarot_credits=1,
                    paid_tarot_credits=0,
                    first_seen=now,
                    last_seen=now
                )
                return user, True

    @classmethod
    async def get_user(cls, user_id: int) -> Optional[User]:
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                return User(
                    user_id=row["user_id"],
                    username=row["username"],
                    first_name=row["first_name"],
                    last_name=row["last_name"],
                    birth_date=row["birth_date"],
                    utm_source=row["utm_source"],
                    referrer_id=row["referrer_id"],
                    free_tarot_credits=row["free_tarot_credits"],
                    paid_tarot_credits=row["paid_tarot_credits"],
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"]
                )

    @classmethod
    async def update_birth_date(cls, user_id: int, birth_date: str) -> None:
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            await db.execute("UPDATE users SET birth_date = ? WHERE user_id = ?", (birth_date, user_id))
            await db.commit()

    @classmethod
    async def deduct_tarot_credit(cls, user_id: int) -> bool:
        """
        Списывает 1 расклад. Сначала бесплатные, затем платные.
        Возвращает True в случае успеха, False если баланс 0.
        """
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT free_tarot_credits, paid_tarot_credits FROM users WHERE user_id = ?",
                (user_id,)
            ) as cur:
                row = await cur.fetchone()

            if not row:
                return False

            free_c = row["free_tarot_credits"]
            paid_c = row["paid_tarot_credits"]

            if free_c > 0:
                await db.execute(
                    "UPDATE users SET free_tarot_credits = free_tarot_credits - 1 WHERE user_id = ?",
                    (user_id,)
                )
            elif paid_c > 0:
                await db.execute(
                    "UPDATE users SET paid_tarot_credits = paid_tarot_credits - 1 WHERE user_id = ?",
                    (user_id,)
                )
            else:
                return False

            await db.commit()
            return True

    @classmethod
    async def add_tarot_credits(cls, user_id: int, count: int, is_paid: bool = True) -> None:
        column = "paid_tarot_credits" if is_paid else "free_tarot_credits"
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            await db.execute(
                f"UPDATE users SET {column} = {column} + ? WHERE user_id = ?",
                (count, user_id)
            )
            await db.commit()

    @classmethod
    async def check_and_increment_compat_limit(cls, user_id: int, max_daily: int = 3) -> bool:
        """
        Проверяет и инкрементирует лимит проверок совместимости на сегодня.
        Возвращает True, если лимит не исчерпан, False если превышен.
        """
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT count FROM compat_daily WHERE user_id = ? AND date_str = ?",
                (user_id, today_str)
            ) as cur:
                row = await cur.fetchone()

            if row:
                if row["count"] >= max_daily:
                    return False
                await db.execute(
                    "UPDATE compat_daily SET count = count + 1 WHERE user_id = ? AND date_str = ?",
                    (user_id, today_str)
                )
            else:
                await db.execute(
                    "INSERT INTO compat_daily (user_id, date_str, count) VALUES (?, ?, 1)",
                    (user_id, today_str)
                )

            await db.commit()
            return True

    @classmethod
    async def record_payment(
        cls,
        user_id: int,
        product_type: str,
        stars_amount: int,
        charge_id: str
    ) -> None:
        now = cls._now_iso()
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            await db.execute(
                """
                INSERT INTO payments (user_id, product_type, stars_amount, telegram_payment_charge_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, product_type, stars_amount, charge_id, now)
            )
            await db.execute(
                "INSERT INTO events (user_id, event_name, payload, created_at) VALUES (?, 'payment_success', ?, ?)",
                (user_id, f"{product_type}:{stars_amount}XTR", now)
            )
            await db.commit()

    @classmethod
    async def record_event(cls, user_id: int, event_name: str, payload: Optional[str] = None) -> None:
        now = cls._now_iso()
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            await db.execute(
                "INSERT INTO events (user_id, event_name, payload, created_at) VALUES (?, ?, ?, ?)",
                (user_id, event_name, payload, now)
            )
            await db.commit()

    @classmethod
    async def is_arcana_unlocked(cls, user_id: int) -> bool:
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            async with db.execute("SELECT user_id FROM arcana_unlocks WHERE user_id = ?", (user_id,)) as cur:
                return await cur.fetchone() is not None

    @classmethod
    async def unlock_arcana(cls, user_id: int) -> None:
        now = cls._now_iso()
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO arcana_unlocks (user_id, unlocked_at) VALUES (?, ?)",
                (user_id, now)
            )
            await db.commit()

    @classmethod
    async def get_referral_info(cls, user_id: int) -> Dict[str, Any]:
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
                invited_count = row[0] if row else 0
            return {"invited_count": invited_count}

    @classmethod
    async def get_admin_metrics(cls) -> Dict[str, Any]:
        """Сводные метрики для команды /admin."""
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row

            # Всего пользователей
            async with db.execute("SELECT COUNT(*) as c FROM users") as cur:
                total_users = (await cur.fetchone())["c"]

            # Новых за сегодня (UTC)
            today_prefix = datetime.utcnow().strftime("%Y-%m-%d")
            async with db.execute("SELECT COUNT(*) as c FROM users WHERE first_seen LIKE ?", (f"{today_prefix}%",)) as cur:
                new_today = (await cur.fetchone())["c"]

            # Активных за последние 24 часа
            async with db.execute("SELECT COUNT(*) as c FROM users WHERE last_seen >= datetime('now', '-1 day')") as cur:
                active_24h = (await cur.fetchone())["c"]

            # Завершили хотя бы 1 расклад
            async with db.execute("SELECT COUNT(DISTINCT user_id) as c FROM events WHERE event_name = 'tarot_completed'") as cur:
                tarot_done_users = (await cur.fetchone())["c"]

            # Увидели пейволл
            async with db.execute("SELECT COUNT(DISTINCT user_id) as c FROM events WHERE event_name = 'paywall_shown'") as cur:
                paywall_users = (await cur.fetchone())["c"]

            # Нажали "Оплатить"
            async with db.execute("SELECT COUNT(DISTINCT user_id) as c FROM events WHERE event_name = 'clicked_pay'") as cur:
                clicked_pay_users = (await cur.fetchone())["c"]

            # Платежи и сумма Stars
            async with db.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(stars_amount), 0) as stars FROM payments") as cur:
                p_row = await cur.fetchone()
                payments_count = p_row["cnt"]
                total_stars = p_row["stars"]

            return {
                "total_users": total_users,
                "new_today": new_today,
                "active_24h": active_24h,
                "tarot_done_users": tarot_done_users,
                "paywall_users": paywall_users,
                "clicked_pay_users": clicked_pay_users,
                "payments_count": payments_count,
                "total_stars": total_stars
            }

    @classmethod
    async def get_utm_funnel(cls) -> List[Dict[str, Any]]:
        """
        Воронка конверсии по UTM-меткам:
        источник -> переходов -> прошли 1-й расклад -> нажали «Оплатить» -> оплатили.
        """
        query = """
            SELECT 
                u.utm_source,
                COUNT(DISTINCT u.user_id) as total_starts,
                COUNT(DISTINCT CASE WHEN e_tarot.id IS NOT NULL THEN u.user_id END) as tarot_completed,
                COUNT(DISTINCT CASE WHEN e_paywall.id IS NOT NULL THEN u.user_id END) as saw_paywall,
                COUNT(DISTINCT CASE WHEN e_click.id IS NOT NULL THEN u.user_id END) as clicked_pay,
                COUNT(DISTINCT p.id) as payments_count,
                COALESCE(SUM(p.stars_amount), 0) as total_stars
            FROM users u
            LEFT JOIN events e_tarot ON u.user_id = e_tarot.user_id AND e_tarot.event_name = 'tarot_completed'
            LEFT JOIN events e_paywall ON u.user_id = e_paywall.user_id AND e_paywall.event_name = 'paywall_shown'
            LEFT JOIN events e_click ON u.user_id = e_click.user_id AND e_click.event_name = 'clicked_pay'
            LEFT JOIN payments p ON u.user_id = p.user_id
            GROUP BY u.utm_source
            ORDER BY total_starts DESC;
        """
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]
