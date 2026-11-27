from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Клавіатура ворожки Велари з інтерактивним віджетом та кнопками під болі аудиторії.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="🔮 ВІДКРИТИ ІНТЕРАКТИВНИЙ АЛТАР ТАРО ✨",
                web_app=WebAppInfo(url="https://velara-85ws.onrender.com/tarot")
            )
        ],
        [
            InlineKeyboardButton(text="🔮 Що він думає про мене?", callback_data="feature:thoughts"),
            InlineKeyboardButton(text="💔 Чи будемо ми разом?", callback_data="feature:together")
        ],
        [
            InlineKeyboardButton(text="🕯 Розклад на майбутнє та долю", callback_data="feature:future"),
            InlineKeyboardButton(text="❤️ Сумісність за датами", callback_data="feature:compatibility")
        ],
        [
            InlineKeyboardButton(text="💰 Грошовий канал та кар'єра", callback_data="feature:finance")
        ],
        [
            InlineKeyboardButton(text="🧿 Отримати особистий розклад у подарунок", callback_data="feature:gift_spread")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
