import asyncio
import logging
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from database.repository import UserRepository

logger = logging.getLogger("services.retention")


async def run_retention_cycle(bot: Bot) -> None:
    """
    Один цикл пошуку та м'якого дожиму користувачів:
    - зареєструвалися 2-24 години тому;
    - мають free_tarot_credits >= 1;
    - жодного завершеного розкладу Таро;
    - nudge_sent = 0.
    """
    users = await UserRepository.get_users_for_nudge()
    if not users:
        return

    logger.info(f"Знайдено {len(users)} користувачів для м'якого дожиму.")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌙 Зробити розклад Таро", callback_data="btn_tarot")],
            [InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")]
        ]
    )
    nudge_text = (
        "🌙 <b>Твій перший безкоштовний розклад усе ще чекає</b>\n\n"
        "Якщо є ситуація, яка не дає спокою чи потребує ясності — "
        "можемо розібрати її прямо зараз без зайвої метушні."
    )

    for u in users:
        uid = u["user_id"]
        try:
            await bot.send_message(
                chat_id=uid,
                text=nudge_text,
                reply_markup=kb,
                parse_mode="HTML"
            )
            await UserRepository.mark_nudge_sent(uid)
            await asyncio.sleep(0.05)  # Захист від перевищення лімітів Telegram API
        except TelegramForbiddenError:
            logger.info(f"Користувач {uid} заблокував бота. Позначаємо як is_blocked=1.")
            await UserRepository.mark_user_blocked(uid)
        except Exception as e:
            logger.warning(f"Не вдалося надіслати дожим користувачеві {uid}: {e}")
            await UserRepository.mark_nudge_sent(uid)


async def start_retention_worker(bot: Bot) -> None:
    """
    Фоновий процес ретеншну (перевірка раз на 10 хвилин).
    """
    logger.info("Фоновий воркер ретеншну (дожиму) успішно активовано.")
    while True:
        try:
            await run_retention_cycle(bot)
        except Exception as e:
            logger.error(f"Помилка під час циклу ретеншну: {e}", exc_info=True)
        await asyncio.sleep(600)  # 10 хвилин
