from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import settings


def get_arcana_upsell_keyboard() -> InlineKeyboardMarkup:
    """
    Клавіатура апселу для любовного сценарію Арканів.
    Ціна динамічно підтягується з settings.arcana_love_price.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔒 Розкрити любовний сценарій ({settings.arcana_love_price} ⭐)",
                    callback_data="buy_stars:arcana_love"
                )
            ],
            [
                InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")
            ]
        ]
    )
