import io
import csv
import html
from aiogram import Router, Bot, F
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command, Filter
from bot.config import settings
from bot.database.db import get_statistics, get_all_users_export


class AdminFilter(Filter):
    """Фильтр для проверки, является ли пользователь администратором."""
    async def __call__(self, message: Message) -> bool:
        if not settings.ADMIN_IDS:
            return False
        admin_list = settings.ADMIN_IDS if isinstance(settings.ADMIN_IDS, list) else [settings.ADMIN_IDS]
        return message.from_user.id in admin_list


router = Router(name="admin_router")
router.message.filter(AdminFilter())


@router.message(Command("stats"))
async def handle_stats(message: Message):
    """Отображение сводной аналитики."""
    stats = await get_statistics()

    total_users = stats["total_users"]
    last_24h = stats["last_24h"]
    sources = stats["sources"]
    button_interests = stats["button_interests"]

    # Формируем блок источников (TikTok метки)
    sources_text = ""
    if sources:
        for src, cnt in sources.items():
            pct = round((cnt / total_users * 100), 1) if total_users > 0 else 0
            sources_text += f"  • <code>{html.escape(src)}</code>: <b>{cnt}</b> ({pct}%)\n"
    else:
        sources_text = "  <i>Переходов пока нет</i>\n"

    # Формируем блок интереса к функциям
    buttons_text = ""
    if button_interests:
        total_clicks = sum(button_interests.values())
        for btn, cnt in button_interests.items():
            pct = round((cnt / total_clicks * 100), 1) if total_clicks > 0 else 0
            buttons_text += f"  • {html.escape(btn)}: <b>{cnt}</b> ({pct}%)\n"
    else:
        buttons_text = "  <i>Нажатий на разделы пока нет</i>\n"

    text = (
        f"📊 <b>СТАТИСТИКА ПРИЁМА У ВЕЛАРЫ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Всего пришло людей:</b> <code>{total_users}</code>\n"
        f"⚡ <b>За последние 24 часа:</b> <code>{last_24h}</code>\n\n"
        f"🏷 <b>Конверсия по креативам (TikTok):</b>\n"
        f"{sources_text}\n"
        f"🎯 <b>Самые частые запросы к картам:</b>\n"
        f"{buttons_text}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>Используйте /export, чтобы выгрузить всю базу в CSV.</i>"
    )

    await message.answer(text=text, parse_mode="HTML")


@router.message(Command("export"))
async def handle_export(message: Message):
    """Экспорт базы контактов в CSV-файл."""
    users = await get_all_users_export()

    if not users:
        await message.answer("В базе пока нет пользователей.")
        return

    # Генерация CSV в памяти
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["user_id", "username", "first_name", "last_name", "source", "first_seen", "clicks_count"]
    )
    writer.writeheader()
    for row in users:
        writer.writerow(row)

    csv_data = output.getvalue().encode("utf-8-sig")  # utf-8-sig для корректного открытия в Excel
    input_file = BufferedInputFile(csv_data, filename="leads.csv")

    await message.answer_document(
        document=input_file,
        caption=f"📁 Выгрузка базы: всего {len(users)} пользователей."
    )


@router.message(Command("help_admin"))
async def handle_help_admin(message: Message, bot: Bot):
    """Справка по командам и созданию ссылок для TikTok."""
    bot_info = await bot.get_me()
    bot_username = bot_info.username or "your_bot"

    text = (
        f"⚙️ <b>Команды администратора:</b>\n"
        f"• <code>/stats</code> — посмотреть общую аналитику и конверсию\n"
        f"• <code>/export</code> — скачать базу пользователей в CSV\n"
        f"• <code>/help_admin</code> — эта справка\n\n"
        f"🔗 <b>Как создавать ссылки для TikTok:</b>\n"
        f"Чтобы понимать, какое именно видео или креатив приносит людей, "
        f"делайте ссылки с меткой <code>?start=ТЕГ</code>:\n\n"
        f"• Видео про Таро 1: <code>https://t.me/{bot_username}?start=tt_taro1</code>\n"
        f"• Видео про Совместимость: <code>https://t.me/{bot_username}?start=tt_sovmest</code>\n"
        f"• Шапка профиля: <code>https://t.me/{bot_username}?start=tt_bio</code>\n\n"
        f"Когда человек перейдёт по ссылке и нажмёт Старт, бот автоматически "
        f"запишет эту метку в статистику и пришлёт её вам!"
    )
    await message.answer(text=text, parse_mode="HTML")
