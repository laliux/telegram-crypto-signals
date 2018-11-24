
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

from apscheduler.schedulers.background import BackgroundScheduler

from telegram.ext import Updater, CommandHandler
from conf import Configuration
from exchange import ExchangeInterface
from notification import Notifier
from behaviour import Behaviour
from math import ceil

import concurrent.futures
import logs
import structlog
import copy

#To store config per user
users_config = dict()
users_market_data = dict()
users_exchanges = dict()
users_indicators = dict()

#New analysis results updated each 5min
new_results = dict()

# Load settings and create the config object
config = Configuration()
settings = config.settings

# Set up logger
logs.configure_logging(settings['log_level'], settings['log_mode'])
logger = structlog.get_logger()

update_interval = ceil(settings['update_interval'] / 60)
logger.info('udate interval %d ', update_interval)

config_indicators = config.indicators

# Configure and run configured behaviour.
exchange_interface = ExchangeInterface(config.exchanges)

if settings['market_pairs']:
    market_pairs = settings['market_pairs']
    logger.info("Found configured markets: %s", market_pairs)
    market_data = exchange_interface.get_exchange_markets(markets=market_pairs)
else:
    logger.info("No configured markets, using all available on exchange.")
    market_data = exchange_interface.get_exchange_markets()

#Dict to save user defined fibonacci levels
fibonacci = None

#Global Telegram Bot Updater
updater = None

# create schedule for retrieving prices
scheduler = BackgroundScheduler()


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
    
    global config, users_config, users_market_data, users_exchanges 
    global exchange_interface
    
    chat_id = update.message.chat_id
    user_id = 'usr_{}'.format(chat_id)
    
    logger.info('Starting chat with id: %s' % chat_id)
    
    if user_id not in users_config:
        users_config[user_id] = copy.deepcopy(config)
        #replace chat id
        users_config[user_id].notifiers['telegram']['required']['chat_id'] = chat_id
        users_config[user_id].notifiers['telegram']['required']['user_id'] = user_id
     
    users_config[user_id].exchanges = exchange_interface.get_default_exchanges()
    users_exchanges[user_id] = list(users_config[user_id].exchanges.keys())
    users_indicators[user_id] = get_user_indicators(users_config[user_id].indicators)
    
    logger.info('Users exchanges ... ')
    logger.info( users_exchanges[user_id] )
    
    logger.info('Users indicators ... ')
    logger.info( users_indicators[user_id] ) 
           
    if user_id not in users_market_data:
        users_market_data[user_id] = copy.deepcopy(market_data)
        
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
    update.message.reply_text('/exchanges to get a list of configured Exchanges')
    update.message.reply_text('/exchange to disable/enable an Exchange')    

def alarm(bot, job):
    
    global exchange_interface, fibonacci, new_results,  updater, logger
    global users_config, users_exchanges, users_market_data, users_indicators
    
    chat_id = job.context
    user_id = 'usr_{}'.format(chat_id)
    
    _market_data = users_market_data[user_id]
    _config = users_config[user_id]
        
    _notifier = Notifier(_config.notifiers, _market_data, _config.settings['enable_charts'])
    _notifier.telegram_client.set_updater(updater)
    

    #Getting custom results for each user
    messages = dict()
    
    for _exchange in _market_data:
        if _exchange in users_exchanges[user_id] :
            messages[_exchange] = dict()

            for _market_pair in _market_data[_exchange]:
                if len(new_results[_exchange][_market_pair]) > 0:
                    messages[_exchange][_market_pair] = copy.deepcopy(new_results[_exchange][_market_pair])

        if len(messages[_exchange]) > 0 :
            _notifier.notify_telegram(messages, users_indicators[user_id])


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
    global market_data, users_config
    
    chat_id = update.message.chat_id
    user_id = 'usr_{}'.format(chat_id)
    
    _market_data = users_market_data[user_id]
    _config = users_config[user_id]
    _notifier = Notifier(_config.notifiers, _market_data, _config.settings['enable_charts'])
    _notifier.telegram_client.set_updater(updater)    
    
    logger.info('Processing command for chat_id %s' % str(chat_id))

    try:
        exchange = args[0].strip().lower()
        market_pair = args[1].strip().upper()
        
        if market_pair in market_data[exchange]: 
            candle_period = args[2].strip().lower()

            _notifier.notify_telegram_chart(chat_id, exchange, market_pair, candle_period)
        else:
            update.message.reply_text('Market pair %s is not configured!' % market_pair)

    except (IndexError, ValueError) as err:
        logger.error('Error on chart() command... %s', err)
        update.message.reply_text('Usage: /chart <exchange> <market_pair> <candle_period>')
        update.message.reply_text('Usage: /chart binance xrp/usdt 4h')

def exchanges(bot, update):
    """ Return a list with the configured exchanges"""
    global users_config, users_exchanges
        
    chat_id = update.message.chat_id
    user_id = 'usr_{}'.format(chat_id)
    
    _exchanges = users_exchanges[user_id]
        
    update.message.reply_text('List of exchanges to analyze ... ')
    update.message.reply_text(str(_exchanges))
    
