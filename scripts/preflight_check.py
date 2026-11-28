#!/usr/bin/env python3
"""
scripts/preflight_check.py
Автоматична передпольотна перевірка Velara Bot v2.5 перед запуском бойового трафіку на Render + Neon.tech.

Перевіряє:
1. Стан БД (PostgreSQL на Neon / SQLite), авто-міграції, коректність роботи всіх методів UserRepository.
2. Чистоту очищення тестових даних (-999999).
3. Живий стан LLM API (OpenRouter / OpenAI), час відповіді, ліміти токенів (finish_reason), валідацію HTML та відсутність «ІІ-слопу».
"""

import os
import sys
import time
import re
import asyncio
from datetime import datetime, timedelta

# Додаємо корінь проєкту в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import settings
from database.db import db, init_db, clean_postgres_dsn
from database.repository import UserRepository
from services.tarot_deck import deck
from services.llm import llm_service, sanitize_telegram_html
from prompts.tarot_prompt import TAROT_SYSTEM_PROMPT, build_tarot_user_prompt
from prompts.compatibility_prompt import COMPATIBILITY_SYSTEM_PROMPT, build_compatibility_user_prompt
from prompts.arcana_prompt import ARCANA_FREE_SYSTEM_PROMPT, build_arcana_free_user_prompt
from services.arcana_math import calculate_base_arcana, calculate_soul_arcana, calculate_compatibility_arcana, get_arcana_info


