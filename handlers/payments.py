import html
import logging
from aiogram import Router, Bot, F
from aiogram.types import (
    CallbackQuery,
    Message,
    PreCheckoutQuery,
    LabeledPrice,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.filters import Command
from config import settings
from database.repository import UserRepository

logger = logging.getLogger("handlers.payments")
router = Router(name="payments_router")


def get_products_catalog() -> dict:
    """
    Каталог товарів Telegram Stars з динамічними цінами строго з .env / settings.
    """
    return {
        "tarot_1": {
            "title": "1 розклад Таро",
            "description": "Глибокий аналіз стосунків на 3 карти з психологічним розбором",
            "stars": settings.tarot_price_1
        },
        "tarot_3": {
            "title": "3 розклади Таро",
            "description": "Пакет із 3 розкладів Таро зі знижкою 15%",
            "stars": settings.tarot_price_3
        },
        "arcana_love": {
            "title": "Любовний сценарій за Арканами",
            "description": "Аналіз типажу партнерів, повторюваних тригерів та сумісності",
            "stars": settings.arcana_love_price
        },
        "compat_1": {
            "title": "1 перевірка сумісності",
            "description": "Розрахунок перетину Арканів пари та лінії взаємного тяжіння",
            "stars": settings.compat_price
        }
    }


@router.message(Command("paysupport"))
async def handle_paysupport(message: Message):
    """
    Офіційна інформація щодо підтримки та повернень у Telegram Stars.
    """
    support_user = settings.clean_support_username
    text = (
        "✦ <b>Підтримка платежів Velara (Telegram Stars)</b>\n\n"
        "Усі транзакції в боті здійснюються офіційно через систему <b>Telegram Stars (XTR)</b> "
        "з дотриманням правил безпеки та конфіденційності платформи Telegram.\n\n"
        "<b>Важлива інформація:</b>\n"
        "• <b>Активація послуг:</b> розклади Таро, перевірки сумісності та любовні сценарії активуються миттєво після успішної транзакції.\n"
        "• <b>Збій або неотримання:</b> якщо через мережеву затримку баланс не оновився, надішли нам скріншот оплати з квитанцією Telegram.\n"
        "• <b>Повернення (Refund):</b> за зверненням у підтримку ми можемо повернути зірки (Stars) на твій баланс Telegram у разі технічного збою.\n\n"
        f"💬 <b>Служба підтримки:</b> @{support_user}"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Написати в підтримку",
                    url=f"https://t.me/{support_user}"
                )
            ],
            [
                InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")
            ]
        ]
    )
    await message.answer(text=text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("buy_stars:"))
async def handle_buy_stars(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    product_type = callback.data.split(":", 1)[1]

    catalog = get_products_catalog()
    product = catalog.get(product_type)
    if not product:
        await callback.answer("Товар не знайдено", show_alert=True)
        return

    # Логуємо клік по оплаті для воронки в адмінці
    await UserRepository.record_event(user_id, "clicked_pay", product_type)

    prices = [LabeledPrice(label=product["title"], amount=product["stars"])]

    await bot.send_invoice(
        chat_id=user_id,
        title=f"✦ {product['title']}",
        description=product["description"],
        payload=f"{product_type}:{user_id}",
        currency="XTR",  # Telegram Stars
        prices=prices,
        provider_token=""  # Для Telegram Stars provider_token завжди порожній рядок
    )
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    """Підтверджуємо готовність прийняти платіж."""
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot):
    """Обробка успішної оплати через Telegram Stars."""
    sp = message.successful_payment
    user_id = message.from_user.id
    payload = sp.invoice_payload or ""
    product_type = payload.split(":", 1)[0]
    stars_amount = sp.total_amount
    charge_id = sp.telegram_payment_charge_id

    # Записуємо платіж у БД
    await UserRepository.record_payment(
        user_id=user_id,
        product_type=product_type,
        stars_amount=stars_amount,
        charge_id=charge_id
    )

    catalog = get_products_catalog()
    product_title = catalog[product_type]["title"] if product_type in catalog else product_type

    # Миттєвий алерт адміну про оплату
    db_user = await UserRepository.get_user(user_id)
    utm_source = db_user.utm_source if db_user else "unknown"
    admin_list = settings.ADMIN_IDS if isinstance(settings.ADMIN_IDS, list) else [settings.ADMIN_IDS]
    admin_alert = (
        f"💰 <b>Нова оплата Stars!</b>\n\n"
        f"• Послуга: <b>{product_title}</b>\n"
        f"• Сума: <b>{stars_amount} ⭐</b>\n"
        f"• Юзер: <code>{user_id}</code> (@{message.from_user.username or 'немає'})\n"
        f"• Джерело: <code>{html.escape(utm_source)}</code>"
    )
    for admin_id in admin_list:
        try:
            await bot.send_message(chat_id=admin_id, text=admin_alert, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Не вдалося надіслати алерт про оплату адміну {admin_id}: {e}")

    # Видаємо придбану послугу відповідно до типу
    if product_type == "tarot_1":
        await UserRepository.add_tarot_credits(user_id, 1, is_paid=True)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🌙 Зробити розклад Таро", callback_data="btn_tarot")],
                [InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")]
            ]
        )
        await message.answer(
            "✨ <b>Дякую за підтримку Velara!</b>\n\n"
            "Тобі нараховано <b>+1 повний розклад Таро</b> 🌙. Можеш скористатися ним просто зараз.",
            reply_markup=kb,
            parse_mode="HTML"
        )
    elif product_type == "tarot_3":
        await UserRepository.add_tarot_credits(user_id, 3, is_paid=True)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🌙 Зробити розклад Таро", callback_data="btn_tarot")],
                [InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")]
            ]
        )
        await message.answer(
            "✨ <b>Дякую за підтримку Velara!</b>\n\n"
            "Тобі нараховано <b>+3 розклади Таро</b> 🌙. Вони збережені у твоєму профілі.",
            reply_markup=kb,
            parse_mode="HTML"
        )
    elif product_type == "compat_1":
        await UserRepository.add_compat_credits(user_id, 1, is_paid=True)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✨ Перевірити сумісність", callback_data="btn_compatibility")],
                [InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")]
            ]
        )
        await message.answer(
            "✨ <b>Дякую за підтримку Velara!</b>\n\n"
            "Тобі нараховано <b>+1 перевірку сумісності</b> ✨. Можеш скористатися нею просто зараз.",
            reply_markup=kb,
            parse_mode="HTML"
        )
    elif product_type == "arcana_love":
        await UserRepository.unlock_arcana(user_id)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📖 Читати мій любовний сценарій",
                        callback_data="show_unlocked_love_scenario"
                    )
                ],
                [InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")]
            ]
        )
        await message.answer(
            "✨ <b>Твій любовний сценарій розблоковано!</b>\n\n"
            "Глибокий аналіз типажу партнерів, повторюваних тригерів та родових патернів тепер доступний.",
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        logger.warning(f"Невідомий product_type після оплати: {product_type}")
        await message.answer(
            "✨ <b>Оплату отримано!</b> Дякуємо за підтримку. Твій доступ активовано.",
            parse_mode="HTML"
        )
