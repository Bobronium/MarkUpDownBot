
import asyncio
import logging
from typing import Optional
from unittest.mock import patch

from aiogram import Bot, Dispatcher
from aiogram.types import Message, Update, MessageEntityType, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import markdown
from aiogram.utils.exceptions import CantParseEntities, MessageNotModified
from aiogram.utils.markdown import text, code, escape_md, quote_html, pre, LIST_MD_SYMBOLS

import config

logger = logging.getLogger('bot')

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(bot=bot)

SHOW_RAW_MD = 'Markdown'
SHOW_RAW_HTML = 'HTML'
SHOW_FORMATTED = 'Markup'

SHOW_RAW_MARKUP = InlineKeyboardMarkup(
    inline_keyboard=[[
        InlineKeyboardButton(text=SHOW_RAW_MD, callback_data=SHOW_RAW_MD),
        InlineKeyboardButton(text=SHOW_RAW_HTML, callback_data=SHOW_RAW_HTML)
    ]]
)

SHOW_FORMATTED_MARKUP = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text=SHOW_FORMATTED, callback_data=SHOW_FORMATTED)
]])

GREETING = text(
    '*Hello there!*',

    '\nSend me message _with_ `some` *markup*, '
    '[raw markdown](https://core.telegram.org/bots/api#markdown-style) or '
    '[raw html](https://core.telegram.org/bots/api#html-style).',

    '\nSupported tags:',
    '- *bold text*',
    '- _italic text_',
    '- `inline fixed-width code`',
    '- [inline mention of a user](tg://user?id=93212972)',
    '- [inline URL](http://www.example.com/)',
    '```\nblock_language\n    pre-formatted fixed-width code block```',

    '\n_(underline and strikethrough text is not supported yet)_',
    sep='\n'
)

# Dirty hack to avoid aiogram escape existing symbols and modifying plain urls
# TODO: PR for this maybe?
dont_escape_md = patch('aiogram.utils.markdown.escape_md', new=lambda s: s)
dont_change_plain_urls = patch.object(MessageEntityType, 'URL', new='NOT URL')

# Remove '\n' before closing ``` in markdown
# Otherwise newlines will grow on each parsing
markdown.MD_SYMBOLS = (
        markdown.MD_SYMBOLS[:3] + ((LIST_MD_SYMBOLS[2] * 3 + '\n', LIST_MD_SYMBOLS[2] * 3),) + markdown.MD_SYMBOLS[4:]
)


def get_error_caption(bad_text: str, exc_message: str):
    """
    :param bad_text: text with improper formatting
    :param exc_message: message that contains info about symbol that caused error

    :return: error message and caption with pointer to the symbol that caused error
    """

    try:
        _, offset = exc_message.rsplit('offset', maxsplit=1)
        offset = int(offset.strip())
        encoded = bad_text.encode()
        offset = len(encoded[:offset].decode())
        exc_message += f', (chars offset {offset})'
    except ValueError as e:
        logger.exception(e)
    else:
        chars_before = 25
        if offset < chars_before:
            chars_before = offset

        bad_char = offset + 1
        start = bad_char - chars_before

        bad_line = bad_text.replace('\n', ' ')[start:offset + 5]
        pointer_line = ' ' * (chars_before - 1) + '^'
        caption = f':\n\n{pre(bad_line)}\n{code(pointer_line)}'
        exc_message += caption

    return exc_message


def detect_message_text_formatting(message: Message) -> Optional[str]:
    """
    Detects message formatting
    (html, markdown or None if message has special entities)
    """

    raw_text: str = message.text

    before_escape_md = raw_text.count('\\')
    before_escape_html = raw_text.count('&')

    escaped_md = escape_md(raw_text).count('\\') - before_escape_md
    escaped_html = quote_html(raw_text).count('&') - before_escape_html

    with dont_change_plain_urls, dont_escape_md:
        with_entities = message.md_text

    escaped_with_entities = escape_md(with_entities).count('\\') - before_escape_md

    if escaped_with_entities > max(escaped_html, escaped_md):
        parse_mode = None
    elif escaped_html > escaped_md:
        parse_mode = 'html'
    else:
        parse_mode = 'markdown'

    return parse_mode


@dp.message_handler(commands='start')
async def greet_user(message: Message):
    await message.reply(GREETING, parse_mode='markdown', reply_markup=SHOW_RAW_MARKUP, disable_web_page_preview=True)


@dp.message_handler()
async def answer_on_message(message: Message):
    """
    If message sent without tg formatting, detects its formatting (md or html) and send it back parsed
    Otherwise sends it unchanged
    """

    formatting = detect_message_text_formatting(message)

    if formatting is None:
        # Message contained special entities
        bot.parse_mode = 'markdown'
        with dont_change_plain_urls:
            message_text = message.md_text
    else:
        # Send it with parse mode matching plain text formatting
        bot.parse_mode = formatting
        message_text = message.text

    markup = SHOW_RAW_MARKUP

    try:
        await bot.send_message(message.chat.id, message_text, reply_markup=markup, disable_web_page_preview=True)
    except CantParseEntities as e:
        err_message = get_error_caption(message_text, str(e))
        await message.reply(err_message, parse_mode='markdown')
    else:
        await message.delete()


@dp.callback_query_handler(lambda q: q.data in (SHOW_RAW_MD, SHOW_RAW_HTML, SHOW_FORMATTED))
async def modify_message(query: CallbackQuery):
    """
    That's how `Markup` and `Markdown` buttons work

    Basically it edits message just changing its parse_mode
    """
    message = query.message

    if query.data == SHOW_FORMATTED:
        bot.parse_mode = detect_message_text_formatting(message)
        markup = SHOW_RAW_MARKUP
        new_text = message.text
    else:
        markup = SHOW_FORMATTED_MARKUP
        to_html = query.data == SHOW_RAW_HTML
        with dont_change_plain_urls:
            bot.parse_mode = 'html' if to_html else 'markdown'  # https://github.com/aiogram/aiogram/pull/205/
            new_text = message.html_text if to_html else message.md_text
        bot.parse_mode = None

    answer_callback = asyncio.create_task(query.answer())  # remove 'Loading...' on user side quickly

    try:
        await message.edit_text(new_text, disable_web_page_preview=True, reply_markup=markup)
    except CantParseEntities as e:
        answer_callback.cancel()
        await query.answer(str(e), show_alert=True)
    except MessageNotModified:
        answer_callback.cancel()
        await query.answer('Message has no formatting')
    else:
        await answer_callback


@dp.errors_handler()
async def handle_errors(update: Update, exception):
    message = update.message or update.callback_query.message
    if message is None:
        return
    await message.bot.send_message(message.chat.id, 'Oops... Something went wrong here.')
    logger.exception(exception)
