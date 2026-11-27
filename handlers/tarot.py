import re
import asyncio
import logging
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from database.repository import UserRepository
from services.tarot_deck import deck
from services.llm import llm_service
from middlewares.throttling import UserLockManager
from keyboards.menu import get_cancel_keyboard, get_main_menu_keyboard
from keyboards.tarot_kb import (
    get_interactive_card_grid,
    get_tarot_paywall_keyboard,
    get_after_tarot_keyboard
)

logger = logging.getLogger("handlers.tarot")
router = Router(name="tarot_router")


class TarotStates(StatesGroup):
    waiting_situation = State()
    selecting_cards = State()


@router.callback_query(F.data == "btn_tarot")
async def start_tarot_flow(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    db_user = await UserRepository.get_user(user_id)

    if not db_user or db_user.total_tarot_credits <= 0:
        # Баланс 0 — показуємо пейвол
        await UserRepository.record_event(user_id, "paywall_tarot_shown")
        paywall_text = (
            "🌙 <b>Твій вільний розклад уже використано</b>\n\n"
            "Щоб отримати новий глибокий аналіз ситуації, обери зручний варіант:\n\n"
            "✦ <b>Підтримати Telegram Stars</b> (миттєве нарахування)\n"
            "✦ <b>Запросити подругу</b> (+1 повний розклад безкоштовно)"
        )
        if callback.message:
            await callback.message.edit_text(
                text=paywall_text,
                reply_markup=get_tarot_paywall_keyboard(),
                parse_mode="HTML"
            )
        await callback.answer()
        return

    # Баланс є — просимо описати питання
    await state.set_state(TarotStates.waiting_situation)
    prompt_text = (
        "🌙 <b>Розклад Таро на стосунки</b>\n\n"
        "Опиши коротко свою ситуацію або питання (від 5 до 500 символів).\n\n"
        "<i>Наприклад: «Він раптово став холодним і мовчить три дні після теплої зустрічі. Що відбувається?»</i>"
    )

    if callback.message:
        await callback.message.edit_text(
            text=prompt_text,
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
    await callback.answer()


@router.message(TarotStates.waiting_situation)
async def process_situation(message: Message, state: FSMContext):
    text = (message.text or "").strip()

    if text.startswith("/"):
        await message.answer("Будь ласка, напиши своє питання звичайним текстом або натисни «Скасувати».")
        return

    # Захист від занадто короткого або гігантського спам-промпту
    if len(text) < 5:
        await message.answer("Спробуй описати ситуацію трохи детальніше (хоча б від 5 символів).")
        return

    if len(text) > 500:
        await message.answer("Питання занадто довге. Спробуй сформулювати суть ситуації коротше (до 500 символів).")
        return

    await state.update_data(situation=text, selected_cards=[])
    await state.set_state(TarotStates.selecting_cards)

    grid_text = (
        "✦ <b>Зосередься на питанні</b>\n\n"
        "Перед тобою 6 закритих карт із колоди. "
        "Інтуїтивно обери <b>3 карти</b>, які найбільше відгукуються:"
    )

    await message.answer(
        text=grid_text,
        reply_markup=get_interactive_card_grid([]),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("card_pick:"))
async def process_card_pick(callback: CallbackQuery, state: FSMContext, bot: Bot):
    parts = callback.data.split(":")
    if len(parts) >= 3 and parts[1] == "ignore":
        await callback.answer("Ця карта вже обрана. Вибери іншу.", show_alert=False)
        return

    idx = int(parts[1])
    data = await state.get_data()
    selected = list(data.get("selected_cards", []))

    if idx in selected:
        await callback.answer()
        return

    selected.append(idx)
    await state.update_data(selected_cards=selected)

    if len(selected) < 3:
        if callback.message:
            await callback.message.edit_reply_markup(
                reply_markup=get_interactive_card_grid(selected)
            )
        await callback.answer(f"✓ Обрано {len(selected)} з 3")
        return

    # Обрано всі 3 карти — запускаємо ритуал
    user_id = callback.from_user.id
    situation = data.get("situation", "Аналіз стосунків")

    if not UserLockManager.acquire(user_id):
        await callback.answer("Зачекай секунду, розклад уже створюється...", show_alert=True)
        return

    await callback.answer("✓ Всі 3 карти обрано! Зчитую розклад...")

    msg = callback.message
    try:
        if msg:
            await msg.edit_text("<i>Тасую колоду та налаштовуюся на твою ситуацію...</i>", parse_mode="HTML")
            await asyncio.sleep(1.2)
            await msg.edit_text("<i>Зчитую поєднання карт та приховані мотиви...</i>", parse_mode="HTML")

        await bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)

        # Тягнемо 3 карти
        drawn_cards = deck.draw_spread(count=3, allow_reversed=True)
        c1, c2, c3 = drawn_cards[0], drawn_cards[1], drawn_cards[2]

        # Викликаємо LLM
        reading = await llm_service.generate_tarot_reading(situation, drawn_cards)

        # Списуємо кредит ТІЛЬКИ після успішної генерації
        await UserRepository.deduct_tarot_credit(user_id)
        await UserRepository.record_event(user_id, "tarot_completed", f"{c1.id},{c2.id},{c3.id}")

        result_header = (
            "🌙 <b>Твій розклад Таро</b>\n\n"
            "✦ <b>Випали карти:</b>\n"
            f"1. <b>{c1.display_name}</b> — <i>{c1.position_title}</i>\n"
            f"2. <b>{c2.display_name}</b> — <i>{c2.position_title}</i>\n"
            f"3. <b>{c3.display_name}</b> — <i>{c3.position_title}</i>\n\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
        )
        final_text = f"{result_header}{reading}\n\n━━━━━━━━━━━━━━━━━━━"

        try:
            if msg:
                await msg.edit_text(
                    text=final_text,
                    reply_markup=get_after_tarot_keyboard(),
                    parse_mode="HTML"
                )
            else:
                await bot.send_message(
                    chat_id=user_id,
                    text=final_text,
                    reply_markup=get_after_tarot_keyboard(),
                    parse_mode="HTML"
                )
        except TelegramBadRequest as te:
            logger.warning(f"TelegramBadRequest під час відправки Таро: {te}. Фоллбек на простий текст.")
            plain_text = re.sub(r"<[^>]+>", "", final_text)
            if msg:
                await msg.edit_text(text=plain_text, reply_markup=get_after_tarot_keyboard(), parse_mode=None)
            else:
                await bot.send_message(chat_id=user_id, text=plain_text, reply_markup=get_after_tarot_keyboard(), parse_mode=None)

        await state.clear()
    except Exception as e:
        logger.error(f"Помилка створення розкладу Таро: {e}", exc_info=True)
        if msg:
            await msg.answer(
                "<i>Вибач, зв'язок тимчасово перервався. Твій кредит збережено. Спробуй ще раз через хвилину.</i>",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
        await state.clear()
    finally:
        UserLockManager.release(user_id)
