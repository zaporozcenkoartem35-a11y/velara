from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from .models import User
from .db import db


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
        Отримує або реєструє користувача.
        Повертає (User, is_new: bool).
        """
        now = cls._now_iso()
        clean_source = (utm_source.strip() if utm_source and utm_source.strip() else "direct")[:64]

        row = await db.fetch_one("SELECT * FROM users WHERE user_id = ?", user_id)

        if row:
            # Оновлюємо активність та профіль
            await db.execute(
                """
                UPDATE users 
                SET last_seen = ?, username = ?, first_name = ?, last_name = ?
                WHERE user_id = ?
                """,
                now, username, first_name, last_name, user_id
            )
            user = User(
                user_id=row["user_id"],
                username=username,
                first_name=first_name,
                last_name=last_name,
                birth_date=row.get("birth_date"),
                utm_source=row.get("utm_source", "direct"),
                referrer_id=row.get("referrer_id"),
                free_tarot_credits=row.get("free_tarot_credits", 1),
                paid_tarot_credits=row.get("paid_tarot_credits", 0),
                free_compat_credits=row.get("free_compat_credits", 1),
                paid_compat_credits=row.get("paid_compat_credits", 0),
                first_seen=row.get("first_seen", now),
                last_seen=now
            )
            return user, False
        else:
            # Новий користувач: 1 безкоштовний розклад Таро + 1 безкоштовна сумісність
            valid_referrer: Optional[int] = None
            if referrer_id and referrer_id != user_id:
                r_row = await db.fetch_one("SELECT user_id FROM users WHERE user_id = ?", referrer_id)
                if r_row:
                    valid_referrer = referrer_id

            await db.execute(
                """
                INSERT INTO users (
                    user_id, username, first_name, last_name, birth_date,
                    utm_source, referrer_id, free_tarot_credits, paid_tarot_credits,
                    free_compat_credits, paid_compat_credits, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, 1, 0, 1, 0, ?, ?)
                """,
                user_id, username, first_name, last_name, clean_source, valid_referrer, now, now
            )

            # Нараховуємо рефереру бонус: +1 розклад Таро та +1 перевірку сумісності
            if valid_referrer:
                await db.execute(
                    """
                    UPDATE users 
                    SET free_tarot_credits = free_tarot_credits + 1,
                        free_compat_credits = free_compat_credits + 1
                    WHERE user_id = ?
                    """,
                    valid_referrer
                )
                await db.execute(
                    "INSERT INTO events (user_id, event_name, payload, created_at) VALUES (?, 'referral_bonus', ?, ?)",
                    valid_referrer, str(user_id), now
                )

            await db.execute(
                "INSERT INTO events (user_id, event_name, payload, created_at) VALUES (?, 'bot_start', ?, ?)",
                user_id, clean_source, now
            )

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
                free_compat_credits=1,
                paid_compat_credits=0,
                first_seen=now,
                last_seen=now
            )
            return user, True

    @classmethod
    async def get_user(cls, user_id: int) -> Optional[User]:
        row = await db.fetch_one("SELECT * FROM users WHERE user_id = ?", user_id)
        if not row:
            return None
        return User(
            user_id=row["user_id"],
            username=row.get("username"),
            first_name=row.get("first_name"),
            last_name=row.get("last_name"),
            birth_date=row.get("birth_date"),
            utm_source=row.get("utm_source", "direct"),
            referrer_id=row.get("referrer_id"),
            free_tarot_credits=row.get("free_tarot_credits", 1),
            paid_tarot_credits=row.get("paid_tarot_credits", 0),
            free_compat_credits=row.get("free_compat_credits", 1),
            paid_compat_credits=row.get("paid_compat_credits", 0),
            first_seen=row.get("first_seen", ""),
            last_seen=row.get("last_seen", "")
        )

    @classmethod
    async def update_birth_date(cls, user_id: int, birth_date: str) -> None:
        await db.execute("UPDATE users SET birth_date = ? WHERE user_id = ?", birth_date, user_id)

    @classmethod
    async def deduct_tarot_credit(cls, user_id: int) -> bool:
        """
        Списує 1 кредит Таро (спочатку безкоштовний, потім платний).
        """
        row = await db.fetch_one(
            "SELECT free_tarot_credits, paid_tarot_credits FROM users WHERE user_id = ?",
            user_id
        )
        if not row:
            return False

        free_c = row.get("free_tarot_credits", 0)
        paid_c = row.get("paid_tarot_credits", 0)

        if free_c > 0:
            await db.execute("UPDATE users SET free_tarot_credits = free_tarot_credits - 1 WHERE user_id = ?", user_id)
            return True
        elif paid_c > 0:
            await db.execute("UPDATE users SET paid_tarot_credits = paid_tarot_credits - 1 WHERE user_id = ?", user_id)
            return True
        return False

    @classmethod
    async def add_tarot_credits(cls, user_id: int, count: int, is_paid: bool = True) -> None:
        column = "paid_tarot_credits" if is_paid else "free_tarot_credits"
        await db.execute(f"UPDATE users SET {column} = {column} + ? WHERE user_id = ?", count, user_id)

    @classmethod
    async def deduct_compat_credit(cls, user_id: int) -> bool:
        """
        Списує 1 кредит перевірки сумісності (спочатку безкоштовний, потім платний).
        """
        row = await db.fetch_one(
            "SELECT free_compat_credits, paid_compat_credits FROM users WHERE user_id = ?",
            user_id
        )
        if not row:
            return False

        free_c = row.get("free_compat_credits", 0)
        paid_c = row.get("paid_compat_credits", 0)

        if free_c > 0:
            await db.execute("UPDATE users SET free_compat_credits = free_compat_credits - 1 WHERE user_id = ?", user_id)
            return True
        elif paid_c > 0:
            await db.execute("UPDATE users SET paid_compat_credits = paid_compat_credits - 1 WHERE user_id = ?", user_id)
            return True
        return False

    @classmethod
    async def add_compat_credits(cls, user_id: int, count: int, is_paid: bool = True) -> None:
        column = "paid_compat_credits" if is_paid else "free_compat_credits"
        await db.execute(f"UPDATE users SET {column} = {column} + ? WHERE user_id = ?", count, user_id)

    @classmethod
    async def record_payment(
        cls,
        user_id: int,
        product_type: str,
        stars_amount: int,
        charge_id: str
    ) -> None:
        now = cls._now_iso()
        await db.execute(
            """
            INSERT INTO payments (user_id, product_type, stars_amount, telegram_payment_charge_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            user_id, product_type, stars_amount, charge_id, now
        )
        await db.execute(
            "INSERT INTO events (user_id, event_name, payload, created_at) VALUES (?, 'payment_success', ?, ?)",
            user_id, f"{product_type}:{stars_amount}XTR", now
        )

    @classmethod
    async def record_event(cls, user_id: int, event_name: str, payload: Optional[str] = None) -> None:
        now = cls._now_iso()
        await db.execute(
            "INSERT INTO events (user_id, event_name, payload, created_at) VALUES (?, ?, ?, ?)",
            user_id, event_name, payload, now
        )

    @classmethod
    async def is_arcana_unlocked(cls, user_id: int) -> bool:
        row = await db.fetch_one("SELECT user_id FROM arcana_unlocks WHERE user_id = ?", user_id)
        return row is not None

    @classmethod
    async def unlock_arcana(cls, user_id: int) -> None:
        now = cls._now_iso()
        await db.execute(
            """
            INSERT INTO arcana_unlocks (user_id, unlocked_at) VALUES (?, ?)
            ON CONFLICT (user_id) DO UPDATE SET unlocked_at = EXCLUDED.unlocked_at
            """,
            user_id, now
        )

    @classmethod
    async def get_referral_info(cls, user_id: int) -> Dict[str, Any]:
        count = await db.fetch_val("SELECT COUNT(*) FROM users WHERE referrer_id = ?", user_id)
        return {"invited_count": count or 0}

    @classmethod
    async def get_admin_metrics(cls) -> Dict[str, Any]:
        """Зведені метрики для панелі керування /admin."""
        total_users = await db.fetch_val("SELECT COUNT(*) FROM users") or 0

        today_prefix = datetime.utcnow().strftime("%Y-%m-%d")
        new_today = await db.fetch_val("SELECT COUNT(*) FROM users WHERE first_seen LIKE ?", f"{today_prefix}%") or 0

        since_24h = (datetime.utcnow() - timedelta(days=1)).isoformat()
        active_24h = await db.fetch_val("SELECT COUNT(*) FROM users WHERE last_seen >= ?", since_24h) or 0

        tarot_done_users = await db.fetch_val(
            "SELECT COUNT(DISTINCT user_id) FROM events WHERE event_name = 'tarot_completed'"
        ) or 0

        paywall_users = await db.fetch_val(
            "SELECT COUNT(DISTINCT user_id) FROM events WHERE event_name LIKE 'paywall%'"
        ) or 0

        clicked_pay_users = await db.fetch_val(
            "SELECT COUNT(DISTINCT user_id) FROM events WHERE event_name = 'clicked_pay'"
        ) or 0

        p_row = await db.fetch_one(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(stars_amount), 0) as stars FROM payments"
        )
        payments_count = p_row["cnt"] if p_row else 0
        total_stars = p_row["stars"] if p_row else 0

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
        Воронка конверсії за UTM-джерелами:
        джерело -> переходи -> розклад -> клік «Оплатити» -> оплат.
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
            LEFT JOIN events e_paywall ON u.user_id = e_paywall.user_id AND e_paywall.event_name LIKE 'paywall%'
            LEFT JOIN events e_click ON u.user_id = e_click.user_id AND e_click.event_name = 'clicked_pay'
            LEFT JOIN payments p ON u.user_id = p.user_id
            GROUP BY u.utm_source
            ORDER BY total_starts DESC;
        """
        return await db.fetch_all(query)

    @classmethod
    async def get_all_users(cls) -> List[Dict[str, Any]]:
        """Вивантаження списку лідів у CSV."""
        return await db.fetch_all("SELECT * FROM users ORDER BY first_seen DESC")
