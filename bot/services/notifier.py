import logging
from aiogram import Bot
from bot.config import settings

logger = logging.getLogger(__name__)


async def notify_admins(bot: Bot, text: str) -> None:
    """Отправка уведомления всем администраторам из конфига."""
    if not settings.ADMIN_IDS:
        logger.warning("Администраторы не указаны в ADMIN_IDS! Уведомление не отправлено.")
        return

    admin_list = settings.ADMIN_IDS if isinstance(settings.ADMIN_IDS, list) else [settings.ADMIN_IDS]

    for admin_id in admin_list:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")
