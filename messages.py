import inspect
from functools import partial
from typing import Optional

from aiogram.types import Message

from bot import SendMessageMethod, bot, AnyContentType


def get_send_method(message: Message, *args, **kwargs) -> SendMessageMethod:
    """
    :return: appropriate method to resend message content
    """
    send_method: SendMessageMethod = getattr(bot, f'send_{message.content_type}', bot.send_message)

    if kwargs:
        acceptable_kwargs = inspect.getfullargspec(send_method).args
        for k in set(kwargs):
            if k not in acceptable_kwargs:
                kwargs.pop(k)

        return partial(send_method, *args, **kwargs)


def get_file_id(message: Message) -> Optional[str]:
    """
    :return file_id of message media
    """
    if message.content_type == 'text':
        return None

    content: AnyContentType = getattr(message, message.content_type)

    if message.content_type == 'photo':
        content = content[-1]  # taking the largest photo from the sizes list

    return content.file_id