from datetime import datetime
from aiogram import Router, Bot, F
from aiogram.types import (
    CallbackQuery,
    Message,
    PreCheckoutQuery,
    LabeledPrice,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from config import settings
from database.repository import UserRepository
from services.arcana_math import calculate_base_arcana, calculate_soul_arcana, get_arcana_info
from services.llm import llm_service
from keyboards.menu import get_main_menu_keyboard

router = Router(name="payments_router")

PRODUCTS_CATALOG = {
    "tarot_1": {
        "title": "1 розклад Таро",
        "description": "Глибокий аналіз стосунків на 3 карти з психологічним розбором",
        "stars": settings.TAROT_PRICE_1
    },
    "tarot_3": {
        "title": "3 розклади Таро",
        "description": "Пакет із 3 розкладів Таро зі знижкою 15%",
        "stars": settings.TAROT_PRICE_3
    },
    "arcana_love": {
        "title": "Любовний сценарій за Арканами",
        "description": "Аналіз типажу партнерів, повторюваних тригерів та сумісності",
        "stars": settings.ARCANA_LOVE_PRICE
    }
}


@router.callback_query(F.data.startswith("buy_stars:"))
async def handle_buy_stars(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    product_type = callback.data.split(":", 1)[1]

    product = PRODUCTS_CATALOG.get(product_type)
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
        provider_token=""  # Для Telegram Stars provider_token завжди порожній рядок!
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

    # Видаємо придбану послугу
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
            "Тобі нараховано <b>+3 повних розклади Таро</b> 🌙. Вони збережуться за тобою назавжди.",
            reply_markup=kb,
            parse_mode="HTML"
        )

    elif product_type == "arcana_love":
        await UserRepository.unlock_arcana(user_id)
        db_user = await UserRepository.get_user(user_id)

        if db_user and db_user.birth_date:
            parsed = datetime.strptime(db_user.birth_date, "%d.%m.%Y")
            base_num = calculate_base_arcana(parsed.day)
            soul_num = calculate_soul_arcana(parsed.day, parsed.month, parsed.year)
            base_info = get_arcana_info(base_num)
            soul_info = get_arcana_info(soul_num)

            loading = await message.answer("<i>Платіж підтверджено! Формую твій індивідуальний любовний сценарій...</i>", parse_mode="HTML")

            deep_text = await llm_service.generate_arcana_deep_love(
                birth_date=db_user.birth_date,
                base_arcana_name=f"{base_num}. {base_info['name']}",
                soul_arcana_name=f"{soul_num}. {soul_info['name']}"
            )

            header = (
                "🔒 <b>Твій ексклюзивний любовний сценарій</b>\n"
                f"<i>Аркани: {base_info['name']} & {soul_info['name']}</i>\n\n"
                "━━━━━━━━━━━━━━━━━━━\n\n"
            )
            back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")]])
            await loading.edit_text(text=f"{header}{deep_text}\n\n━━━━━━━━━━━━━━━━━━━", reply_markup=back_kb, parse_mode="HTML")
        else:
            await message.answer(
                "✨ <b>Доступ відкрито!</b>\n\nТепер перейди в розділ «✦ Мій Аркан» та вкажи свою дату народження.",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
