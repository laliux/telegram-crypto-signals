
"""Simple Bot to send timed Telegram messages.

# This program is dedicated to the public domain under the CC0 license.

This Bot uses the Updater class to handle the bot and the JobQueue to send
timed messages.

First, a few handler functions are defined. Then, those functions are passed to
the Dispatcher and registered at their respective places.
Then, the bot is started and runs until we press Ctrl-C on the command line.

Usage:
Basic Alarm Bot example, sends a message after a set time.
Press Ctrl-C on the command line or send a signal to the process to stop the
bot.
"""

from telegram.ext import Updater, CommandHandler
from conf import Configuration
from exchange import ExchangeInterface
from notification import Notifier
from behaviour import Behaviour

import logs
import structlog

# Load settings and create the config object
config = Configuration()
settings = config.settings

config_indicators = config.indicators

# Set up logger
logs.configure_logging(settings['log_level'], settings['log_mode'])
logger = structlog.get_logger()

# Configure and run configured behaviour.
exchange_interface = ExchangeInterface(config.exchanges)

if settings['market_pairs']:
    market_pairs = settings['market_pairs']
    logger.info("Found configured markets: %s", market_pairs)
    market_data = exchange_interface.get_exchange_markets(markets=market_pairs)
else:
    logger.info("No configured markets, using all available on exchange.")
    market_data = exchange_interface.get_exchange_markets()

notifier = Notifier(config.notifiers, market_data)

#Dict to save user defined fibonacci levels
fibonacci = None


def setup_fibonacci(market_data):
    global fibonacci

    fibonacci = dict()

    for exchange in market_data:
        fibonacci[exchange] = dict()

        for market_pair in market_data[exchange]:
            add_to_fibonnaci(exchange, market_pair)


def add_to_fibonnaci(exchange, market_pair):
    global fibonacci

    fibonacci[exchange][market_pair] = dict()

    fibonacci[exchange][market_pair]['0.00'] = 0
    fibonacci[exchange][market_pair]['23.60'] = 0
    fibonacci[exchange][market_pair]['38.20'] = 0
    fibonacci[exchange][market_pair]['50.00'] = 0
    fibonacci[exchange][market_pair]['61.80'] = 0
    fibonacci[exchange][market_pair]['78.60'] = 0
    fibonacci[exchange][market_pair]['100.00'] = 0


# Define a few command handlers. These usually take the two arguments bot and
# update. Error handlers also receive the raised TelegramError object in error.

def start(bot, update, job_queue, chat_data):
    global settings
    
    """Add job to the queue with due = settings['update_interval'] ."""
    
    chat_id = update.message.chat_id
    
    try:
        update.message.reply_text('Hi! Welcome to Crypto Signals Bot')
        
        # args[0] should contain the time for the timer in seconds
        due = int(settings['update_interval'])
        if due < 0:
            update.message.reply_text('Dont forget to set the update interval. Use the /timeout command !')
            return

        if 'job' not in chat_data:
            # Add job to queue
            job = job_queue.run_repeating(alarm, due, context=chat_id)
            chat_data['job'] = job

            update.message.reply_text('Default update interval from config file set to %d seconds!' % due)

    except (IndexError, ValueError):
        update.message.reply_text('Dont forget to set the update interval. Type /help for more info.')

def help(bot, update):
    update.message.reply_text('Available commands:')
    update.message.reply_text('/timeout to set the update interval')
    update.message.reply_text('/unset to reset the timeout value - removes timer.')
    update.message.reply_text('/markets to get a list of market pairs')
    update.message.reply_text('/market to add or remove a market pair')
    update.message.reply_text('/indicators to get a list of configured indicators')
    update.message.reply_text('/indicator to disable/enable an indicator')

def markets(bot, update):
    update.message.reply_text('List of market pairs to analyze ... ')
    update.message.reply_text(str(market_pairs))

def alarm(bot, job):
    global config, exchange_interface, notifier, settings, market_data, fibonacci

    notifier.update_market_data(market_data)

    behaviour = Behaviour(
            config,
            exchange_interface,
            notifier
        )

    behaviour.run(market_data, fibonacci, settings['output_mode'])

def fibo(bot, update, args):
    """Set Fibonnaci levels for a specific market pair."""
    global fibonacci

    try:
        # args[0] is the operation to do
        min_max = args[0].lower()
        # args[1] should contain the name of market
        market_pair = ("%s/USDT" % args[1].strip()).upper()
        # args[2] is the value to set
        value = float(args[2])

        try:
            if market_pair in fibonacci['binance']: 
                level = fibonacci['binance'][market_pair]

                if min_max == 'min':
                    level['100.00'] = value
                else:
                    level['0.00'] = value

                if level['0.00'] > 0 and level['0.00'] > level['100.00']:
                    price_max = level['0.00']
                    price_min = level['100.00'] 
                    diff = price_max - price_min

                    level['23.60'] = price_max - 0.236 * diff
                    level['38.20'] = price_max - 0.382 * diff
                    level['50.00'] = price_max - 0.50 * diff
                    level['61.80'] = price_max - 0.618 * diff
                    level['78.60'] = price_max - 0.786 * diff


                update.message.reply_text('Successfully set %s as %s value for %s!' % (args[2], args[1], market_pair))
            
        except(ValueError):
            update.message.reply_text('Problems setting %s %s!' % (args[2], market_pair))

    except (IndexError, ValueError) as err:
        logger.error('Error on fibo() command... %s', err)
        update.message.reply_text('Usage: /fibo <min|max> <market_pair> value')

