"""Notify a user via telegram
"""

import json

import structlog
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from notifiers.utils import NotifierUtils


class TelegramNotifier(NotifierUtils):
    """Used to notify user of events via telegram.
    """

    def __init__(self, token, chat_id, parse_mode):
        """Initialize TelegramNotifier class

        Args:
            token (str): The telegram API token.
            chat_id (str): The chat ID you want the bot to send messages to.
        """

        self.logger = structlog.get_logger()
        #self.bot = telegram.Bot(token=token)
        # Create the EventHandler and pass it your bot's token.
        #self.updater = Updater(token)
        self.chat_id = chat_id
        self.parse_mode = parse_mode
        self.updater = None

    @retry(
        retry=retry_if_exception_type(telegram.error.TimedOut),
        stop=stop_after_attempt(6),
        wait=wait_fixed(5)
    )
    def notify(self, message, chat_id = None):
        """Send the notification.

        Args:
            message (str): The message to send.
        """

        if chat_id == None:
            chat_id = self.chat_id
            
        max_message_size = 4096
        message_chunks = self.chunk_message(message=message, max_message_size=max_message_size)

        for message_chunk in message_chunks:
            self.updater.bot.send_message(chat_id=chat_id, text=message_chunk, parse_mode=self.parse_mode)


    @retry(
        retry=retry_if_exception_type(telegram.error.TimedOut),
        stop=stop_after_attempt(6),
        wait=wait_fixed(5)
    )
    def send_chart(self, photo_url, caption, chat_id = None):
        """Send image chart

        Args:
            photo_url (str): The photo url to send.
        """
        if chat_id == None:
            chat_id = self.chat_id

        self.updater.bot.send_photo(chat_id=chat_id, photo=photo_url, caption=caption, timeout=40)

    def set_updater(self, updater):
        self.updater = updater       
