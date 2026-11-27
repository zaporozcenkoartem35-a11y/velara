import re
import html
import logging
from typing import Optional, List
from openai import AsyncOpenAI
from config import settings
from prompts.tarot_prompt import TAROT_SYSTEM_PROMPT, build_tarot_user_prompt
from prompts.compatibility_prompt import COMPATIBILITY_SYSTEM_PROMPT, build_compatibility_user_prompt
from prompts.arcana_prompt import (
    ARCANA_FREE_SYSTEM_PROMPT,
    ARCANA_DEEP_LOVE_PROMPT,
    build_arcana_free_user_prompt,
    build_arcana_deep_user_prompt
)
from services.tarot_deck import DrawnCard

logger = logging.getLogger("services.llm")


def sanitize_telegram_html(text: str) -> str:
    """
    Санітайзер для HTML Telegram:
    - Конвертує Markdown **жирний** у <b>жирний</b>
    - Конвертує *курсив* у <i>курсив</i>
    - Захищає від незакритих або невалідних тегів
    """
    if not text:
        return ""

    # Прибираємо потрійні бектіки
    text = re.sub(r"```[a-zA-Z]*\n?", "", text)
    text = text.replace("```", "")

    # Замінюємо **жирний** на <b>жирний</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Замінюємо *курсив* на <i>курсив</i> (якщо це не частина списку)
    text = re.sub(r"(?<!\w)\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", text)

    # Прибираємо заборонені теги Telegram, залишаючи дозволені: b, i, u, s, code, pre, blockquote
    allowed_tags = ["b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "blockquote"]
    pattern = r"<(?!/?(" + "|".join(allowed_tags) + r")\b)[^>]*>"
    text = re.sub(pattern, "", text)

    # Нормалізуємо strong -> b, em -> i
    text = text.replace("<strong>", "<b>").replace("</strong>", "</b>")
    text = text.replace("<em>", "<i>").replace("</em>", "</i>")

    # Балансуємо незакриті теги для основних тегів
    for tag in ["b", "i", "blockquote", "code"]:
        open_count = len(re.findall(rf"<{tag}>", text))
        close_count = len(re.findall(rf"</{tag}>", text))
        if open_count > close_count:
            text += f"</{tag}>" * (open_count - close_count)

    return text.strip()


class LLMService:
    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None
        if settings.LLM_API_KEY and settings.LLM_API_KEY.strip() not in ("SET_YOUR_KEY_HERE", ""):
            self._client = AsyncOpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
                timeout=settings.LLM_TIMEOUT_SECONDS
            )

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    async def _call_llm(self, system_prompt: str, user_prompt: str, fallback_func) -> str:
        if not self.is_configured:
            logger.warning("LLM API_KEY не налаштовано в .env. Використовується якісний евристичний фоллбек.")
            return fallback_func()

        try:
            response = await self._client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
                timeout=settings.LLM_TIMEOUT_SECONDS
            )
            raw_text = response.choices[0].message.content or ""
            clean_text = sanitize_telegram_html(raw_text)
            if clean_text:
                return clean_text
            return fallback_func()
        except Exception as e:
            logger.error(f"Помилка виклику LLM API: {e}", exc_info=True)
            return fallback_func()

    # --- 1. Таро ---
    async def generate_tarot_reading(self, situation: str, cards: List[DrawnCard]) -> str:
        cards_str_list = []
        for i, c in enumerate(cards, start=1):
            pos = "перевернуте" if c.is_reversed else "пряме"
            cards_str_list.append(f"{i}. {c.name_ukr} ({pos} положення) — {c.meaning_upright if not c.is_reversed else c.meaning_reversed}")
        cards_str = "\n".join(cards_str_list)

        user_prompt = build_tarot_user_prompt(situation, cards_str)

        def fallback() -> str:
            c1, c2, c3 = cards[0], cards[1], cards[2]
            return (
                f"✦ <b>Аналіз твоєї ситуації:</b>\n\n"
                f"<b>{c1.name_ukr}</b> ({c1.position_title}) вказує на внутрішній стан та імпульс, з якого почалася динаміка. "
                f"{c1.meaning_upright if not c1.is_reversed else c1.meaning_reversed}.\n\n"
                f"<b>{c2.name_ukr}</b> ({c2.position_title}) висвітлює ключову напругу між вами. "
                f"{c2.meaning_upright if not c2.is_reversed else c2.meaning_reversed}.\n\n"
                f"<b>{c3.name_ukr}</b> ({c3.position_title}) спрямовує вектор у найближчу перспективу: "
                f"{c3.meaning_upright if not c3.is_reversed else c3.meaning_reversed}.\n\n"
                f"<blockquote>Порада: не намагайся форсувати відповідь партнера через тиск. Залиш простір для прояву і спостерігай за реальними діями, а не словами.</blockquote>"
            )

        return await self._call_llm(TAROT_SYSTEM_PROMPT, user_prompt, fallback)

    # --- 2. Сумісність ---
    async def generate_compatibility(
        self,
        user_name: str,
        user_birth: str,
        user_arcana_name: str,
        partner_name: str,
        partner_birth: str,
        partner_arcana_name: str,
        pair_arcana_name: str
    ) -> str:
        user_prompt = build_compatibility_user_prompt(
            user_name, user_birth, user_arcana_name,
            partner_name, partner_birth, partner_arcana_name,
            pair_arcana_name
        )

        def fallback() -> str:
            return (
                f"✦ <b>Динаміка пари {user_name} та {partner_name}:</b>\n\n"
                f"Твій Аркан ({user_arcana_name}) прагне глибини, ясності та внутрішньої опори, "
                f"тоді як Аркан партнера ({partner_arcana_name}) проявляє іншу швидкість сприйняття та реакцій.\n\n"
                f"Спільний Аркан союзу ({pair_arcana_name}) показує, що головний урок цих стосунків — "
                f"навчитися домовлятися на рівних, не намагаючись перевиховати іншого під власні очікування.\n\n"
                f"<blockquote>У цій парі сильне взаємне тяжіння, але воно потребує зрілості: тригери виникають там, де накопичуються невисловлені образи. Чесний спокійний діалог знімає напругу.</blockquote>"
            )

        return await self._call_llm(COMPATIBILITY_SYSTEM_PROMPT, user_prompt, fallback)

    # --- 3. Аркан долі (Безкоштовний портрет) ---
    async def generate_arcana_portrait(
        self,
        birth_date: str,
        base_arcana_name: str,
        soul_arcana_name: str
    ) -> str:
        user_prompt = build_arcana_free_user_prompt(birth_date, base_arcana_name, soul_arcana_name)

        def fallback() -> str:
            return (
                f"✦ <b>Твій характер і сила:</b>\n"
                f"Базовий Аркан {base_arcana_name} наділяє тебе природним відчуттям кордонів, проникливістю та вмінням бачити справжню мотивацію людей.\n\n"
                f"✦ <b>Твої почуття та тіньова сторона:</b>\n"
                f"Аркан душі {soul_arcana_name} вказує на тонку чутливість до фальші. У стресі може з'являтися бажання закритися в собі або контролювати все довкола.\n\n"
                f"<blockquote>Твоя точка сили — у довірі до власної інтуїції. Коли ти не зраджуєш себе заради чужого схвалення, стосунки навколо стають гармонійними.</blockquote>"
            )

        return await self._call_llm(ARCANA_FREE_SYSTEM_PROMPT, user_prompt, fallback)

    # --- 4. Любовний сценарій Арканів (Платний) ---
    async def generate_arcana_deep_love(
        self,
        birth_date: str,
        base_arcana_name: str,
        soul_arcana_name: str
    ) -> str:
        user_prompt = build_arcana_deep_user_prompt(birth_date, base_arcana_name, soul_arcana_name)

        def fallback() -> str:
            return (
                f"✦ <b>1. Яких партнерів ти несвідомо притягуєш:</b>\n"
                f"Твоя конфігурація ({base_arcana_name} + {soul_arcana_name}) часто приваблює яскравих, але емоційно нестабільних партнерів. "
                f"Ти несвідомо бачиш у них потенціал, який хочеш розкрити, забуваючи про власні потреби.\n\n"
                f"✦ <b>2. Повторювані сценарії та тригери:</b>\n"
                f"Головний патерн — віддавати більше турботи й уваги, ніж отримувати натомість. "
                f"Коли накопичується втома, виникає розчарування та відчуття самотності удвох.\n\n"
                f"✦ <b>3. Як вийти з замкненого кола:</b>\n"
                f"Перестань бути «рятівницею». Твій ідеальний баланс — партнер з розвиненою внутрішньою відповідальністю, який діє, а не обіцяє.\n\n"
                f"<blockquote>Практична порада: на початку знайомства оцінюй вчинки людини за місяць, а не її слова за перший вечір.</blockquote>"
            )

        return await self._call_llm(ARCANA_DEEP_LOVE_PROMPT, user_prompt, fallback)


llm_service = LLMService()
