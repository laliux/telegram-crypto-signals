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
        self.updater = Updater(token)
        self.chat_id = chat_id
        self.parse_mode = parse_mode

        self.setup_bot()

    @retry(
        retry=retry_if_exception_type(telegram.error.TimedOut),
        stop=stop_after_attempt(6),
        wait=wait_fixed(5)
    )
    def notify(self, message):
        """Send the notification.

        Args:
            message (str): The message to send.
        """

        max_message_size = 4096
        message_chunks = self.chunk_message(message=message, max_message_size=max_message_size)

        for message_chunk in message_chunks:
            self.updater.bot.send_message(chat_id=self.chat_id, text=message_chunk, parse_mode=self.parse_mode)


    @retry(
        retry=retry_if_exception_type(telegram.error.TimedOut),
        stop=stop_after_attempt(6),
        wait=wait_fixed(5)
    )
    def send_chart(self, photo_url, caption):
        """Send image chart

        Args:
            photo_url (str): The photo url to send.
        """

        self.updater.bot.send_photo(chat_id=self.chat_id, photo=photo_url, caption=caption, timeout=40)

    def register_markets(self, markets):
        self.logger.info('entro a este metodo %s' , markets)

    def stop_bot(self):
        if self.updater.running :
            self.updater.stop()

    def setup_bot(self):
        """Start the bot."""
        # Get the dispatcher to register handlers
        dp = self.updater.dispatcher

        # on different commands - answer in Telegram
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("help", help))

        # on noncommand i.e message - echo the message on Telegram
        dp.add_handler(MessageHandler(Filters.text, echo))

        # log all errors
        dp.add_error_handler(error)

        #updater.bot.send_message(chat_id=20739325, text='Holi')

        # Start the Bot
        self.updater.start_polling()

        # Run the bot until you press Ctrl-C or the process receives SIGINT,
        # SIGTERM or SIGABRT. This should be used most of the time, since
        # start_polling() is non-blocking and will stop the bot gracefully.
        #self.updater.idle()     


def start(bot, update):
        """Send a message when the command /start is issued."""
        update.message.reply_text('Hi!')


def help(bot, update):
        """Send a message when the command /help is issued."""
        update.message.reply_text('TODO: show help')


def echo(bot, update):
        """Echo the user message."""
        reply = "Unknown command " + update.message.text
        update.message.reply_text(reply)

def error(bot, update, error):
        """Log Errors caused by Updates."""
        #logger.warning('Update "%s" caused error "%s"', update, error)           
