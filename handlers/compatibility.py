import re
from datetime import datetime
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ChatAction
from database.repository import UserRepository
from services.arcana_math import (
    calculate_base_arcana,
    calculate_compatibility_arcana,
    get_arcana_info
)
from services.llm import llm_service
from middlewares.throttling import UserLockManager
from keyboards.menu import get_cancel_keyboard, get_main_menu_keyboard
from config import settings

router = Router(name="compatibility_router")


class CompatStates(StatesGroup):
    waiting_user_data = State()
    waiting_partner_data = State()


def parse_name_and_date(text: str, default_name: str = "Ти") -> tuple[str, str, int, int, int]:
    """
    Витягує ім'я та дату ДД.ММ.РРРР із введеного тексту.
    Повертає (name, date_str, day, month, year) або викликає ValueError.
    """
    clean = text.strip()
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", clean)
    if not match:
        raise ValueError("Дата не знайдена у форматі ДД.ММ.РРРР")

    date_str = match.group(0)
    # Перевірка валідності реальної дати
    parsed = datetime.strptime(date_str, "%d.%m.%Y")
    if not (1930 <= parsed.year <= 2024):
        raise ValueError("Рік має бути в межах 1930–2024")

    # Ім'я — все, що було до або після дати
    name_candidate = clean.replace(date_str, "").strip(" ,-–")
    name = name_candidate if len(name_candidate) >= 2 else default_name
    return name[:30], date_str, parsed.day, parsed.month, parsed.year


