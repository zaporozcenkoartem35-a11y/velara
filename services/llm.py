import re
import html
import time
import asyncio
import logging
from typing import Optional, List, Dict
from openai import AsyncOpenAI, APITimeoutError, APIConnectionError, RateLimitError
from aiogram import Bot
from config import settings
from database.repository import UserRepository
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


class LLMServiceError(Exception):
    """Помилка генерації через LLM API."""
    pass


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

    # Прибираємо заборонені теги Telegram
    allowed_tags = ["b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "blockquote"]
    pattern = r"<(?!/?(" + "|".join(allowed_tags) + r")\b)[^>]*>"
    text = re.sub(pattern, "", text)

    # Нормалізуємо strong -> b, em -> i
    text = text.replace("<strong>", "<b>").replace("</strong>", "</b>")
    text = text.replace("<em>", "<i>").replace("</em>", "</i>")

    # Балансуємо незакриті теги
    for tag in ["b", "i", "blockquote", "code"]:
        open_count = len(re.findall(rf"<{tag}>", text))
        close_count = len(re.findall(rf"</{tag}>", text))
        if open_count > close_count:
            text += f"</{tag}>" * (open_count - close_count)

    return text.strip()


class LLMService:
    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None
        self._bot: Optional[Bot] = None
        self._alert_cooldowns: Dict[str, float] = {}
        if settings.LLM_API_KEY and settings.LLM_API_KEY.strip() not in ("SET_YOUR_KEY_HERE", ""):
            self._client = AsyncOpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
                timeout=settings.LLM_TIMEOUT_SECONDS
            )

    def set_bot(self, bot: Bot) -> None:
        self._bot = bot

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    async def _send_admin_alert(self, error_message: str) -> None:
        """
        Відправляє сповіщення адміністраторам при помилці LLM API.
        Захист від флуду: не частіше 1 однакового сповіщення на 5 хвилин.
        """
        if not self._bot:
            return

        error_key = error_message[:100]
        now = time.time()
        last_sent = self._alert_cooldowns.get(error_key, 0.0)
        if now - last_sent < 300.0:  # 5 хвилин
            return

        self._alert_cooldowns[error_key] = now
        admin_list = settings.ADMIN_IDS if isinstance(settings.ADMIN_IDS, list) else [settings.ADMIN_IDS]
        alert_text = (
            f"🚨 <b>Алерт збою LLM API:</b>\n\n"
            f"• Модель: <code>{settings.LLM_MODEL}</code>\n"
            f"• Помилка: <code>{html.escape(error_message[:400])}</code>\n\n"
            f"<i>Користувачеві надіслано повідомлення про навантаження, кредит збережено. Повторні алерти цієї помилки заглушено на 5 хв.</i>"
        )
        for admin_id in admin_list:
            try:
                await self._bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Не вдалося надіслати алерт адміну {admin_id}: {e}")

    async def _call_llm(self, system_prompt: str, user_prompt: str, user_id: int, feature: str) -> str:
        if not self.is_configured:
            err_msg = "LLM_API_KEY не налаштовано або не задано в .env"
            logger.error(err_msg)
            await self._send_admin_alert(err_msg)
            raise LLMServiceError(err_msg)

        last_exception = None
        is_new_gen = any(k in settings.LLM_MODEL.lower() for k in ["terra", "o1", "o3", "gpt-5", "gpt-6"])

        for attempt in range(2):
            try:
                call_kwargs = {
                    "model": settings.LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "timeout": settings.LLM_TIMEOUT_SECONDS
                }
                if is_new_gen:
                    call_kwargs["max_completion_tokens"] = settings.LLM_MAX_TOKENS
                else:
                    call_kwargs["max_tokens"] = settings.LLM_MAX_TOKENS
                    call_kwargs["temperature"] = settings.LLM_TEMPERATURE

                for _ in range(3):
                    try:
                        response = await self._client.chat.completions.create(**call_kwargs)
                        break
                    except Exception as api_err:
                        err_text = str(api_err).lower()
                        modified = False
                        if "max_completion_tokens" in err_text and "max_tokens" in call_kwargs:
                            logger.info(f"Модель {settings.LLM_MODEL} вимагає max_completion_tokens замість max_tokens")
                            call_kwargs.pop("max_tokens", None)
                            call_kwargs["max_completion_tokens"] = settings.LLM_MAX_TOKENS
                            modified = True
                        if "temperature" in err_text and "temperature" in call_kwargs:
                            logger.info(f"Модель {settings.LLM_MODEL} не підтримує temperature, прибираємо")
                            call_kwargs.pop("temperature", None)
                            modified = True
                        if not modified:
                            raise api_err

                raw_text = response.choices[0].message.content or ""
                clean_text = sanitize_telegram_html(raw_text)
                if not clean_text:
                    raise LLMServiceError("Отримано порожню відповідь від LLM")

                # Фіксація споживання токенів (юніт-економіка)
                if hasattr(response, "usage") and response.usage:
                    p_tok = response.usage.prompt_tokens or 0
                    c_tok = response.usage.completion_tokens or 0
                    try:
                        await UserRepository.record_llm_usage(
                            user_id=user_id,
                            feature=feature,
                            model=settings.LLM_MODEL,
                            prompt_tokens=p_tok,
                            completion_tokens=c_tok
                        )
                    except Exception as ue:
                        logger.warning(f"Не вдалося записати llm_usage: {ue}")

                return clean_text

            except (APITimeoutError, APIConnectionError, RateLimitError) as net_err:
                last_exception = net_err
                if attempt == 0:
                    logger.warning(f"Тимчасова мережева помилка LLM ({net_err.__class__.__name__}). Повтор через 2с...")
                    await asyncio.sleep(2.0)
                    continue
                else:
                    logger.error(f"Повторна мережева помилка LLM: {net_err}")
            except Exception as e:
                last_exception = e
                logger.error(f"Помилка виклику LLM API: {e}", exc_info=True)
                break

        err_text = str(last_exception) if last_exception else "Невідома помилка LLM"
        await self._send_admin_alert(err_text)
        raise LLMServiceError(err_text)

    # --- 1. Таро ---
    async def generate_tarot_reading(self, situation: str, cards: List[DrawnCard], user_id: int) -> str:
        cards_str_list = []
        for i, c in enumerate(cards, start=1):
            pos = "перевернуте" if c.is_reversed else "пряме"
            cards_str_list.append(f"{i}. {c.name_ukr} ({pos} положення) — {c.meaning_upright if not c.is_reversed else c.meaning_reversed}")
        cards_str = "\n".join(cards_str_list)

        user_prompt = build_tarot_user_prompt(situation, cards_str)
        return await self._call_llm(TAROT_SYSTEM_PROMPT, user_prompt, user_id=user_id, feature="tarot")

    # --- 2. Сумісність ---
    async def generate_compatibility(
        self,
        user_name: str,
        user_birth: str,
        user_arcana_name: str,
        partner_name: str,
        partner_birth: str,
        partner_arcana_name: str,
        pair_arcana_name: str,
        user_id: int
    ) -> str:
        user_prompt = build_compatibility_user_prompt(
            user_name, user_birth, user_arcana_name,
            partner_name, partner_birth, partner_arcana_name,
            pair_arcana_name
        )
        return await self._call_llm(COMPATIBILITY_SYSTEM_PROMPT, user_prompt, user_id=user_id, feature="compatibility")

    # --- 3. Аркан долі (Базовий портрет) ---
    async def generate_arcana_portrait(
        self,
        birth_date: str,
        base_arcana_name: str,
        soul_arcana_name: str,
        user_id: int
    ) -> str:
        user_prompt = build_arcana_free_user_prompt(birth_date, base_arcana_name, soul_arcana_name)
        return await self._call_llm(ARCANA_FREE_SYSTEM_PROMPT, user_prompt, user_id=user_id, feature="arcana_portrait")

    # --- 4. Любовний сценарій Арканів (Платний) ---
    async def generate_arcana_deep_love(
        self,
        birth_date: str,
        base_arcana_name: str,
        soul_arcana_name: str,
        user_id: int
    ) -> str:
        user_prompt = build_arcana_deep_user_prompt(birth_date, base_arcana_name, soul_arcana_name)
        return await self._call_llm(ARCANA_DEEP_LOVE_PROMPT, user_prompt, user_id=user_id, feature="arcana_deep_love")


llm_service = LLMService()