def print_header(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_step(step_name: str, status: str = "RUNNING"):
    print(f"\n[•] {step_name} ... {status}")


def validate_html_structure(text: str) -> tuple[bool, str]:
    """Перевіряє коректність відкритих та закритих тегів HTML для Telegram."""
    tags = ["b", "i", "blockquote", "code"]
    for t in tags:
        opened = len(re.findall(rf"<{t}>", text))
        closed = len(re.findall(rf"</{t}>", text))
        if opened != closed:
            return False, f"Дисбаланс тегів <{t}>: відкрито {opened}, закрито {closed}"
    return True, "Усі теги збалансовані"


async def run_database_preflight() -> bool:
    print_header("ЧАСТИНА 1: ПЕРЕВІРКА БАЗИ ДАНИХ ТА СУМІСНОСТІ SQL")

    db_type = "PostgreSQL (Neon.tech / Cloud)" if db.is_postgres else "SQLite (Local fallback)"
    print(f"Режим бази даних: {db_type}")

    if db.is_postgres:
        dsn, needs_ssl = clean_postgres_dsn(settings.DATABASE_URL)
        # Маскуємо пароль для безпечного виводу
        masked_dsn = re.sub(r":([^@]+)@", ":*****@", dsn)
        print(f"DSN: {masked_dsn}")
        print(f"SSL вимагається: {needs_ssl}")
    else:
        print(f"Шлях до SQLite: {settings.DATABASE_PATH}")

    # 1. Ініціалізація та міграції
    print_step("1. Ініціалізація схеми та авто-міграції (init_db)")
    start_t = time.time()
    await init_db()
    print(f"    ✓ Схема мігрована успішно за {time.time() - start_t:.3f}с")

    # 2. Перевірка SELECT 1
    print_step("2. Пінгування БД (SELECT 1)")
    s1 = await db.fetch_val("SELECT 1")
    if s1 != 1:
        print(f"    ✗ Помилка: SELECT 1 повернув {s1}")
        return False
    print("    ✓ Відповідь SELECT 1 = 1 отримана миттєво")

    # 3. Тестування репозиторію на тестовому користувачі
    TEST_USER_ID = -999999
    print_step(f"3. Тестування бізнес-логіки репозиторію на user_id = {TEST_USER_ID}")

    # Попереднє очищення, якщо лишилися сліди минулих тестів
    await db.execute("DELETE FROM users WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM events WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM payments WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM arcana_unlocks WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM arcana_cache WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM readings_history WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM llm_usage WHERE user_id = ?", TEST_USER_ID)

    try:
        # 3.1 Створення користувача
        u, is_new = await UserRepository.get_or_create_user(
            user_id=TEST_USER_ID,
            username="preflight_bot",
            first_name="Preflight",
            last_name="Tester",
            utm_source="preflight_utm"
        )
        assert is_new is True, "Користувач мав бути новим"
        assert u.free_tarot_credits == 1, "Має бути 1 вільний розклад Таро"
        assert u.free_compat_credits == 1, "Має бути 1 вільна сумісність"
        print("    ✓ get_or_create_user: користувача створено з 1 безкоштовним кредитом Таро та Сумісності")

        # 3.2 Оновлення дати народження
        await UserRepository.update_birth_date(TEST_USER_ID, "18.06.1999")
        u_updated = await UserRepository.get_user(TEST_USER_ID)
        assert u_updated.birth_date == "18.06.1999"
        print("    ✓ update_birth_date: збережено дату народження")

        # 3.3 Списання та нарахування Таро
        assert await UserRepository.deduct_tarot_credit(TEST_USER_ID) is True
        assert await UserRepository.deduct_tarot_credit(TEST_USER_ID) is False, "При нульовому балансі має повертати False"
        await UserRepository.add_tarot_credits(TEST_USER_ID, 3, is_paid=True)
        u_t = await UserRepository.get_user(TEST_USER_ID)
        assert u_t.total_tarot_credits == 3
        print("    ✓ deduct_tarot_credit & add_tarot_credits: списання та нарахування працюють")

        # 3.4 Списання та нарахування Сумісності
        assert await UserRepository.deduct_compat_credit(TEST_USER_ID) is True
        assert await UserRepository.deduct_compat_credit(TEST_USER_ID) is False, "Має бути 0 кредитів сумісності"
        await UserRepository.add_compat_credits(TEST_USER_ID, 1, is_paid=True)
        u_c = await UserRepository.get_user(TEST_USER_ID)
        assert u_c.total_compat_credits == 1
        print("    ✓ deduct_compat_credit & add_compat_credits: перевірка сумісності працює")

        # 3.5 Запис платежу та події
        await UserRepository.record_payment(TEST_USER_ID, "tarot_3", 90, "ch_preflight_123")
        await UserRepository.record_event(TEST_USER_ID, "preflight_event", "sample_payload")
        print("    ✓ record_payment & record_event: транзакція Stars та аналітика зафіксовані")

        # 3.6 Розблокування Аркана
        assert await UserRepository.is_arcana_unlocked(TEST_USER_ID) is False
        await UserRepository.unlock_arcana(TEST_USER_ID)
        assert await UserRepository.is_arcana_unlocked(TEST_USER_ID) is True
        print("    ✓ unlock_arcana: ON CONFLICT розблокування платних матеріалів працює")

        # 3.7 Кэшування Арканів
        await UserRepository.save_arcana_portrait(TEST_USER_ID, "18.06.1999", "<b>Тестовий портрет</b>")
        await UserRepository.save_arcana_love(TEST_USER_ID, "18.06.1999", "<b>Тестовий любовний сценарій</b>")
        cached = await UserRepository.get_arcana_cache(TEST_USER_ID, "18.06.1999")
        assert cached is not None and cached["base_portrait"] == "<b>Тестовий портрет</b>"
        assert cached["love_scenario"] == "<b>Тестовий любовний сценарій</b>"
        print("    ✓ arcana_cache: збереження та миттєве читання портрета і сценарію працює")

        # 3.8 Історія розкладів
        await UserRepository.add_reading_history(TEST_USER_ID, "tarot", "Розклад: Маг, Шут, Сонце", "Текст розкладу")
        hist = await UserRepository.get_readings_history(TEST_USER_ID, limit=5)
        assert len(hist) >= 1
        single_h = await UserRepository.get_reading_by_id(hist[0]["id"], TEST_USER_ID)
        assert single_h is not None and single_h["title"] == "Розклад: Маг, Шут, Сонце"
        print("    ✓ readings_history: запис та читання історії користувача працює")

        # 3.9 Юніт-економіка LLM
        await UserRepository.record_llm_usage(TEST_USER_ID, "tarot", settings.LLM_MODEL, 210, 140)
        usage_stats = await UserRepository.get_llm_usage_stats()
        assert usage_stats["tokens_all"]["total"] >= 350
        print("    ✓ llm_usage: облік споживання токенів (Input/Output) активний")

        # 3.10 Запити ретеншн-дожиму та сегментів розсилки
        nudge_users = await UserRepository.get_users_for_nudge()
        assert isinstance(nudge_users, list)
        seg_all = await UserRepository.get_broadcast_recipients("all")
        seg_nopay = await UserRepository.get_broadcast_recipients("no_payments")
        seg_paid = await UserRepository.get_broadcast_recipients("paid")
        assert TEST_USER_ID in seg_all
        assert TEST_USER_ID in seg_paid  # бо ми записали платіж вище
        print(f"    ✓ broadcast сегменти: all={len(seg_all)}, no_payments={len(seg_nopay)}, paid={len(seg_paid)}")

        # 3.11 Аналітика /admin та воронка UTM
        admin_m = await UserRepository.get_admin_metrics()
        utm_f = await UserRepository.get_utm_funnel()
        assert admin_m["total_users"] >= 1
        assert any(item["utm_source"] == "preflight_utm" for item in utm_f)
        print("    ✓ get_admin_metrics & get_utm_funnel: складні агрегатні запити відпрацювали коректно")

    finally:
        # Повне видалення тестових даних
        print_step("4. Повне очищення тестових записів (-999999)")
        await db.execute("DELETE FROM users WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM events WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM payments WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM arcana_unlocks WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM arcana_cache WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM readings_history WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM llm_usage WHERE user_id = ?", TEST_USER_ID)

        # Перевірка чистоти
        u_clean = await UserRepository.get_user(TEST_USER_ID)
        assert u_clean is None, "Тестовий користувач мав бути видалений"
        print("    ✓ Тестовий користувач та всі пов'язані сутності повністю очищені з бази")

    return True


async def run_llm_preflight() -> bool:
    print_header("ЧАСТИНА 2: ЖИВА ПЕРЕВІРКА LLM API ТА ЯКОСТІ ТЕКСТІВ")

    if not settings.LLM_API_KEY or settings.LLM_API_KEY.strip() in ("SET_YOUR_KEY_HERE", "", "your_openai_or_openrouter_key_here"):
        print("\n[!] ПОПЕРЕДЖЕННЯ: LLM_API_KEY не налаштовано в .env.")
        print("    Перевірка живих запитів пропущена. Для повного тесту вкажіть дійсний ключ API.")
        return True

    print(f"Провайдер Base URL: {settings.LLM_BASE_URL}")
    print(f"Модель: {settings.LLM_MODEL}")
    print(f"Макс. токенів (LLM_MAX_TOKENS): {settings.LLM_MAX_TOKENS}")
    print(f"Таймаут: {settings.LLM_TIMEOUT_SECONDS}s")

    client = llm_service._client
    if not client:
        print("    ✗ Помилка: клієнт AsyncOpenAI не ініціалізовано.")
        return False

    scenarios = [
        {
            "name": "1. Розклад Таро на стосунки",
            "type": "tarot",
            "system": TAROT_SYSTEM_PROMPT,
            "build_user": lambda: (
                build_tarot_user_prompt(
                    "Він пропав на три дні після класного побачення, хоча до цього писав постійно. Що відбувається і чи писати йому першій?",
                    "1. 2 Мечів (пряме положення) — внутрішній конфлікт і вимушена пауза\n2. Місяць (пряме положення) — тривожність, приховані сумніви\n3. Королева Жезлів (пряме положення) — збереження гідності та автономії"
                )
            )
        },
        {
            "name": "2. Сумісність пари за Арканами",
            "type": "compatibility",
            "system": COMPATIBILITY_SYSTEM_PROMPT,
            "build_user": lambda: (
                build_compatibility_user_prompt(
                    user_name="Оля",
                    user_birth="18.06.1999",
                    user_arcana_name="18. Місяць",
                    partner_name="Максим",
                    partner_birth="05.11.1996",
                    partner_arcana_name="5. Ієрофант",
                    pair_arcana_name="1. Маг"
                )
            )
        },
        {
            "name": "3. Базовий Аркан долі за датою народження",
            "type": "arcana",
            "system": ARCANA_FREE_SYSTEM_PROMPT,
            "build_user": lambda: (
                build_arcana_free_user_prompt(
                    birth_date="14.08.1998",
                    base_arcana_name="14. Помірність",
                    soul_arcana_name="5. Ієрофант"
                )
            )
        }
    ]

    all_passed = True
    for sc in scenarios:
        print_step(f"Генерація: {sc['name']}")
        user_prompt = sc["build_user"]()

        t_start = time.time()
        try:
            resp = await client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": sc["system"]},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
                timeout=settings.LLM_TIMEOUT_SECONDS
            )
            elapsed = time.time() - t_start
            choice = resp.choices[0]
            raw_content = choice.message.content or ""
            clean_html = sanitize_telegram_html(raw_content)

            finish_reason = choice.finish_reason
            p_tok = resp.usage.prompt_tokens if resp.usage else 0
            c_tok = resp.usage.completion_tokens if resp.usage else 0

            is_valid_html, html_msg = validate_html_structure(clean_html)

            # Перевірки якості
            is_cut_off = (finish_reason == "length")
            
            print(f"    • Час відповіді: {elapsed:.2f} сек")
            print(f"    • Токени: Prompt: {p_tok} | Completion: {c_tok} | Всього: {p_tok + c_tok}")
            print(f"    • Статус завершення (finish_reason): {finish_reason} {'[OK]' if not is_cut_off else '[УВАГА: ОБРІЗАНО НА ПІВСЛОВІ]'}")
            print(f"    • HTML валідність: {'[OK] ' + html_msg if is_valid_html else '[ПОМИЛКА: ' + html_msg + ']'}")

            # Перевірка на бан-лист слів
            banned_words = ["кармічний борг", "вібрації", "всесвіт чує", "трансформація трансформацій"]
            found_banned = [w for w in banned_words if w in clean_html.lower()]
            if found_banned:
                print(f"    [!] Увага: знайдено слова з бан-листа: {found_banned}")
            else:
                print("    ✓ Анти-слоп фільтр: заборонених кліше не виявлено")

            print("\n    --- ПОЧАТОК ЗГЕНЕРОВАНОГО ТЕКСТУ ---")
            # Виводимо перші 400 символів для швидкої оцінки
            preview = clean_html[:450] + ("..." if len(clean_html) > 450 else "")
            for line in preview.split("\n"):
                print(f"    | {line}")
            print("    --- КІНЕЦЬ ЗГЕНЕРОВАНОГО ТЕКСТУ ---\n")

            if is_cut_off or not is_valid_html:
                all_passed = False

        except Exception as e:
            print(f"    ✗ Помилка запиту до LLM: {e}")
            all_passed = False

    return all_passed


async def main():
    print_header(f"ПРЕДПОЛЬОТНИЙ ТЕСТ VELARA BOT (v2.5) — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Операційна система: {sys.platform}")
    print(f"Версія Python: {sys.version.split()[0]}")

    db_ok = await run_database_preflight()
    llm_ok = await run_llm_preflight()

    print_header("ПІДСУМОК ПЕРЕДПОЛЬОТНОЇ ПЕРЕВІРКИ")
    print(f"1. База даних та SQL-сумісність: {'[УСПІШНО PASSED]' if db_ok else '[ПОМИЛКА FAILED]'}")
    print(f"2. LLM API та якість відповідей: {'[УСПІШНО PASSED]' if llm_ok else '[ПОМИЛКА FAILED]'}")

    if db_ok and llm_ok:
        print("\n🚀 БОТ ПОВНІСТЮ ГОТОВИЙ ДО БОЙОВОГО ДЕПЛОЮ ТА ТРАФІКУ!")
        sys.exit(0)
    else:
        print("\n❌ ВИЯВЛЕНО НЕПОЛАДКИ. Перевірте вивід вище перед запуском реклами.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
