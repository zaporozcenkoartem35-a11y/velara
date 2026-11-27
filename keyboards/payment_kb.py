from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import settings


def get_arcana_upsell_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔒 Розкрити любовний сценарій ({settings.ARCANA_LOVE_PRICE} ⭐)",
                    callback_data="buy_stars:arcana_love"
                )
            ],
            [
                InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")
            ]
        ]
    )
