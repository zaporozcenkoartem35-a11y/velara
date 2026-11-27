import os
import sys
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from database.db import init_db
from middlewares.throttling import ThrottlingMiddleware

# Роутери
from handlers.admin import router as admin_router
from handlers.payments import router as payments_router
from handlers.start import router as start_router
from handlers.tarot import router as tarot_router
from handlers.compatibility import router as compatibility_router
from handlers.arcana import router as arcana_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("velara_main")


async def healthcheck(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "app": "Velara Bot", "version": "2.0"})


async def tarot_webapp_page(request: web.Request) -> web.Response:
    if os.path.exists("static/tarot.html"):
        return web.FileResponse("static/tarot.html")
    return web.Response(text="Tarot WebApp is active", status=200)


async def start_web_server(port: int) -> None:
    app = web.Application()
    app.router.add_get("/", healthcheck)
    app.router.add_get("/health", healthcheck)
    app.router.add_get("/tarot", tarot_webapp_page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Healthcheck & WebApp сервер запущено на порту {port}")


async def main() -> None:
    if not settings.BOT_TOKEN or settings.BOT_TOKEN in ("SET_YOUR_TOKEN_HERE", ""):
        logger.error(
            "\n" + "="*50 + "\n"
            "ПОМИЛКА: BOT_TOKEN не налаштовано!\n"
            "Перевірте файл .env та вкажіть дійсний токен від @BotFather.\n"
            + "="*50
        )
        sys.exit(1)

    logger.info("Ініціалізація бази даних...")
    await init_db()

    # Запуск фонового веб-сервера для Render / UptimeRobot
    port_env = os.getenv("PORT")
    port = int(port_env) if port_env and port_env.isdigit() else settings.PORT
    try:
        await start_web_server(port)
    except Exception as e:
        logger.warning(f"Не вдалося запустити локальний веб-сервер на порту {port}: {e}")

    logger.info("Запуск бота Velara...")
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Реєстрація middleware
    throttling = ThrottlingMiddleware()
    dp.message.middleware(throttling)
    dp.callback_query.middleware(throttling)

    # Реєстрація роутерів (порядок має значення!)
    dp.include_router(admin_router)
    dp.include_router(payments_router)
    dp.include_router(start_router)
    dp.include_router(tarot_router)
    dp.include_router(compatibility_router)
    dp.include_router(arcana_router)

    # Очищуємо старі апдейти перед стартом
    await bot.delete_webhook(drop_pending_updates=True)

    bot_info = await bot.get_me()
    logger.info(f"Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")

    # Сповіщаємо адмінів про запуск нової версії
    admin_list = settings.ADMIN_IDS if isinstance(settings.ADMIN_IDS, list) else [settings.ADMIN_IDS]
    for admin_id in admin_list:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🕯 <b>Velara Bot 2.0 активовано!</b>\n\n"
                    f"Бот: @{bot_info.username}\n"
                    f"Усі модулі (Таро, Сумісність, Аркани, Stars) активні.\n"
                    f"Використовуй <code>/admin</code> для перегляду аналітики."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинений.")
