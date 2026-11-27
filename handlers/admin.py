import io
import csv
import html
import logging
from aiogram import Router, Bot
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command, Filter
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


@router.message(Command("admin"))
async def handle_admin_dashboard(message: Message):
    """
    Компактна та точна аналітика для тестування реклами та конверсій.
    """
    metrics = await UserRepository.get_admin_metrics()
    utm_data = await UserRepository.get_utm_funnel()

    total = metrics["total_users"]
    tarot_done = metrics["tarot_done_users"]
    paywall = metrics["paywall_users"]
    clicked_pay = metrics["clicked_pay_users"]
    payments = metrics["payments_count"]
    stars = metrics["total_stars"]

    # Конверсії
    cr_tarot = round(tarot_done / total * 100, 1) if total > 0 else 0
    cr_pay = round(payments / total * 100, 1) if total > 0 else 0

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
        "• <code>/export</code> — вивантаження бази лідів у CSV\n"
        "• <code>/refund &lt;user_id&gt; &lt;charge_id&gt;</code> — повернення платежу Stars"
    )
    await message.answer(f"{header_block}{utm_text}{footer}", parse_mode="HTML")


@router.message(Command("export"))
async def handle_export_users(message: Message):
    """Вивантаження списку лідів у CSV (працює однаково для SQLite та PostgreSQL)."""
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
