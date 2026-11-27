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
            logger.warning("LLM API_KEY не налаштовано в .env. Використовується евристичний фоллбек.")
            return fallback_func()

        try:
            response = await self._client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=900
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
            cards_str_list.append(
                f"{i}. Позиція: {c.position_title}\n"
                f"   Карта: {c.display_name} ({c.suit})\n"
                f"   Ключові сенси: {c.keywords}"
            )
        cards_info = "\n\n".join(cards_str_list)

        def fallback() -> str:
            c1, c2, c3 = cards[0], cards[1], cards[2]
            return (
                f"<b>Суть</b>\n"
                f"У твоїй ситуації зараз випала карта <b>{c1.display_name}</b>. "
                f"Це показує, що зовнішня картинка значно простіша за твої внутрішні переживання. "
                f"Зараз немає сенсу додумувати за людину її мотиви — дивись виключно на реальні вчинки.\n\n"
                f"<b>Що приховано</b>\n"
                f"Карта <b>{c2.display_name}</b> розкриває приховане: між вами є недомовленість або страх здатися вразливим. "
                f"Партнер займає позицію вичікування, бо боїться втратити контроль над ситуацією.\n\n"
                f"<b>Що робити</b>\n"
                f"Вектор задає карта <b>{c3.display_name}</b>: зроби крок назад у власний спокій. "
                f"Не випитуй і не тисни. Чітка внутрішня опора зараз спрацює у рази сильніше, ніж спроби витягнути пояснення силою."
            )

        user_prompt = build_tarot_user_prompt(situation, cards_info)
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
        def fallback() -> str:
            return (
                f"<b>Де іскра</b>\n"
                f"Поєднання Арканів «{user_arcana_name}» та «{partner_arcana_name}» дає сильне перше тяжіння. "
                f"Вас тягне одне до одного на контрасті: те, чого не вистачає одному, є з надлишком в іншого. "
                f"Спільний Аркан союзу «{pair_arcana_name}» говорить про те, що ця зустріч відчувається як щось неминуче.\n\n"
                f"<b>Головні граблі</b>\n"
                f"Основний камінь спотикання — різні швидкості та способи переживати стрес. "
                f"Коли виникає непорозуміння, один прагне з'ясувати все негайно, а інший закривається в панцир. "
                f"Якщо сприймати мовчання як нелюбов — почнеться руйнівна гра в образу.\n\n"
                f"<b>Реальний прогноз</b>\n"
                f"Цей союз житиме довго лише за умови прямої дорослої розмови без натяків. "
                f"Перестаньте виховувати одне одного. Тут потрібна домовленість про особисті кордони, а не злиття в одне ціле.\n\n"
                f"✦ @Velara_bot"
            )

        user_prompt = build_compatibility_user_prompt(
            user_name, user_birth, user_arcana_name,
            partner_name, partner_birth, partner_arcana_name,
            pair_arcana_name
        )
        return await self._call_llm(COMPATIBILITY_SYSTEM_PROMPT, user_prompt, fallback)

    # --- 3. Базовий Аркан ---
    async def generate_arcana_portrait(
        self,
        birth_date: str,
        base_arcana_name: str,
        soul_arcana_name: str
    ) -> str:
        def fallback() -> str:
            return (
                f"<b>Твоя сила</b>\n"
                f"Твій провідний архетип — <b>{base_arcana_name}</b>. Твоя сила в умінні тримати внутрішній стрижень, "
                f"коли навколо все хитається. Ти інтуїтивно відчуваєш фальш за перші кілька секунд спілкування, "
                f"а Аркан душі <b>{soul_arcana_name}</b> додає рідкісну глибину почуттів і вміння любити по-справжньому.\n\n"
                f"<b>Твоя пастка</b>\n"
                f"Ти схильна виправдовувати холодність інших своєю 'терплячістю'. "
                f"Коли людина дає тобі мінімум — ти починаєш шукати причину в собі, застрягаючи в очікуванні, "
                f"що він колись оцінить твою вірність.\n\n"
                f"<b>Чесний фокус</b>\n"
                f"Перестань бути рятувальницею для тих, хто не просив про допомогу. "
                f"Твоя цінність не вимірюється тим, скільки болю ти змогла витримати в стосунках."
            )

        user_prompt = build_arcana_free_user_prompt(birth_date, base_arcana_name, soul_arcana_name)
        return await self._call_llm(ARCANA_FREE_SYSTEM_PROMPT, user_prompt, fallback)

    # --- 4. Платний любовний сценарій ---
    async def generate_arcana_deep_love(
        self,
        birth_date: str,
        base_arcana_name: str,
        soul_arcana_name: str
    ) -> str:
        def fallback() -> str:
            return (
                f"<b>Кого ти несвідомо притягуєш</b>\n"
                f"Через взаємодію Арканів {base_arcana_name} та {soul_arcana_name} до тебе тягнуться емоційно "
                f"закриті або втомлені від життя чоловіки. Вони бачать у тобі безпечну гавань, ресурс і здатність зрозуміти все без слів. "
                f"Але проблема в тому, що вони приходять брати, а не віддавати взамін.\n\n"
                f"<b>Чому повторюється той самий сценарій</b>\n"
                f"Ти плутаєш спокій із нудьгою, а тривогу та гойдалки — зі справжньою пристрастю. "
                f"Якщо чоловік доступний, надійний і не зникає, тобі здається, що 'немає іскри'. "
                f"Але щойно він віддаляється — вмикається азарт довести свою важливість.\n\n"
                f"<b>Який партнер тобі насправді потрібен</b>\n"
                f"Тобі потрібна людина зі зрілим Імператорським або Магічним стрижнем: той, чиї слова не розходяться з діями. "
                f"Чоловік, який не боїться говорити про почуття прямо і не змушує тебе гадати на кавовій гущі, "
                f"хто ти для нього сьогодні."
            )

        user_prompt = build_arcana_deep_user_prompt(birth_date, base_arcana_name, soul_arcana_name)
        return await self._call_llm(ARCANA_DEEP_LOVE_PROMPT, user_prompt, fallback)


llm_service = LLMService()
