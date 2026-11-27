import asyncio
from typing import Callable, Dict, Any, Awaitable, Set
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

# Набір користувачів, для яких прямо зараз генерується відповідь LLM
_active_generation_users: Set[int] = set()


class UserLockManager:
    @staticmethod
    def is_locked(user_id: int) -> bool:
        return user_id in _active_generation_users

    @staticmethod
    def acquire(user_id: int) -> bool:
        if user_id in _active_generation_users:
            return False
        _active_generation_users.add(user_id)
        return True

    @staticmethod
    def release(user_id: int) -> None:
        _active_generation_users.discard(user_id)


class ThrottlingMiddleware(BaseMiddleware):
    """
    Захист від паралельних запитів до LLM та подвійних кліків.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id and UserLockManager.is_locked(user_id):
            # Якщо користувач зараз у процесі генерації розкладу
            if isinstance(event, CallbackQuery):
                await event.answer("Я ще зчитую карти, зачекай кілька секунд...", show_alert=True)
                return
            elif isinstance(event, Message):
                await event.answer("<i>Я ще розкладаю карти, зачекай кілька секунд...</i>", parse_mode="HTML")
                return

        return await handler(event, data)