def chart(bot, update, args):
    """Send a chart image for a specific market pair and candle period."""
    global market_data, notifier

    try:
        # args[0] should contain the name of market
        market_pair = ("%s/USDT" % args[0].strip()).upper()

        if market_pair in market_data['binance']: 
            candle_period = args[1]

            notifier.notify_telegram_chart('binance', market_pair, candle_period)
        else:
            update.message.reply_text('Market pair %s is not configured!' % market_pair)

    except (IndexError, ValueError) as err:
        logger.error('Error on chart() command... %s', err)
        update.message.reply_text('Usage: /chart <market_pair> <candle_period>')

def market(bot, update, args):
    """Add/Remove a marker pair."""
    global market_data

    change = False

    try:
        # args[0] is the operation to do
        operation = args[0]
        # args[1] should contain the name of market
        market_pair = ("%s/USDT" % args[1].strip()).upper()

        if operation == 'add':
            try:
                settings['market_pairs'].append(market_pair)
                
                #TODO: call get_default_exchange()
                exchange = 'binance'
                add_to_fibonnaci(exchange, market_pair)

                update.message.reply_text('%s successfully added!' % market_pair)
                change = True
            except(ValueError):
                update.message.reply_text('Problems adding %s!' % market_pair)

        if operation == 'remove':
            try:
                settings['market_pairs'].remove(market_pair)
                update.message.reply_text('%s successfully removed!' % market_pair)
                change = True
            except(ValueError):
                update.message.reply_text('%s is not in market pairs list.' % market_pair)

        if change == True:
            market_data = exchange_interface.get_exchange_markets(markets=settings['market_pairs'])

    except (IndexError, ValueError) as err:
        logger.error('Error on market() command... %s', err)
        update.message.reply_text('Usage: /market <add|remove> pair')

def indicators(bot, update):
    """ Display enabled indicators """
    update.message.reply_text('Configured indicators ... ')

    for indicator in config.indicators:
        msg = indicator

        for conf in config.indicators[indicator] :
            if conf['enabled']:
                msg = '%s %s' % (msg, conf['candle_period'])

        if msg != indicator :
            update.message.reply_text(msg)

def indicator(bot, update, args):
    """ Manage indicators """
    if args is None or len(args) == 0 :
        update.message.reply_text('Usage: /indicator <indicator> <candle_period> <enable|disable>')
    else:
        try:
            # args[0] is the name of indicator
            indicator = args[0].strip().lower()
            # args[1] is the candle period
            candle_period = args[1]
            # args[2] the operation
            enabled = args[2] == 'enable'

            for idx, conf in enumerate(config.indicators[indicator]) :
                if conf['candle_period'] == candle_period:
                    config.indicators[indicator][idx]['enabled'] = enabled
            
            update.message.reply_text('Changes applied successfully!')
        except (IndexError, ValueError) as err:
            logger.error('Error on indicator() command... %s', err)
            update.message.reply_text('Usage: /indicator <indicator> <15m|30m|1h|4h> <enable|disable>')

def set_timeout(bot, update, args, job_queue, chat_data):
    """Add a job to the queue."""
    chat_id = update.message.chat_id
    try:
        # args[0] should contain the time for the timer in seconds
        due = int(args[0])
        if due < 0:
            update.message.reply_text('Sorry we can not go back to future!')
            return

        # Add job to queue
        job = job_queue.run_repeating(alarm, due, context=chat_id)
        chat_data['job'] = job

        update.message.reply_text('Timeout successfully set to %d!' % due)

    except (IndexError, ValueError):
        update.message.reply_text('Usage: /timeout <seconds>')


def unset(bot, update, chat_data):
    """Remove the job if the user changed their mind."""
    if 'job' not in chat_data:
        update.message.reply_text('You have no active timer')
        return

    job = chat_data['job']
    job.schedule_removal()
    del chat_data['job']

    update.message.reply_text('Timer successfully unset!')


def error(bot, update, error):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, error)


def main():
    global market_data

    setup_fibonacci(market_data)

    """Run bot."""
    updater = Updater(config.notifiers['telegram']['required']['token'])

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # on different commands - answer in Telegram
    dp.add_handler(CommandHandler("start", start, 
                                  pass_job_queue=True, 
                                  pass_chat_data=True ))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(CommandHandler("timeout", set_timeout,
                                  pass_args=True,
                                  pass_job_queue=True,
                                  pass_chat_data=True))
    dp.add_handler(CommandHandler("markets", markets))                                  
    dp.add_handler(CommandHandler("market", market, pass_args=True))
    dp.add_handler(CommandHandler("indicators", indicators))
    dp.add_handler(CommandHandler("indicator", indicator, pass_args=True))
    dp.add_handler(CommandHandler("unset", unset, pass_chat_data=True))
    dp.add_handler(CommandHandler("fibo", fibo, pass_args=True))
    dp.add_handler(CommandHandler("chart", chart, pass_args=True))

    # log all errors
    dp.add_error_handler(error)

    notifier.telegram_client.setup_bot(updater)

    # Start the Bot
    updater.start_polling()

    # Block until you press Ctrl-C or the process receives SIGINT, SIGTERM or
    # SIGABRT. This should be used most of the time, since start_polling() is
    # non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == '__main__':
    main()
