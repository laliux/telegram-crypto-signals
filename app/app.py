
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
import copy

#To store config per each user
users_config = dict()
markets_data = dict()

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

#Global Telegram Bot Updater
updater = None


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

def start(bot, update):    
    """Mainly used to set a general config per user."""
    
    global config, users_config, markets_data
    
    chat_id = update.message.chat_id
    user_id = 'usr_{}'.format(chat_id)
    
    logger.info('Starting chat with id: %s' % chat_id)
    
    if user_id not in users_config:
        users_config[user_id] = copy.deepcopy(config)
        #replace chat id
        users_config[user_id].notifiers['telegram']['required']['chat_id'] = chat_id
        users_config[user_id].notifiers['telegram']['required']['user_id'] = user_id
            
    if user_id not in markets_data:
        markets_data[user_id] = copy.deepcopy(market_data)
        
    update.message.reply_text('Hi! Welcome to Crypto Signals Bot')
    update.message.reply_text('Dont forget to set the update interval. Type /help for more info.')
        

def help(bot, update):
    update.message.reply_text('Available commands:')
    update.message.reply_text('/timeout to set the update interval')
    update.message.reply_text('/unset to reset the timeout value - removes timer.')
    update.message.reply_text('/markets to get a list of market pairs')
    update.message.reply_text('/market to add or remove a market pair')
    update.message.reply_text('/indicators to get a list of configured indicators')
    update.message.reply_text('/indicator to disable/enable an indicator')

def alarm(bot, job):
    
    global exchange_interface, markets_data, fibonacci
    global users_config, updater
    
    chat_id = job.context
    user_id = 'usr_{}'.format(chat_id)
    
    _market_data = markets_data[user_id]
    _config = users_config[user_id]
    _notifier = Notifier(_config.notifiers, _market_data)
    _notifier.telegram_client.set_updater(updater)
    
    logger.info('Processing alarm() for user_id: %s' % user_id)

    behaviour = Behaviour(
            _config,
            exchange_interface,
            _notifier
        )

    behaviour.run(_market_data, fibonacci, _config.settings['output_mode'])

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
    
    chat_id = update.message.chat_id
    
    logger.info('Processing command for chat_id %s' % str(chat_id))

    try:
        # args[0] should contain the name of market
        market_pair = ("%s/USDT" % args[0].strip()).upper()

        if market_pair in market_data['binance']: 
            candle_period = args[1]

            notifier.notify_telegram_chart(chat_id, 'binance', market_pair, candle_period)
        else:
            update.message.reply_text('Market pair %s is not configured!' % market_pair)

    except (IndexError, ValueError) as err:
        logger.error('Error on chart() command... %s', err)
        update.message.reply_text('Usage: /chart <market_pair> <candle_period>')

def markets(bot, update):
    """ Return a list with the configured market pairs"""
    global users_config
        
    chat_id = update.message.chat_id
    user_id = 'usr_{}'.format(chat_id)
    
    _market_pairs = users_config[user_id].settings['market_pairs']
        
    update.message.reply_text('List of market pairs to analyze ... ')
    update.message.reply_text(str(_market_pairs))
    
def market(bot, update, args):
    """Add/Remove a marker pair."""
    global markets_data, users_config
    
    chat_id = update.message.chat_id
    user_id = 'usr_{}'.format(chat_id)    
    _config = users_config[user_id]
    _settings = _config.settings   
    
    #TODO: call get_default_exchange()
    exchange = 'binance'

    try:
        # args[0] is the operation to do
        operation = args[0]
        # args[1] should contain the name of market
        market_pair = ("%s/%s" % (args[1].strip(), args[2].strip())).upper()
        
                
        if operation == 'add':
            _settings['market_pairs'].append(market_pair)
            _market_data = exchange_interface.get_exchange_markets(markets=_settings['market_pairs'])
            
            if market_pair not in _market_data[exchange]:
                _settings['market_pairs'].remove(market_pair)
                update.message.reply_text('%s doesnt exist on %s!' % (market_pair, exchange))
                return
            else:
                markets_data[user_id] = _market_data
            
            add_to_fibonnaci(exchange, market_pair)

            update.message.reply_text('%s successfully added!' % market_pair)

        if operation == 'remove':
            
            if market_pair not in _settings['market_pairs']:
                update.message.reply_text('%s is not in your market pairs list.' % market_pair)
                
            _settings['market_pairs'].remove(market_pair)
            _market_data = exchange_interface.get_exchange_markets(markets=_settings['market_pairs'])
            markets_data[user_id] = _market_data
            
            update.message.reply_text('%s successfully removed!' % market_pair)

    except (IndexError, ValueError) as err:
        logger.error('Error on market() command... %s', err)
        update.message.reply_text('Usage: /market <add|remove> symbol base_market')
        update.message.reply_text('For example: /market add btc usdt')

def indicators(bot, update):
    """ Display enabled indicators """
    
    chat_id = update.message.chat_id
    user_id = 'usr_{}'.format(chat_id)
    
    _config = users_config[user_id]
        
    update.message.reply_text('Configured indicators ... ')

    for indicator in _config.indicators:
        msg = indicator

        for conf in _config.indicators[indicator] :
            if conf['enabled']:
                msg = '%s %s' % (msg, conf['candle_period'])

        if msg != indicator :
            update.message.reply_text(msg)

def indicator(bot, update, args):
    """ Manage indicators """
    
    chat_id = update.message.chat_id
    user_id = 'usr_{}'.format(chat_id)
    
    _config = users_config[user_id]
        
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

            for idx, conf in enumerate(_config.indicators[indicator]) :
                if conf['candle_period'] == candle_period:
                    _config.indicators[indicator][idx]['enabled'] = enabled
            
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
        
        job_id = 'job_{}'.format(chat_id)
        chat_data[job_id] = job

        update.message.reply_text('Timeout successfully set to %d!' % due)

    except (IndexError, ValueError):
        update.message.reply_text('Usage: /timeout <seconds>')


def unset(bot, update, chat_data):
    """Remove the job if the user changed their mind."""
    
    chat_id = update.message.chat_id
    job_id = 'job_{}'.format(chat_id)
    
    if job_id not in chat_data:
        update.message.reply_text('You have no active timer')
        return

    job = chat_data[job_id]
    job.schedule_removal()
    del chat_data[job_id]

    update.message.reply_text('Timer successfully unset!')


def error(bot, update, error):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, error)


def main():
    global market_data, updater

    setup_fibonacci(market_data)

    """Run bot."""
    updater = Updater(config.notifiers['telegram']['required']['token'])

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # on different commands - answer in Telegram
    dp.add_handler(CommandHandler("start", start))
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

    

    # Start the Bot
    updater.start_polling()

    # Block until you press Ctrl-C or the process receives SIGINT, SIGTERM or
    # SIGABRT. This should be used most of the time, since start_polling() is
    # non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == '__main__':
    main()
