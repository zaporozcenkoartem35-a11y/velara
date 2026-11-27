import asyncio
import logging
import os
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from bot.config import settings
from bot.database.db import init_db
from bot.handlers.admin import router as admin_router
from bot.handlers.user import router as user_router
from bot.services.notifier import notify_admins

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("bot")


async def healthcheck(request: web.Request) -> web.Response:
    """Эндпоинт для облачных хостингов (Render, Koyeb, Railway), чтобы они не усыпляли сервис."""
    return web.json_response({"status": "ok", "bot": "velara_bot"})


async def tarot_page(request: web.Request) -> web.Response:
    """Отдаёт интерактивный Telegram WebApp виджет Таро."""
    return web.FileResponse("static/tarot.html")


async def start_web_server(port: int) -> None:
    """Запуск фонового легковесного HTTP-сервера для healthcheck и WebApp виджета."""
    app = web.Application()
    app.router.add_get("/", healthcheck)
    app.router.add_get("/health", healthcheck)
    app.router.add_get("/tarot", tarot_page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Healthcheck и WebApp веб-сервер запущен на порту {port}")


async def main() -> None:
    # Проверка заполнения токена
    if not settings.BOT_TOKEN or settings.BOT_TOKEN == "SET_YOUR_TOKEN_HERE":
        logger.error(
            "\n" + "="*50 + "\n"
            "ОШИБКА: Токен бота не настроен!\n"
            "Пожалуйста, создайте файл .env на основе .env.example\n"
            "и укажите в нём BOT_TOKEN и ADMIN_IDS.\n"
            + "="*50
        )
        sys.exit(1)

    logger.info("Инициализация базы данных...")
    await init_db()

    logger.info("Запуск бота...")
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Подключаем роутеры (сначала админский, затем пользовательский)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # Если хостинг предоставил переменную PORT (Render, Koyeb, Railway), поднимаем healthcheck-сервер
    port = os.getenv("PORT")
    if port:
        try:
            await start_web_server(int(port))
        except Exception as e:
            logger.warning(f"Не удалось запустить HTTP-сервер на порту {port}: {e}")

    # Очистка старых обновлений перед стартом
    await bot.delete_webhook(drop_pending_updates=True)

    # Оповещение администратора о запуске
    bot_info = await bot.get_me()
    logger.info(f"Бот @{bot_info.username} успешно авторизован!")
    await notify_admins(
        bot,
        f"🕯 <b>Гадалка Велара на связи!</b>\n\n"
        f"Бот: @{bot_info.username}\n"
        f"Алтарь открыт, статистика собирается. Отправьте <code>/stats</code> для просмотра."
    )

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
