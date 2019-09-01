from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def one_button_markup(*args, **kwargs):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(*args, **kwargs)]
    ])

