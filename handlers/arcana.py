import re
import logging
from datetime import datetime
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from database.repository import UserRepository
from services.arcana_math import (
    calculate_base_arcana,
    calculate_soul_arcana,
    get_arcana_info
)
from services.llm import llm_service, LLMServiceError
from services.image_renderer import render_personal_arcana
from middlewares.throttling import UserLockManager
from keyboards.menu import get_cancel_keyboard, get_main_menu_keyboard
from keyboards.payment_kb import get_arcana_upsell_keyboard
from config import settings

logger = logging.getLogger("handlers.arcana")
router = Router(name="arcana_router")


class ArcanaStates(StatesGroup):
    waiting_birth_date = State()


@router.callback_query(F.data == "btn_my_arcana")
async def start_my_arcana(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    user_id = callback.from_user.id
    db_user = await UserRepository.get_user(user_id)

    # Якщо дата вже є в базі — одразу розраховуємо (або віддаємо з кэшу)
    if db_user and db_user.birth_date:
        await generate_and_show_arcana(callback.message, user_id, db_user.birth_date, bot)
        await callback.answer()
        return

    # Якщо дати немає — просимо ввести
    await state.set_state(ArcanaStates.waiting_birth_date)
    text = (
        "✦ <b>Розрахунок твого Аркана долі</b>\n\n"
        "Введи свою дату народження у форматі ДД.ММ.РРРР (наприклад: <code>14.08.1998</code>):"
    )
    if callback.message:
        await callback.message.edit_text(
            text=text,
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
    await callback.answer()


@router.message(ArcanaStates.waiting_birth_date, ~F.text)
async def process_birth_date_non_text(message: Message):
    """Обробка нетекстового вводу дати."""
    await message.answer("Напиши, будь ласка, текстом — так я зможу точно розібрати твій запит ✦")


@router.message(ArcanaStates.waiting_birth_date, F.text)
async def process_birth_date(message: Message, state: FSMContext, bot: Bot):
    text = (message.text or "").strip()
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if not match:
        await message.answer("Будь ласка, введи дату у форматі ДД.ММ.РРРР (наприклад: <code>14.08.1998</code>).", parse_mode="HTML")
        return

    date_str = match.group(0)
    try:
        parsed = datetime.strptime(date_str, "%d.%m.%Y")
        if not (1930 <= parsed.year <= 2024):
            raise ValueError()
    except Exception:
        await message.answer("Вкажи реальну дату народження (наприклад: <code>14.08.1998</code>).", parse_mode="HTML")
        return

    user_id = message.from_user.id
    await UserRepository.update_birth_date(user_id, date_str)
    await state.clear()

    await generate_and_show_arcana(message, user_id, date_str, bot)


async def generate_and_show_arcana(message_obj: Message, user_id: int, birth_date: str, bot: Bot):
    parsed = datetime.strptime(birth_date, "%d.%m.%Y")
    day, month, year = parsed.day, parsed.month, parsed.year

    base_num = calculate_base_arcana(day)
    soul_num = calculate_soul_arcana(day, month, year)

    base_info = get_arcana_info(base_num)
    soul_info = get_arcana_info(soul_num)

    if not UserLockManager.acquire(user_id):
        await message_obj.answer("Зачекай секунду, розрахунок уже триває...")
        return

    # Перевірка наявності в кэші
    cached = await UserRepository.get_arcana_cache(user_id, birth_date)
    if cached and cached.get("base_portrait"):
        portrait = cached["base_portrait"]
        is_cached = True
    else:
        is_cached = False

    loading = None
    if not is_cached:
        loading = await message_obj.answer("<i>Зчитую коди твого народження...</i>", parse_mode="HTML")
        await bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)

    try:
        if not is_cached:
            portrait = await llm_service.generate_arcana_portrait(
                birth_date=birth_date,
                base_arcana_name=f"{base_num}. {base_info['name']}",
                soul_arcana_name=f"{soul_num}. {soul_info['name']}",
                user_id=user_id
            )
            await UserRepository.save_arcana_portrait(user_id, birth_date, portrait)
            await UserRepository.record_event(user_id, "arcana_completed", f"{base_num}:{soul_num}")

        is_unlocked = await UserRepository.is_arcana_unlocked(user_id)

        header = (
            "✦ <b>Твій психологічний портрет за Арканами</b>\n\n"
            f"📅 Дата: <b>{birth_date}</b>\n"
            f"✦ Базовий Аркан (Особистість): <b>{base_num}. {base_info['name']}</b>\n"
            f"✦ Аркан душі (Почуття): <b>{soul_num}. {soul_info['name']}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
        )
        final_text = f"{header}{portrait}\n\n━━━━━━━━━━━━━━━━━━━"

        if is_unlocked:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📖 Читати мій любовний сценарій", callback_data="show_unlocked_love_scenario")],
                    [InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")]
                ]
            )
        else:
            kb = get_arcana_upsell_keyboard()

        # Динамічна візуалізація через Pillow
        photo_sent = False
        if not settings.DISABLE_IMAGES:
            try:
                db_u = await UserRepository.get_user(user_id)
                user_name = (db_u.username if db_u and db_u.username else None) or (message_obj.from_user.first_name if message_obj.from_user else "Ти")
                photo_bytes = render_personal_arcana(
                    name=user_name,
                    birth_date=birth_date,
                    arc_num=base_num,
                    arc_name=base_info["name"],
                    arc_type="Аркан особистості"
                )
                photo_file = BufferedInputFile(photo_bytes, filename="personal_arcana.jpg")
                caption = f"✦ Твій Аркан долі: {base_num}. {base_info['name']}"
                if loading:
                    try:
                        await loading.delete()
                    except Exception:
                        pass
                await message_obj.answer_photo(photo_file, caption=caption)
                photo_sent = True
            except Exception as ie:
                logger.error(f"Помилка генерації або відправки зображення Аркана: {ie}", exc_info=True)

        target_msg = loading if (loading and not photo_sent) else message_obj
        try:
            if loading and not photo_sent:
                await target_msg.edit_text(text=final_text, reply_markup=kb, parse_mode="HTML")
            else:
                await target_msg.answer(text=final_text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest as te:
            logger.warning(f"TelegramBadRequest у показі Аркана: {te}. Відправка простим текстом.")
            plain_text = re.sub(r"<[^>]+>", "", final_text)
            if loading and not photo_sent:
                await target_msg.edit_text(text=plain_text, reply_markup=kb, parse_mode=None)
            else:
                await target_msg.answer(text=plain_text, reply_markup=kb, parse_mode=None)

    except Exception as e:
        logger.error(f"Помилка генерації Аркана: {e}", exc_info=True)
        fail_text = "<i>Зараз високе навантаження, не вдалося розрахувати Аркан. Спробуй ще раз за хвилину.</i>"
        if loading:
            await loading.edit_text(fail_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
        else:
            await message_obj.answer(fail_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
    finally:
        UserLockManager.release(user_id)


@router.callback_query(F.data == "show_unlocked_love_scenario")
async def show_unlocked_love_scenario(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    db_user = await UserRepository.get_user(user_id)
    if not db_user or not db_user.birth_date:
        await callback.answer("Спочатку вкажи дату народження у розділі «✦ Мій Аркан».", show_alert=True)
        return

    parsed = datetime.strptime(db_user.birth_date, "%d.%m.%Y")
    base_num = calculate_base_arcana(parsed.day)
    soul_num = calculate_soul_arcana(parsed.day, parsed.month, parsed.year)
    base_info = get_arcana_info(base_num)
    soul_info = get_arcana_info(soul_num)

    # Перевірка наявності в кэші
    cached = await UserRepository.get_arcana_cache(user_id, db_user.birth_date)
    if cached and cached.get("love_scenario"):
        deep_text = cached["love_scenario"]
        is_cached = True
    else:
        is_cached = False

    loading = None
    if not is_cached:
        loading = await callback.message.answer("<i>Відкриваю твій розбір любовного сценарію...</i>", parse_mode="HTML")
        await bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)

    try:
        if not is_cached:
            deep_text = await llm_service.generate_arcana_deep_love(
                birth_date=db_user.birth_date,
                base_arcana_name=f"{base_num}. {base_info['name']}",
                soul_arcana_name=f"{soul_num}. {soul_info['name']}",
                user_id=user_id
            )
            await UserRepository.save_arcana_love(user_id, db_user.birth_date, deep_text)

        header = (
            "🔒 <b>Твій ексклюзивний любовний сценарій</b>\n"
            f"<i>Аркани: {base_info['name']} & {soul_info['name']}</i>\n\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
        )
        back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")]])
        full_text = f"{header}{deep_text}\n\n━━━━━━━━━━━━━━━━━━━"

        target_msg = loading if loading else callback.message
        try:
            if loading:
                await target_msg.edit_text(text=full_text, reply_markup=back_kb, parse_mode="HTML")
            else:
                await target_msg.answer(text=full_text, reply_markup=back_kb, parse_mode="HTML")
        except TelegramBadRequest as te:
            logger.warning(f"TelegramBadRequest у любовному сценарії: {te}. Відправка простим текстом.")
            plain_text = re.sub(r"<[^>]+>", "", full_text)
            if loading:
                await target_msg.edit_text(text=plain_text, reply_markup=back_kb, parse_mode=None)
            else:
                await target_msg.answer(text=plain_text, reply_markup=back_kb, parse_mode=None)

    except Exception as e:
        logger.error(f"Помилка відкриття любовного сценарію: {e}", exc_info=True)
        fail_text = "<i>Зараз високе навантаження, не вдалося зчитати сценарій. Спробуй ще раз за хвилину.</i>"
        if loading:
            await loading.edit_text(fail_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
        else:
            await callback.message.answer(fail_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")

    await callback.answer()
