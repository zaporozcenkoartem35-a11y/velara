from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import settings


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Чисте головне меню Velara.
    """
    keyboard = [
        [
            InlineKeyboardButton(text="🌙 Розклад Таро", callback_data="btn_tarot")
        ],
        [
            InlineKeyboardButton(text="✨ Сумісність", callback_data="btn_compatibility"),
            InlineKeyboardButton(text="✦ Мій Аркан", callback_data="btn_my_arcana")
        ],
        [
            InlineKeyboardButton(text="👤 Профіль / Запросити подругу", callback_data="btn_profile")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Скасувати", callback_data="back_to_menu")]
        ]
    )


def get_profile_keyboard(referral_link: str) -> InlineKeyboardMarkup:
    share_url = f"https://t.me/share/url?url={referral_link}&text=Тримай%20безкоштовний%20розклад%20Таро%20та%20сумісність%20у%20Велари%20✨"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💌 Поділитися з подругою (+1 бонус)", url=share_url)
            ],
            [
                InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")
            ]
        ]
    )
