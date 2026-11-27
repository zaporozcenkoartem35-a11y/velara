import html
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from database.repository import UserRepository
from keyboards.menu import get_main_menu_keyboard, get_profile_keyboard

router = Router(name="start_router")


@router.message(CommandStart())
async def handle_start(message: Message, command: CommandObject, bot: Bot, state: FSMContext):
    await state.clear()
    user = message.from_user

    # Розбираємо deep-link payload
    payload = (command.args or "").strip()
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
async def handle_profile(callback: CallbackQuery, bot: Bot):
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
