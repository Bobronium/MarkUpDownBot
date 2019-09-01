import asyncio
import logging
from contextlib import contextmanager
from functools import partial
from unittest.mock import patch

from aiogram import Bot, Dispatcher
from aiogram.types import Message, Update, MessageEntityType, CallbackQuery
from aiogram.utils.exceptions import CantParseEntities, MessageNotModified
from aiogram.utils.markdown import text, code

import config
from keyboards import one_button_markup
from messages import get_send_method, get_file_id

logger = logging.getLogger('bot')

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(bot=bot)

SHOW_RAW = 'Markdown'
SHOW_FORMATTED = 'Markup'

SHOW_RAW_MARKUP = one_button_markup(SHOW_RAW, callback_data=SHOW_RAW)
SHOW_FORMATTED_MARKUP = one_button_markup(SHOW_FORMATTED, callback_data=SHOW_FORMATTED)

GREETING = text(
    '*Hello there!*',
    'Send me message with some markup and I will convert it to '
    '[raw markdown](https://core.telegram.org/bots/api#markdown-style)',

    '\nMessages containing media with caption are also supported',

    '\n_(underline and strikethrough text is not supported yet)_',
    sep='\n'
)


@contextmanager
def dont_escape_md():
    """
    Dirty hack to avoid aiogram escape existing md symbols and modifying plain urls
    """
    with patch('aiogram.utils.markdown.escape_md', new=lambda s: s), patch.object(MessageEntityType, 'URL', new=None):
        yield


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
        offset = len(encoded[:offset + 1].decode())
        exc_message += f', (chars offset {offset})'
    except ValueError as e:
        logger.exception(e)
    else:
        chars_before = 25
        if offset < chars_before:
            chars_before = offset

        start = offset - chars_before

        bad_line = bad_text.replace('\n', ' ')[start:offset + 5]
        pointer_line = ' ' * (chars_before - 1) + '^'
        caption = f':\n\n{code(bad_line)}\n{code(pointer_line)}'
        exc_message += caption

    return exc_message


@dp.message_handler(commands='start')
async def greet_user(message: Message):
    await message.reply(GREETING, parse_mode='markdown', reply_markup=SHOW_RAW_MARKUP, disable_web_page_preview=True)


@dp.message_handler(content_types=config.MEDIA_CONTENT_TYPES)
async def answer_on_message(message: Message):
    """
    Extracts markdown text from message and sends it back with same media
    If message doesn't have any formatting in entities (plain urls, mentions, etc... doesn't count),
    sends it with parse_mode='markdown'
    """

    with dont_escape_md():
        try:
            md_text = message.md_text
        except TypeError:
            md_text = 'Why would you _send me_ `media` without *any* `caption`?'

    content = get_file_id(message) or md_text
    send_content = get_send_method(message, message.chat.id, content, disable_web_page_preview=True, caption=md_text)

    raw_text = message.text or message.caption
    if raw_text == md_text:
        # Message didn't contain any special entities
        # so try to format it as markdown
        send_content = partial(send_content, parse_mode='markdown', reply_markup=SHOW_RAW_MARKUP)
    else:
        send_content = partial(send_content, reply_markup=SHOW_FORMATTED_MARKUP)

    try:
        await send_content()
    except CantParseEntities as e:
        err_message = get_error_caption(md_text, str(e))
        await message.reply(err_message, parse_mode='markdown')
    else:
        await message.delete()


@dp.callback_query_handler(lambda q: q.data in (SHOW_RAW, SHOW_FORMATTED))
async def modify_message(query: CallbackQuery):
    """
    That's how `Markup` and `Markdown` buttons work

    Basically it edits message just changing its parse_mode
    """
    message = query.message

    if query.data == SHOW_FORMATTED:
        markup = SHOW_RAW_MARKUP
        parse_mode = 'markdown'
    else:
        markup = SHOW_FORMATTED_MARKUP
        parse_mode = None

    with dont_escape_md():
        new_text = message.md_text

    if message.caption:
        edit_message = message.edit_caption
    else:
        edit_message = partial(message.edit_text, disable_web_page_preview=True)

    answer_callback = asyncio.create_task(query.answer())  # remove 'Loading...' on user side quickly

    try:
        await edit_message(new_text, parse_mode=parse_mode, reply_markup=markup)
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
    await message.bot.send_message(message.chat.id, 'Oops... Something went wrong.')
    logger.exception(exception)
