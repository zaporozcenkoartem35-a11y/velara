import html
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, CommandObject
from bot.database.db import register_user_start, log_event
from bot.keyboards.inline import get_main_menu_keyboard
from bot.services.notifier import notify_admins

router = Router(name="user_router")

# Словник тем ворожіння для детальної статистики
FEATURE_NAMES = {
    "thoughts": "🔮 Що він думає про мене?",
    "together": "💔 Чи будемо ми разом?",
    "future": "🕯 Розклад на майбутнє та долю",
    "compatibility": "❤️ Сумісність за датами",
    "finance": "💰 Грошовий канал та кар'єра",
    "gift_spread": "🧿 Особистий розклад у подарунок"
}


@router.message(CommandStart())
async def handle_start(message: Message, command: CommandObject, bot: Bot):
    user = message.from_user
    source = command.args or "direct"

    # Реєструємо в БД
    is_new = await register_user_start(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        source=source
    )

    safe_name = html.escape(user.full_name or "Без імені")
    user_tag = f"@{user.username}" if user.username else "<i>(немає юзернейма)</i>"

    # Сповіщаємо адміністратора
    if is_new:
        admin_text = (
            f"🔮 <b>Нова людина прийшла до Велари!</b>\n\n"
            f"👤 <b>Користувач:</b> {safe_name} ({user_tag})\n"
            f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
            f"🏷 <b>Джерело (TikTok/креатив):</b> <code>{html.escape(source)}</code>"
        )
    else:
        admin_text = (
            f"🔄 <b>Повторний візит до Велари:</b> {safe_name} ({user_tag})\n"
            f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
            f"🏷 <b>Джерело:</b> <code>{html.escape(source)}</code>"
        )

    await notify_admins(bot, admin_text)

    # Атмосферний текст ворожки Велари українською мовою
    welcome_text = (
        f"🕯 <b>Вітаю тебе, душе моя.</b>\n\n"
        f"Я — <b>Велара</b>, спадкова ворожка та тарологиня. "
        f"Карти та зорі не випадково привели тебе до мене саме сьогодні.\n\n"
        f"Якщо ти тут — отже, твоє серце шукає відповіді на найпотаємніші запитання. "
        f"Я допоможу тобі побачити правду: про думки коханої людини, майбутнє стосунків та твою долю.\n\n"
        f"✨ <i>Спробуй наш інтерактивний віджет Таро вище або обери тему нижче:</i>"
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

    # Логуємо дію в БД
    await log_event(user.id, "button_click", feature_title)

    # Сповіщаємо адміністратора
    safe_name = html.escape(user.full_name or "Без імені")
    user_tag = f"@{user.username}" if user.username else "<i>(немає юзернейма)</i>"
    admin_text = (
        f"🎯 <b>Запит на розклад!</b>\n\n"
        f"👤 <b>Користувач:</b> {safe_name} ({user_tag})\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"🕯 <b>Обрана тема:</b> <b>{feature_title}</b>"
    )
    await notify_admins(bot, admin_text)

    # Спливаюче вікно в образі ворожки
    alert_text = (
        "🕯 Карти вже на вівтарі, душе моя...\n\n"
        "Зараз я проводжу обряд очищення колоди перед відкриттям прийому. "
        "Твою енергію почуто — я внесла тебе до свого закритого кола!\n\n"
        "Спробуй поки що відкрити наш інтерактивний віджет вище — карти вже готові дати першу підказку! 🎁"
    )
    await callback.answer(text=alert_text, show_alert=True)
