from typing import List
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import settings


def get_interactive_card_grid(selected_indices: List[int]) -> InlineKeyboardMarkup:
    """
    Сітка з 6 закритих карт [ ✦ ].
    Обрані карти позначаються як ✓.
    """
    buttons = []
    for row in range(2):
        row_buttons = []
        for col in range(3):
            idx = row * 3 + col
            if idx in selected_indices:
                text = "✓"
                cb = f"card_pick:ignore:{idx}"
            else:
                text = "[ ✦ ]"
                cb = f"card_pick:{idx}"
            row_buttons.append(InlineKeyboardButton(text=text, callback_data=cb))
        buttons.append(row_buttons)

    buttons.append([InlineKeyboardButton(text="« Скасувати", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_tarot_paywall_keyboard() -> InlineKeyboardMarkup:
    """
    Акуратний пейвол на Таро без тиску.
    Ціни беруться строго з налаштувань.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"⭐ 1 розклад — {settings.tarot_price_1} Stars",
                callback_data="buy_stars:tarot_1"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"⭐ 3 розклади — {settings.tarot_price_3} Stars (-15%)",
                callback_data="buy_stars:tarot_3"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎁 Отримати безкоштовно за подругу",
                callback_data="btn_profile"
            )
        ],
        [
            InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_compat_paywall_keyboard() -> InlineKeyboardMarkup:
    """
    Пейвол для модуля сумісності після використання 1 безкоштовної спроби.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"⭐ Перевірка сумісності — {settings.compat_price} Stars",
                callback_data="buy_stars:compat_1"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎁 Запросити подругу (+1 перевірка)",
                callback_data="btn_profile"
            )
        ],
        [
            InlineKeyboardButton(text="« До меню", callback_data="back_to_menu")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_after_tarot_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🌙 Зробити ще один розклад", callback_data="btn_tarot")
            ],
            [
                InlineKeyboardButton(text="« До головного меню", callback_data="back_to_menu")
            ]
        ]
    )
