import re
import html
import logging
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from database.repository import UserRepository
from keyboards.menu import get_main_menu_keyboard, get_profile_keyboard

logger = logging.getLogger("handlers.start")
router = Router(name="start_router")


@router.message(CommandStart())
@router.message(Command("menu"))
async def handle_start(message: Message, bot: Bot, state: FSMContext, command: CommandObject = None):
    # Глобальний скид будь-якого стану FSM
    await state.clear()
    user = message.from_user

    # Розбираємо deep-link payload якщо є
    payload = ""
    if command and command.args:
        payload = command.args.strip()

    referrer_id = None
    utm_source = "direct"

    if payload.startswith("ref_"):
        raw_ref = payload.replace("ref_", "")
        if raw_ref.isdigit():
            referrer_id = int(raw_ref)
            utm_source = "referral"
    elif payload:
        utm_source = payload

    db_user, is_new = await UserRepository.get_or_create_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        utm_source=utm_source,
        referrer_id=referrer_id
    )

    # Якщо користувач новий і прийшов за рефералкою — сповіщаємо запросившого
    if is_new and db_user.referrer_id:
        try:
            await bot.send_message(
                chat_id=db_user.referrer_id,
                text=(
                    "✨ <b>Твоя подруга приєдналася до Velara!</b>\n\n"
                    "Тобі автоматично нараховано <b>+1 безкоштовний розклад Таро</b> 🌙 "
                    "та <b>+1 перевірку сумісності</b> ✨"
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    welcome_text = (
        "🕯 <b>Простір Velara</b>\n\n"
        "Тут немає фальшивих обіцянок чи магічних ілюзій. "
        "Тільки твереза психологія стосунків, точні Аркани та погляд у суть речей.\n\n"
        "✦ Тобі нараховано <b>1 безкоштовний розклад Таро</b> та <b>1 аналіз сумісності</b> для знайомства.\n\n"
        "Обери, з чого почнемо сьогодні:"
    )

    await message.answer(
        text=welcome_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "back_to_menu")
async def handle_back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    menu_text = (
        "🕯 <b>Простір Velara</b>\n\n"
        "Обери потрібний напрямок:"
    )
    if callback.message:
        try:
            await callback.message.edit_text(
                text=menu_text,
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
        except Exception:
            await callback.message.answer(
                text=menu_text,
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
    await callback.answer()


@router.callback_query(F.data == "btn_profile")
async def handle_profile(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    db_user = await UserRepository.get_user(user_id)
    if not db_user:
        await callback.answer("Помилка профілю, надішли /start", show_alert=True)
        return

    ref_info = await UserRepository.get_referral_info(user_id)
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"

    text = (
        "👤 <b>Твій особистий простір</b>\n\n"
        f"🌙 <b>Баланс Таро:</b> {db_user.total_tarot_credits} "
        f"(вільних: {db_user.free_tarot_credits}, придбаних: {db_user.paid_tarot_credits})\n"
        f"✨ <b>Баланс сумісності:</b> {db_user.total_compat_credits} "
        f"(вільних: {db_user.free_compat_credits}, придбаних: {db_user.paid_compat_credits})\n"
        f"👥 <b>Запрошено подруг:</b> {ref_info['invited_count']}\n\n"
        "✦ <b>Твоє посилання для запрошення:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        "<i>За кожну подругу, яка вперше приєднається за твоїм посиланням, "
        "ти отримуєш +1 розклад Таро та +1 перевірку сумісності безкоштовно.</i>"
    )

    if callback.message:
        await callback.message.edit_text(
            text=text,
            reply_markup=get_profile_keyboard(ref_link),
            parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data == "btn_history")
async def handle_history_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    readings = await UserRepository.get_readings_history(user_id, limit=5)

    if not readings:
        empty_text = (
            "📜 <b>Твоя історія розкладів</b>\n\n"
            "Тут зберігатимуться твої розклади Таро та перевірки сумісності, "
            "щоб ти завжди могла повернутися до них та перечитати інсайти.\n\n"
            "<i>У тебе поки немає збережених розкладів.</i>"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« До профілю", callback_data="btn_profile")]
            ]
        )
        if callback.message:
            await callback.message.edit_text(empty_text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        return

    hist_text = (
        "📜 <b>Твої останні розклади</b>\n\n"
        "Натисни на розклад, щоб переглянути його повний текст:"
    )
    kb_rows = []
    for r in readings:
        icon = "🌙" if r["reading_type"] == "tarot" else "✨"
        dt = r["created_at"][:10]  # РРРР-ММ-ДД
        clean_title = r["title"].replace("Розклад: ", "").replace("Сумісність: ", "")[:20]
        label = f"{icon} {clean_title}... ({dt})"
        kb_rows.append([
            InlineKeyboardButton(text=label, callback_data=f"read_hist:{r['id']}")
        ])
    kb_rows.append([InlineKeyboardButton(text="« До профілю", callback_data="btn_profile")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    if callback.message:
        await callback.message.edit_text(hist_text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("read_hist:"))
async def handle_show_history_item(callback: CallbackQuery):
    try:
        reading_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Помилка ідентифікатора", show_alert=True)
        return

    user_id = callback.from_user.id
    item = await UserRepository.get_reading_by_id(reading_id, user_id)
    if not item:
        await callback.answer("Запис не знайдено", show_alert=True)
        return

    content = item["content"]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« До списку розкладів", callback_data="btn_history")],
            [InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")]
        ]
    )

    if callback.message:
        try:
            await callback.message.edit_text(content, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest as te:
            logger.warning(f"HTML parse error in history: {te}. Sending plain text.")
            plain_text = re.sub(r"<[^>]+>", "", content)
            await callback.message.edit_text(plain_text, reply_markup=kb, parse_mode=None)

    await callback.answer()
