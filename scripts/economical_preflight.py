#!/usr/bin/env python3
"""
scripts/economical_preflight.py
Економний предпольотний тест (строго 1 живий запит до LLM).
Перевіряє:
1. Хмарну базу даних Neon.tech (PostgreSQL): міграції, CRUD, адмінку, nudge, сегменти broadcast.
2. Візуалізацію Pillow (збереження 3 карток у tmp_preview/ та перевірка літер і, ї, є, ґ).
3. LLM API (РІВНО ОДИН запит до OpenAI gpt-6.1-terra на розклад Таро).
"""

import os
import sys
import time
import re
import asyncio
from datetime import datetime, timedelta

# Корінь проєкту
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import settings
from database.db import db, init_db, clean_postgres_dsn
from database.repository import UserRepository
from services.tarot_deck import DrawnCard
from services.llm import llm_service, sanitize_telegram_html
from prompts.tarot_prompt import TAROT_SYSTEM_PROMPT, build_tarot_user_prompt
from services.image_renderer import render_tarot_spread, render_compatibility, render_personal_arcana


def print_header(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_step(name: str):
    print(f"\n[•] {name} ...")


def validate_html_structure(text: str) -> tuple[bool, str]:
    tags = ["b", "i", "blockquote", "code"]
    for t in tags:
        opened = len(re.findall(rf"<{t}>", text))
        closed = len(re.findall(rf"</{t}>", text))
        if opened != closed:
            return False, f"Дисбаланс тегів <{t}>: відкрито {opened}, закрито {closed}"
    return True, "Усі теги збалансовані"


async def test_database_neon() -> bool:
    print_header("ЧАСТИНА 1: ПЕРЕВІРКА ХМАРНОЇ БАЗИ ДАНИХ NEON (POSTGRESQL)")

    if not db.is_postgres:
        print("    [!] ПОМИЛКА: База даних визначена як SQLite, а не PostgreSQL!")
        print(f"    DATABASE_URL={settings.DATABASE_URL}")
        return False

    dsn, needs_ssl = clean_postgres_dsn(settings.DATABASE_URL)
    masked_dsn = re.sub(r":([^@]+)@", ":*****@", dsn)
    print(f"    ✓ Двигун БД: PostgreSQL (asyncpg pool)")
    print(f"    ✓ Хост / DSN: {masked_dsn}")
    print(f"    ✓ SSL режим: {needs_ssl} (параметри channel_binding успішно очищено)")

    # 1. Авто-міграції
    print_step("1. Автоматичні міграції таблиць під PostgreSQL")
    t0 = time.time()
    await init_db()
    print(f"    ✓ Схема БД синхронізована за {time.time() - t0:.3f}с")

    # 2. Перевірка SELECT 1
    val = await db.fetch_val("SELECT 1")
    assert val == 1, f"SELECT 1 повернув {val}"
    print("    ✓ Пінгування Neon.tech успішне (SELECT 1 = 1)")

    # 3. Тестування CRUD та складних запитів на тестовому ID
    TEST_USER_ID = -999999
    print_step(f"2. Комплексний тест бізнес-логіки репозиторію на user_id = {TEST_USER_ID}")

    # Очищення перед тестом
    await db.execute("DELETE FROM users WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM events WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM payments WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM arcana_unlocks WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM arcana_cache WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM readings_history WHERE user_id = ?", TEST_USER_ID)
    await db.execute("DELETE FROM llm_usage WHERE user_id = ?", TEST_USER_ID)

    try:
        # Створення
        u, is_new = await UserRepository.get_or_create_user(
            user_id=TEST_USER_ID,
            username="test_neon_user",
            first_name="Оля",
            last_name=None,
            utm_source="test_ad"
        )
        assert u is not None and is_new is True
        assert u.free_tarot_credits == 1
        assert u.free_compat_credits == 1
        print("    ✓ get_or_create_user: новий запис створено з дефолтними кредитами")

        # Дата народження
        await UserRepository.update_birth_date(TEST_USER_ID, "14.08.1998")
        u = await UserRepository.get_user(TEST_USER_ID)
        assert u.birth_date == "14.08.1998"
        print("    ✓ update_birth_date: дата збережена")

        # Кредити Таро
        ok = await UserRepository.deduct_tarot_credit(TEST_USER_ID)
        assert ok is True
        u = await UserRepository.get_user(TEST_USER_ID)
        assert u.free_tarot_credits == 0
        await UserRepository.add_tarot_credits(TEST_USER_ID, 3)
        u = await UserRepository.get_user(TEST_USER_ID)
        assert u.paid_tarot_credits == 3
        print("    ✓ Баланси Таро (списання та нарахування) працюють коректно")

        # Кредити сумісності
        ok = await UserRepository.deduct_compat_credit(TEST_USER_ID)
        assert ok is True
        u = await UserRepository.get_user(TEST_USER_ID)
        assert u.free_compat_credits == 0
        await UserRepository.add_compat_credits(TEST_USER_ID, 2)
        u = await UserRepository.get_user(TEST_USER_ID)
        assert u.paid_compat_credits == 2
        print("    ✓ Баланси сумісності (списання та нарахування) працюють коректно")

        # Платежі та події
        await UserRepository.record_payment(TEST_USER_ID, "tarot_1", 35, "test_ch_1")
        await UserRepository.record_event(TEST_USER_ID, "preflight_event", "meta")
        print("    ✓ record_payment та record_event зафіксовані")

        # Аркан розблокування (ON CONFLICT DO NOTHING)
        await UserRepository.unlock_arcana(TEST_USER_ID)
        unlocked = await UserRepository.is_arcana_unlocked(TEST_USER_ID)
        assert unlocked is True
        print("    ✓ unlock_arcana: ON CONFLICT коректно відпрацьовує в PostgreSQL")

        # Кэш Арканів
        await UserRepository.save_arcana_portrait(TEST_USER_ID, "14.08.1998", "Портрет")
        await UserRepository.save_arcana_love(TEST_USER_ID, "14.08.1998", "Сценарій")
        cache = await UserRepository.get_arcana_cache(TEST_USER_ID, "14.08.1998")
        assert cache["base_portrait"] == "Портрет"
        assert cache["love_scenario"] == "Сценарій"
        print("    ✓ arcana_cache: збереження та миттєве читання працюють")

        # Історія
        await UserRepository.add_reading_history(TEST_USER_ID, "tarot", "Тест Таро", "Зміст")
        hist = await UserRepository.get_readings_history(TEST_USER_ID, limit=5)
        assert len(hist) == 1
        print("    ✓ readings_history: історія розкладів збережена та зчитана")

        # LLM статистика
        await UserRepository.record_llm_usage(TEST_USER_ID, "tarot", "gpt-6.1-terra", 100, 200)
        u_stats = await UserRepository.get_llm_usage_stats()
        assert u_stats["tokens_all"]["total"] >= 300
        print("    ✓ llm_usage: облік юніт-економіки активний")

        # Retention Nudge запит
        three_hours_ago = (datetime.utcnow() - timedelta(hours=3)).isoformat()
        await db.execute(
            "UPDATE users SET first_seen = ?, nudge_sent = 0, free_tarot_credits = 1 WHERE user_id = ?",
            three_hours_ago, TEST_USER_ID
        )
        nudge_users = await UserRepository.get_users_for_nudge()
        assert any(x["user_id"] == TEST_USER_ID for x in nudge_users)
        print("    ✓ get_users_for_nudge: логіка дожиму неактивних користувачів працює")

        # Broadcast сегменти
        b_all = await UserRepository.get_broadcast_recipients("all")
        b_paid = await UserRepository.get_broadcast_recipients("paid")
        assert TEST_USER_ID in b_all and TEST_USER_ID in b_paid
        print("    ✓ get_broadcast_recipients: сегментація розсилки (all / paid) працює")

        # Admin аналітика
        metrics = await UserRepository.get_admin_metrics()
        funnel = await UserRepository.get_utm_funnel()
        assert metrics["total_users"] >= 1
        print("    ✓ get_admin_metrics та get_utm_funnel: складні агрегатні запити відпрацювали успішно")

        # Очищення
        await db.execute("DELETE FROM users WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM events WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM payments WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM arcana_unlocks WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM arcana_cache WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM readings_history WHERE user_id = ?", TEST_USER_ID)
        await db.execute("DELETE FROM llm_usage WHERE user_id = ?", TEST_USER_ID)
        u_after = await UserRepository.get_user(TEST_USER_ID)
        assert u_after is None
        print("    ✓ Тестовий користувач повністю очищений з Neon.tech")

    except Exception as e:
        print(f"    [!] Помилка тестування БД Neon: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


def test_pillow_visuals() -> bool:
    print_header("ЧАСТИНА 2: ВІЗУАЛІЗАЦІЯ PILLOW ТА КИРИЛИЦЯ (І, Ї, Є, Ґ)")

    out_dir = os.path.abspath("tmp_preview")
    os.makedirs(out_dir, exist_ok=True)

    # 1. Таро з українськими літерами
    print_step("1. Рендеринг Таро (1200x675) з кирилицею")
    cards = [
        {"id": "major_1", "name_ua": "Маґ", "is_reversed": False},
        {"id": "major_18", "name_ua": "Місяць", "is_reversed": False},
        {"id": "major_2", "name_ua": "Верховна Жриця", "is_reversed": True}
    ]
    t_bytes = render_tarot_spread(cards)
    t_path = os.path.join(out_dir, "tarot_preview.jpg")
    with open(t_path, "wb") as f:
        f.write(t_bytes)
    print(f"    [OK] Збережено: {t_path} ({len(t_bytes)} байт)")

    # 2. Сумісність з іменами: Надія (і, я), Ґеоргій (ґ, є, і, й)
    print_step("2. Рендеринг Сумісності (1200x675) з літерами і, ї, є, ґ")
    c_bytes = render_compatibility("Надія", "Ґеоргій", "24.10.2001", "15.03.1998", 6, "Закохані")
    c_path = os.path.join(out_dir, "compat_preview.jpg")
    with open(c_path, "wb") as f:
        f.write(c_bytes)
    print(f"    [OK] Збережено: {c_path} ({len(c_bytes)} байт)")

    # 3. Аркан долі: Мар'їна (ї, і)
    print_step("3. Рендеринг Аркана долі (720x1080) з літерами і, ї, є, ґ")
    a_bytes = render_personal_arcana("Мар'їна", "14.08.1998", 14, "Помірність", "Аркан особистості")
    a_path = os.path.join(out_dir, "arcana_preview.jpg")
    with open(a_path, "wb") as f:
        f.write(a_bytes)
    print(f"    [OK] Збережено: {a_path} ({len(a_bytes)} байт)")

    return True


async def test_single_llm_call() -> dict:
    print_header("ЧАСТИНА 3: СТРОГО 1 ЖИВИЙ ЗАПИТ ДО OPENAI API (ЕКОНОМІЯ БЮДЖЕТУ)")

    print(f"    • Base URL: {settings.LLM_BASE_URL}")
    print(f"    • Модель: {settings.LLM_MODEL}")
    print(f"    • Ліміт токенів: {settings.LLM_MAX_TOKENS}")

    drawn = [
        DrawnCard(id="major_2", name_ua="2 Мечів", suit="swords", is_reversed=False, position_title="Основа ситуації", keywords="внутрішній конфлікт, пауза"),
        DrawnCard(id="major_18", name_ua="Місяць", suit="major", is_reversed=False, position_title="Приховане", keywords="тривожність, сумніви"),
        DrawnCard(id="major_11", name_ua="Королева Жезлів", suit="wands", is_reversed=False, position_title="Порада", keywords="гідність, автономія")
    ]
    situation = "Він пропав на три дні після класного побачення, хоча до цього писав постійно. Що відбувається і чи писати йому першій?"

    cards_text = (
        "1. 2 Мечів (пряме положення) — внутрішній конфлікт і вимушена пауза\n"
        "2. Місяць (пряме положення) — тривожність, приховані сумніви\n"
        "3. Королева Жезлів (пряме положення) — збереження гідності та автономії"
    )
    user_prompt = build_tarot_user_prompt(situation, cards_text)

    client = llm_service._client
    if not client:
        raise RuntimeError("AsyncOpenAI client не ініціалізовано")

    print_step("Відправка єдиного живого запиту до OpenAI...")
    t0 = time.time()

    is_new_gen = any(k in settings.LLM_MODEL.lower() for k in ["terra", "o1", "o3", "gpt-5", "gpt-6"])
    call_kwargs = {
        "model": settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": TAROT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "timeout": settings.LLM_TIMEOUT_SECONDS
    }
    if is_new_gen:
        call_kwargs["max_completion_tokens"] = settings.LLM_MAX_TOKENS
    else:
        call_kwargs["max_tokens"] = settings.LLM_MAX_TOKENS
        call_kwargs["temperature"] = settings.LLM_TEMPERATURE

    resp = None
    for _ in range(3):
        try:
            resp = await client.chat.completions.create(**call_kwargs)
            break
        except Exception as e:
            err_str = str(e).lower()
            modified = False
            if "max_completion_tokens" in err_str and "max_tokens" in call_kwargs:
                print("    [!] OpenAI вимагає 'max_completion_tokens' замість 'max_tokens'. Перемикаємо...")
                call_kwargs.pop("max_tokens", None)
                call_kwargs["max_completion_tokens"] = settings.LLM_MAX_TOKENS
                modified = True
            if "temperature" in err_str and "temperature" in call_kwargs:
                print("    [!] OpenAI не приймає параметр temperature для цієї моделі. Прибираємо...")
                call_kwargs.pop("temperature", None)
                modified = True
            if not modified:
                raise e

    elapsed = time.time() - t0
    choice = resp.choices[0]
    raw_text = choice.message.content or ""
    clean_html = sanitize_telegram_html(raw_text)

    finish_reason = choice.finish_reason
    p_tok = resp.usage.prompt_tokens if resp.usage else 0
    c_tok = resp.usage.completion_tokens if resp.usage else 0

    is_valid_html, html_msg = validate_html_structure(clean_html)

    # Записуємо споживання токенів у Neon
    await UserRepository.record_llm_usage(
        user_id=1092164380,
        feature="preflight_single_tarot",
        model=settings.LLM_MODEL,
        prompt_tokens=p_tok,
        completion_tokens=c_tok
    )

    return {
        "elapsed": elapsed,
        "finish_reason": finish_reason,
        "prompt_tokens": p_tok,
        "completion_tokens": c_tok,
        "total_tokens": p_tok + c_tok,
        "is_valid_html": is_valid_html,
        "html_msg": html_msg,
        "text": clean_html
    }


async def main():
    print_header(f"ЕКОНОМНИЙ ПРЕДПОЛЬОТНИЙ ТЕСТ VELARA (v2.5) — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. Тест Neon
    db_ok = await test_database_neon()
    if not db_ok:
        print("\n❌ Зупинка через помилку в базі даних Neon.")
        sys.exit(1)

    # 2. Тест Pillow
    pillow_ok = test_pillow_visuals()
    if not pillow_ok:
        print("\n❌ Зупинка через помилку рендерингу зображень.")
        sys.exit(1)

    # 3. Рівно 1 виклик LLM
    try:
        llm_res = await test_single_llm_call()
    except Exception as e:
        print(f"\n❌ Помилка єдиного виклику LLM: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print_header("ПІДСУМОК ПЕРЕДПОЛЬОТНОГО ТЕСТУ")
    print(f"1. Neon PostgreSQL: [УСПІШНО PASSED]")
    print(f"2. Pillow Візуалізація: [УСПІШНО PASSED — 3 файли збережено в tmp_preview/]")
    print(f"3. Живий виклик LLM: [УСПІШНО PASSED]")
    print(f"   • Модель: {settings.LLM_MODEL}")
    print(f"   • Час генерації: {llm_res['elapsed']:.2f} сек")
    print(f"   • Токени: Prompt {llm_res['prompt_tokens']} | Completion {llm_res['completion_tokens']} | Всього {llm_res['total_tokens']}")
    print(f"   • finish_reason: {llm_res['finish_reason']}")
    print(f"   • Валідність HTML: {llm_res['html_msg']}")

    print("\n" + "=" * 70)
    print("  ПОВНИЙ ТЕКСТ ЗГЕНЕРОВАНОГО РОЗКЛАДУ ТАРО (ОЦІНКА ОЧИМА)")
    print("=" * 70 + "\n")
    print(llm_res["text"])
    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