def exchange(bot, update, args):
    """ Enable/Disable an exchange """
    global users_config, users_exchanges
    
    chat_id = update.message.chat_id
    user_id = 'usr_{}'.format(chat_id)
    
    _exchanges = users_exchanges[user_id]
    
    try:
        operation = args[0]
        exchange = args[1].strip().lower()
        
        if operation == 'disable':
            if exchange in _exchanges:
                _exchanges.remove(exchange)
                update.message.reply_text('Exchange %s was disabled sucessfully!' % exchange)
                
                logger.info('Exchange %s disabled for user %s' % (exchange, user_id))
            else:
                update.message.reply_text('Exchange %s is not enable for you or doesnt exist!' % exchange)
            
        if operation == 'add':
            #Not implemeted
            update.message.reply_text('This operation only can be done for Bot Admin')
            
    except (IndexError, ValueError) as err:
        logger.error('Error on exchange() command... %s', err)
        update.message.reply_text('Usage: /exchange [add|remove/enable/disable] exchange_name')
        update.message.reply_text('For example: /exchange disable bitfinex')        
        
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
    global users_config, settings, exchange_interface
    
    #To store all exchanges/market_pairs to analyze
    global market_data
    
    #To store custom exchanges/market_pairs for each user
    global users_market_data
    
    chat_id = update.message.chat_id
    user_id = 'usr_{}'.format(chat_id) 
     
    _config = users_config[user_id]
    _settings  = _config.settings
    _exchanges = _config.exchanges
    
    #TODO: call get_default_exchange()
    exchange = 'binance'

    try:
        # args[0] is the operation to do
        operation = args[0]
        # args[1] should contain the name of market
        market_pair = ("%s/%s" % (args[1].strip(), args[2].strip())).upper()
        
                
        if operation == 'add':
            _settings['market_pairs'].append(market_pair)
            _market_data = exchange_interface.get_exchange_markets(
                                                    exchanges = _exchanges, 
                                                    markets = _settings['market_pairs']
                                                    )
            exists = False
            for _exchange in _market_data:
                for _pair in _market_data[_exchange]:
                    if(_pair in _market_data[_exchange]):
                        exists = True
                        break
                
            #Is a valid market pair
            if exists == True:
                users_market_data[user_id] = _market_data
                
                #Save user market pair in global config to be part of analysis
                if market_pair not in settings['market_pairs']:
                    settings['market_pairs'].append(market_pair)
                    
                    #by default takes global config.exchanges
                    market_data = exchange_interface.get_exchange_markets(markets=settings['market_pairs'])
            
                #TODO: fix it
                add_to_fibonnaci(exchange, market_pair)

                update.message.reply_text('%s successfully added!' % market_pair)
            else:
                _settings['market_pairs'].remove(market_pair)
                update.message.reply_text('%s doesnt exist on your exchanges %s!' % (market_pair, str(_exchanges)))
                return
                

        if operation == 'remove':
            
            if market_pair not in _settings['market_pairs']:
                update.message.reply_text('%s is not in your market pairs list.' % market_pair)
                
            _settings['market_pairs'].remove(market_pair)
            _market_data = exchange_interface.get_exchange_markets(markets=_settings['market_pairs'])
            
            users_market_data[user_id] = _market_data
            
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
    global users_indicators
    
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
            
            users_indicators[user_id] = get_user_indicators(_config.indicators)
            
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

def get_user_indicators(config_indicators):
    _indicators = dict()
    
    for _indicator in config_indicators:
        _indicators[_indicator] = list()
        for conf in config_indicators[_indicator]:
            if conf['enabled']:
                _indicators[_indicator].append(conf['candle_period'])
        
    return _indicators

def load_exchange(exchange):
    global config, market_data, fibonacci, new_results
           
    try:
        single_config = dict()
        single_config[exchange] = config.exchanges[exchange]
                
        single_exchange_interface = ExchangeInterface(single_config)
            
        single_market_data = dict()
        single_market_data[exchange] = market_data[exchange]
                
        behaviour = Behaviour(config, single_exchange_interface)
    
        new_result = behaviour.run(exchange, single_market_data, fibonacci, config.settings['output_mode'])
        
        new_results[exchange] = new_result[exchange]
        
        return True
    except Exception as exc:
        logger.info('Exception while processing exchange: %s', exchange)
        #logger.info('%s', exc)
        raise exc
        #return False
    
@scheduler.scheduled_job('interval', minutes=update_interval)
def load_exchanges():
    global market_data, new_results
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_exchange = {executor.submit(load_exchange, exchange): exchange for exchange in market_data}
        
        for future in concurrent.futures.as_completed(future_to_exchange):
            try:      
                exchange = future_to_exchange[future]
                          
                if (future.result() == True):
                    logger.info('New analysis results for: %s' % exchange )

            except Exception as exc:
                logger.info('Exception processing exchanges: %s' % (exc))
                raise exc

    
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
    dp.add_handler(CommandHandler("exchanges", exchanges))
    dp.add_handler(CommandHandler("exchange", exchange, pass_args=True))
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
    scheduler.start() 
    
    main()
    