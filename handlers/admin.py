import io
import csv
import html
import asyncio
import logging
from aiogram import Router, Bot, F
from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from config import settings
from database.repository import UserRepository

logger = logging.getLogger("handlers.admin")


class AdminFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        if not settings.ADMIN_IDS:
            return False
        admin_list = settings.ADMIN_IDS if isinstance(settings.ADMIN_IDS, list) else [settings.ADMIN_IDS]
        return message.from_user.id in admin_list


router = Router(name="admin_router")
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


class BroadcastStates(StatesGroup):
    waiting_segment = State()
    waiting_content = State()
    confirm_send = State()


@router.message(Command("admin"))
async def handle_admin_dashboard(message: Message):
    """
    Компактна та точна аналітика: воронка, конверсії, юніт-економіка LLM.
    """
    metrics = await UserRepository.get_admin_metrics()
    utm_data = await UserRepository.get_utm_funnel()
    llm_stats = await UserRepository.get_llm_usage_stats()

    total = metrics["total_users"]
    tarot_done = metrics["tarot_done_users"]
    paywall = metrics["paywall_users"]
    clicked_pay = metrics["clicked_pay_users"]
    payments = metrics["payments_count"]
    stars = metrics["total_stars"]

    # Конверсії
    cr_tarot = round(tarot_done / total * 100, 1) if total > 0 else 0
    cr_pay = round(payments / total * 100, 1) if total > 0 else 0

    t24 = llm_stats["tokens_24h"]
    t_all = llm_stats["tokens_all"]

    header_block = (
        "📊 <b>АНАЛІТИКА VELARA BOT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Всього користувачів: <b>{total}</b>\n"
        f"⚡ Нових за сьогодні: <b>{metrics['new_today']}</b>\n"
        f"🕒 Активних за 24г: <b>{metrics['active_24h']}</b>\n\n"
        f"🌙 Пройшли 1-й розклад: <b>{tarot_done}</b> ({cr_tarot}% від старту)\n"
        f"🚧 Побачили пейвол: <b>{paywall}</b>\n"
        f"🎯 Натиснули «Оплатити»: <b>{clicked_pay}</b>\n"
        f"⭐ Оплат Stars: <b>{payments}</b> (Всього: <b>{stars} ⭐</b> | CR: <b>{cr_pay}%</b>)\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 <b>ВИТРАТИ ТОКЕНІВ LLM:</b>\n"
        f"• <b>24 години:</b> In: {t24['prompt']:,} | Out: {t24['completion']:,} | Разом: {t24['total']:,} ({t24['requests']} зап.)\n"
        f"• <b>За весь час:</b> In: {t_all['prompt']:,} | Out: {t_all['completion']:,} | Разом: {t_all['total']:,} ({t_all['requests']} зап.)\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📈 <b>ВОРОНКА ЗА ДЖЕРЕЛАМИ (UTM):</b>\n\n"
    )

    utm_lines = []
    for item in utm_data:
        src = item["utm_source"]
        starts = item["total_starts"]
        t_done = item["tarot_completed"]
        c_pay = item["clicked_pay"]
        p_cnt = item["payments_count"]
        p_stars = item["total_stars"]

        cr = round(p_cnt / starts * 100, 1) if starts > 0 else 0
        utm_lines.append(
            f"• <code>{html.escape(src)}</code>:\n"
            f"   Старт: <b>{starts}</b> ➔ Розклад: <b>{t_done}</b> ➔ Клік на оплату: <b>{c_pay}</b> ➔ Оплат: <b>{p_cnt}</b> ({p_stars} ⭐) [CR: <b>{cr}%</b>]"
        )

    if not utm_lines:
        utm_text = "<i>Даних щодо джерел ще немає</i>"
    else:
        utm_text = "\n\n".join(utm_lines)

    footer = (
        "\n━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Команди адміна:</i>\n"
        "• <code>/broadcast</code> — безпечна сегментована розсилка\n"
        "• <code>/export</code> — вивантаження бази лідів у CSV\n"
        "• <code>/refund &lt;user_id&gt; &lt;charge_id&gt;</code> — повернення платежу Stars"
    )
    await message.answer(f"{header_block}{utm_text}{footer}", parse_mode="HTML")


@router.message(Command("export"))
async def handle_export_users(message: Message):
    """Вивантаження списку лідів у CSV (сумісне з SQLite та PostgreSQL)."""
    rows = await UserRepository.get_all_users()

    if not rows:
        await message.answer("У базі поки немає користувачів.")
        return

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for r in rows:
        writer.writerow(dict(r))

    csv_bytes = output.getvalue().encode("utf-8-sig")
    doc = BufferedInputFile(csv_bytes, filename="velara_leads.csv")
    await message.answer_document(
        document=doc,
        caption=f"📁 Експорт бази користувачів ({len(rows)} записів)"
    )


