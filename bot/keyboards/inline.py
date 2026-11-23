from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура гадалки Велары.
    Сформулирована под самые горячие боли аудитории из TikTok:
    отношения, мысли партнёра, будущее, финансы.
    """
    keyboard = [
        [
            InlineKeyboardButton(text="🔮 Что он думает обо мне?", callback_data="feature:thoughts"),
            InlineKeyboardButton(text="💔 Будем ли мы вместе?", callback_data="feature:together")
        ],
        [
            InlineKeyboardButton(text="🕯 Расклад на будущее и судьбу", callback_data="feature:future"),
            InlineKeyboardButton(text="❤️ Совместимость по датам", callback_data="feature:compatibility")
        ],
        [
            InlineKeyboardButton(text="💰 Денежный канал и карьера", callback_data="feature:finance")
        ],
        [
            InlineKeyboardButton(text="🧿 Получить личный расклад в подарок", callback_data="feature:gift_spread")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
