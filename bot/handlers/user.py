import html
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, CommandObject
from bot.database.db import register_user_start, log_event
from bot.keyboards.inline import get_main_menu_keyboard
from bot.services.notifier import notify_admins

router = Router(name="user_router")

# Словарь тем гадания для детальной статистики
FEATURE_NAMES = {
    "thoughts": "🔮 Что он думает обо мне?",
    "together": "💔 Будем ли мы вместе?",
    "future": "🕯 Расклад на будущее и судьбу",
    "compatibility": "❤️ Совместимость по датам",
    "finance": "💰 Денежный канал и карьера",
    "gift_spread": "🧿 Личный расклад в подарок"
}


@router.message(CommandStart())
async def handle_start(message: Message, command: CommandObject, bot: Bot):
    user = message.from_user
    source = command.args or "direct"

    # Регистрируем в БД
    is_new = await register_user_start(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        source=source
    )

    safe_name = html.escape(user.full_name or "Без имени")
    user_tag = f"@{user.username}" if user.username else "<i>(нет юзернейма)</i>"

    # Оповещаем администратора
    if is_new:
        admin_text = (
            f"🔮 <b>Новый человек пришёл к Веларе!</b>\n\n"
            f"👤 <b>Пользователь:</b> {safe_name} ({user_tag})\n"
            f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
            f"🏷 <b>Источник (TikTok/креатив):</b> <code>{html.escape(source)}</code>"
        )
    else:
        admin_text = (
            f"🔄 <b>Повторный визит к Веларе:</b> {safe_name} ({user_tag})\n"
            f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
            f"🏷 <b>Источник:</b> <code>{html.escape(source)}</code>"
        )

    await notify_admins(bot, admin_text)

    # Атмосферный текст гадалки Велары
    welcome_text = (
        f"🕯 <b>Приветствую тебя, душа моя.</b>\n\n"
        f"Я — <b>Велара</b>, потомственная гадалка и таролог. "
        f"Карты и звёзды не случайно привели тебя ко мне именно сегодня.\n\n"
        f"Если ты здесь — значит, твоё сердце ищет ответы на сокровенные вопросы. "
        f"Я помогу тебе увидеть правду: о мыслях любимого человека, судьбе отношений и твоём будущем.\n\n"
        f"🔮 <b>Выбери, что волнует тебя больше всего прямо сейчас:</b>"
    )

    await message.answer(
        text=welcome_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("feature:"))
async def handle_feature_click(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    feature_key = callback.data.split(":", 1)[1]
    feature_title = FEATURE_NAMES.get(feature_key, feature_key)

    # Логируем действие в БД
    await log_event(user.id, "button_click", feature_title)

    # Оповещаем администратора
    safe_name = html.escape(user.full_name or "Без имени")
    user_tag = f"@{user.username}" if user.username else "<i>(нет юзернейма)</i>"
    admin_text = (
        f"🎯 <b>Запрос на расклад!</b>\n\n"
        f"👤 <b>Пользователь:</b> {safe_name} ({user_tag})\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"🕯 <b>Выбранная тема:</b> <b>{feature_title}</b>"
    )
    await notify_admins(bot, admin_text)

    # Всплывающее окно в образе гадалки (не сухое "технические работы", а мистическая калибровка)
    alert_text = (
        "🕯 Карты уже на алтаре, душа моя...\n\n"
        "Прямо сейчас я провожу обряд очищения колоды перед открытием приёма. "
        "Твоя энергия услышана — я внесла тебя в свой личный круг!\n\n"
        "Как только алтарь будет открыт, я первой пришлю тебе подробный расклад в подарок! 🎁"
    )
    await callback.answer(text=alert_text, show_alert=True)