@router.message(Command("refund"))
async def handle_refund(message: Message, bot: Bot):
    """
    Повернення платежу Telegram Stars:
    /refund <user_id> <telegram_payment_charge_id>
    """
    parts = message.text.strip().split()
    if len(parts) < 3:
        await message.answer(
            "⚠️ <b>Формат команди:</b>\n"
            "<code>/refund &lt;user_id&gt; &lt;telegram_payment_charge_id&gt;</code>\n\n"
            "<i>Знайти charge_id можна у вивантаженні /export або у списку платежів.</i>",
            parse_mode="HTML"
        )
        return

    try:
        target_user_id = int(parts[1])
        charge_id = parts[2].strip()
    except ValueError:
        await message.answer("❌ Помилка: user_id має бути цілим числом.")
        return

    try:
        res = await bot.refund_star_payment(
            user_id=target_user_id,
            telegram_payment_charge_id=charge_id
        )
        if res:
            await UserRepository.record_event(
                target_user_id,
                "payment_refunded",
                f"charge_id:{charge_id}"
            )
            await message.answer(
                f"✅ <b>Платіж успішно повернуто!</b>\n\n"
                f"• User ID: <code>{target_user_id}</code>\n"
                f"• Charge ID: <code>{charge_id}</code>\n"
                "Зірки (Stars) повернено на баланс користувача.",
                parse_mode="HTML"
            )
        else:
            await message.answer("❌ Telegram повернув статус False при спробі повернення платежу.")
    except Exception as e:
        logger.error(f"Помилка повернення платежу Stars: {e}", exc_info=True)
        await message.answer(
            f"❌ <b>Помилка під час повернення:</b>\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )


# --- 5. Адмін-розсилка (/broadcast) ---
SEGMENT_TITLES = {
    "all": "Усі активні (не заблокували)",
    "no_payments": "Користувачі без оплат",
    "paid": "Користувачі, які платили Stars"
}


@router.message(Command("broadcast"))
async def handle_broadcast_start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Усі активні", callback_data="bcast_seg:all")],
            [InlineKeyboardButton(text="⏳ Без оплат", callback_data="bcast_seg:no_payments")],
            [InlineKeyboardButton(text="⭐ Ті, хто платив", callback_data="bcast_seg:paid")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="bcast_cancel")]
        ]
    )
    await message.answer(
        "📢 <b>Створення розсилки</b>\n\nОбери сегмент аудиторії для відправки:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_segment)


@router.callback_query(F.data == "bcast_cancel")
async def handle_broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Розсилку скасовано.")
    await callback.answer()


@router.callback_query(BroadcastStates.waiting_segment, F.data.startswith("bcast_seg:"))
async def handle_broadcast_segment_chosen(callback: CallbackQuery, state: FSMContext):
    segment = callback.data.split(":", 1)[1]
    title = SEGMENT_TITLES.get(segment, segment)
    await state.update_data(segment=segment, segment_title=title)
    await state.set_state(BroadcastStates.waiting_content)

    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Скасувати", callback_data="bcast_cancel")]]
    )
    await callback.message.edit_text(
        f"✓ Обрано сегмент: <b>{title}</b>\n\n"
        "Тепер надішли повідомлення для розсилки (текст або фото з підписом).\n"
        "<i>Підтримується HTML-розмітка (&lt;b&gt;, &lt;i&gt;, посилання).</i>",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_content)
async def handle_broadcast_content_received(message: Message, state: FSMContext):
    photo_id = None
    caption = None
    text = None

    if message.photo:
        photo_id = message.photo[-1].file_id
        caption = message.caption or ""
    elif message.text:
        text = message.text
    else:
        await message.answer("Будь ласка, надішли текст або фото з підписом.")
        return

    data = await state.get_data()
    segment = data.get("segment", "all")
    segment_title = data.get("segment_title", segment)

    recipients = await UserRepository.get_broadcast_recipients(segment)
    await state.update_data(photo_id=photo_id, caption=caption, text=text, recipients_count=len(recipients))
    await state.set_state(BroadcastStates.confirm_send)

    # Показуємо передперегляд
    await message.answer("👁 <b>ПОПЕРЕДНІЙ ПЕРЕГЛЯД ПОВІДОМЛЕННЯ:</b>", parse_mode="HTML")
    if photo_id:
        await message.answer_photo(photo=photo_id, caption=caption, parse_mode="HTML")
    else:
        await message.answer(text=text, parse_mode="HTML")

    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Надіслати", callback_data="bcast_confirm"),
                InlineKeyboardButton(text="❌ Скасувати", callback_data="bcast_cancel")
            ]
        ]
    )
    await message.answer(
        f"📊 <b>Параметри відправки:</b>\n"
        f"• Сегмент: <b>{segment_title}</b>\n"
        f"• Кількість одержувачів: <b>{len(recipients)}</b>\n\n"
        "Розпочати розсилку?",
        reply_markup=confirm_kb,
        parse_mode="HTML"
    )


@router.callback_query(BroadcastStates.confirm_send, F.data == "bcast_confirm")
async def handle_broadcast_execute(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    segment = data.get("segment", "all")
    photo_id = data.get("photo_id")
    caption = data.get("caption")
    text = data.get("text")

    recipients = await UserRepository.get_broadcast_recipients(segment)
    total = len(recipients)

    if total == 0:
        await callback.message.edit_text("❌ У цьому сегменті немає користувачів.")
        await state.clear()
        return

    status_msg = await callback.message.edit_text(
        f"⏳ <b>Розсилка розпочата...</b>\n\nВідправка {total} одержувачам (~20 повідомлень/сек). Зачекайте звіту.",
        parse_mode="HTML"
    )

    delivered = 0
    blocked = 0
    errors = 0

    for uid in recipients:
        try:
            if photo_id:
                await bot.send_photo(chat_id=uid, photo=photo_id, caption=caption, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            delivered += 1
            await asyncio.sleep(0.05)  # ~20 повідомлень на секунду
        except TelegramForbiddenError:
            blocked += 1
            await UserRepository.mark_user_blocked(uid)
        except Exception as e:
            errors += 1
            logger.warning(f"Помилка надсилання юзеру {uid}: {e}")

    report = (
        "✅ <b>Розсилку завершено!</b>\n\n"
        f"• Всього в сегменті: <b>{total}</b>\n"
        f"• Успішно доставлено: <b>{delivered}</b>\n"
        f"• Заблокували бота: <b>{blocked}</b> (позначено як is_blocked)\n"
        f"• Помилки: <b>{errors}</b>"
    )
    await status_msg.edit_text(report, parse_mode="HTML")
    await state.clear()
    await callback.answer()