@router.callback_query(F.data == "btn_compatibility")
async def start_compatibility(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    db_user = await UserRepository.get_user(user_id)

    # Якщо дата вже збережена в базі
    if db_user and db_user.birth_date:
        saved_date = db_user.birth_date
        u_name = callback.from_user.first_name or "Ти"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"✨ Використати мою дату ({saved_date})",
                        callback_data=f"compat_use_saved:{saved_date}"
                    )
                ],
                [
                    InlineKeyboardButton(text="Ввести іншу дату", callback_data="compat_enter_new")
                ],
                [
                    InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")
                ]
            ]
        )
        if callback.message:
            await callback.message.edit_text(
                text=f"✨ <b>Сумісність за Арканами долі</b>\n\nУ тебе збережена дата народження: <b>{saved_date}</b>. Використовуємо її?",
                reply_markup=kb,
                parse_mode="HTML"
            )
        await callback.answer()
        return

    # Запитуємо дані користувача
    await state.set_state(CompatStates.waiting_user_data)
    prompt_text = (
        "✨ <b>Сумісність за Арканами долі</b>\n\n"
        "Введи своє ім'я та дату народження через крапку.\n\n"
        "<i>Наприклад: <code>Оля 18.06.1999</code> або просто дату <code>18.06.1999</code></i>"
    )
    if callback.message:
        await callback.message.edit_text(
            text=prompt_text,
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("compat_use_saved:"))
async def handle_use_saved_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":", 1)[1]
    parsed = datetime.strptime(date_str, "%d.%m.%Y")
    u_name = callback.from_user.first_name or "Ти"

    await state.update_data(
        user_name=u_name,
        user_birth=date_str,
        user_day=parsed.day,
        user_month=parsed.month,
        user_year=parsed.year
    )
    await state.set_state(CompatStates.waiting_partner_data)

    prompt_partner = (
        f"✓ Твої дані: <b>{u_name} ({date_str})</b>\n\n"
        "Тепер введи <b>ім'я та дату народження партнера</b>:\n"
        "<i>Наприклад: <code>Максим 05.11.1996</code> або <code>05.11.1996</code></i>"
    )
    if callback.message:
        await callback.message.edit_text(
            text=prompt_partner,
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data == "compat_enter_new")
async def handle_enter_new_date(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CompatStates.waiting_user_data)
    prompt_text = (
        "Введи своє ім'я та дату народження (формат ДД.ММ.РРРР):\n"
        "<i>Наприклад: <code>Оля 18.06.1999</code></i>"
    )
    if callback.message:
        await callback.message.edit_text(
            text=prompt_text,
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
    await callback.answer()


@router.message(CompatStates.waiting_user_data)
async def process_user_data(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    def_name = message.from_user.first_name or "Ти"

    try:
        name, date_str, day, month, year = parse_name_and_date(text, def_name)
    except Exception:
        await message.answer("Будь ласка, вкажи коректну дату у форматі ДД.ММ.РРРР (наприклад: <code>15.08.1998</code>).", parse_mode="HTML")
        return

    # Зберігаємо дату користувача в БД, щоб наступного разу не питати
    await UserRepository.update_birth_date(message.from_user.id, date_str)

    await state.update_data(
        user_name=name,
        user_birth=date_str,
        user_day=day,
        user_month=month,
        user_year=year
    )
    await state.set_state(CompatStates.waiting_partner_data)

    await message.answer(
        f"✓ Твої дані збережено: <b>{name} ({date_str})</b>\n\n"
        "Тепер введи <b>ім'я та дату народження партнера</b>:\n"
        "<i>Наприклад: <code>Максим 05.11.1996</code></i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


@router.message(CompatStates.waiting_partner_data)
async def process_partner_data(message: Message, state: FSMContext, bot: Bot):
    text = (message.text or "").strip()
    try:
        p_name, p_date_str, p_day, p_month, p_year = parse_name_and_date(text, "Партнер")
    except Exception:
        await message.answer("Вкажи дату партнера у форматі ДД.ММ.РРРР (наприклад: <code>Максим 05.11.1996</code>).", parse_mode="HTML")
        return

    user_id = message.from_user.id

    # Перевіряємо денний ліміт
    allowed = await UserRepository.check_and_increment_compat_limit(user_id, settings.COMPATIBILITY_DAILY_LIMIT)
    if not allowed:
        await message.answer(
            "✦ <b>Денний ліміт сумісності вичерпано (3/3)</b>\n\n"
            "Щоб зберегти свіжість сприйняття, повертайся завтра або запроси подругу у розділі «👤 Профіль».",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
        await state.clear()
        return

    if not UserLockManager.acquire(user_id):
        await message.answer("Зачекай кілька секунд, попередня відповідь ще генерується...")
        return

    data = await state.get_data()
    u_name = data.get("user_name", "Ти")
    u_date_str = data.get("user_birth", "")
    u_day = data.get("user_day", 1)

    loading_msg = await message.answer("<i>Розраховую перетин ваших Арканів та лінію тяжіння...</i>", parse_mode="HTML")
    await bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)

    try:
        # Детермінована математика Арканів
        u_base_num = calculate_base_arcana(u_day)
        p_base_num = calculate_base_arcana(p_day)
        pair_num = calculate_compatibility_arcana(u_base_num, p_base_num)

        u_arcana = get_arcana_info(u_base_num)
        p_arcana = get_arcana_info(p_base_num)
        pair_arcana = get_arcana_info(pair_num)

        # Виклик LLM
        analysis = await llm_service.generate_compatibility(
            user_name=u_name,
            user_birth=u_date_str,
            user_arcana_name=f"{u_base_num}. {u_arcana['name']}",
            partner_name=p_name,
            partner_birth=p_date_str,
            partner_arcana_name=f"{p_base_num}. {p_arcana['name']}",
            pair_arcana_name=f"{pair_num}. {pair_arcana['name']}"
        )

        await UserRepository.record_event(user_id, "compat_completed", f"{u_base_num}+{p_base_num}={pair_num}")

        header = (
            f"✨ <b>Сумісність: {u_name} & {p_name}</b>\n\n"
            f"✦ Аркан {u_name}: <b>{u_base_num}. {u_arcana['name']}</b>\n"
            f"✦ Аркан {p_name}: <b>{p_base_num}. {p_arcana['name']}</b>\n"
            f"✦ Аркан союзу: <b>{pair_num}. {pair_arcana['name']}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
        )

        result_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✨ Перевірити іншу пару", callback_data="btn_compatibility")],
                [InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")]
            ]
        )

        await loading_msg.edit_text(
            text=f"{header}{analysis}",
            reply_markup=result_kb,
            parse_mode="HTML"
        )
        await state.clear()
    except Exception as e:
        await loading_msg.edit_text(
            "<i>Вибач, сталася технічна помилка. Спробуй ще раз за хвилину.</i>",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
        await state.clear()
    finally:
        UserLockManager.release(user_id)
