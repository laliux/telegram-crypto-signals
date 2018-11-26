""" Runs the default analyzer, which performs two functions...
1. Output the signal information to the prompt.
2. Notify users when a threshold is crossed.
"""

import traceback
import structlog
import os

import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker

from matplotlib.dates import DateFormatter
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from copy import deepcopy
from ccxt import ExchangeError
from tenacity import RetryError
from jinja2 import Template

from stockstats import StockDataFrame
from analysis import StrategyAnalyzer
from outputs import Output
from analyzers.utils import IndicatorUtils
from analyzers.indicators.obv import OBV

class Behaviour(IndicatorUtils):
    """Default analyzer which gives users basic trading information.
    """

    def __init__(self, config, exchange_interface):
        """Initializes DefaultBehaviour class.

        Args:
            indicator_conf (dict): A dictionary of configuration for this analyzer.
            exchange_interface (ExchangeInterface): Instance of the ExchangeInterface class for
                making exchange queries.
        """

        self.logger = structlog.get_logger()
        self.indicator_conf = config.indicators
        self.informant_conf = config.informants
        self.crossover_conf = config.crossovers
        self.notifiers_conf = config.notifiers
        self.exchange_interface = exchange_interface
        self.strategy_analyzer = StrategyAnalyzer()
        
        self.all_historical_data = dict()
        self.last_analysis = dict()

        output_interface = Output()
        self.output = output_interface.dispatcher


    def run(self, exchange, market_data, fibonacci, output_mode):
        """The analyzer entrypoint

        Args:
            market_data (dict): Dict of exchanges and symbol pairs to operate on.
            fibonacci (dict): Dict with Fibonacci levels
            output_mode (str): Which console output mode to use.
        """

        self.logger.info("Starting default analyzer for %s ...", exchange)

        self.all_historical_data = self.get_all_historical_data(market_data)

        new_analysis = self._test_strategies(market_data, output_mode)
        
        template = self.notifiers_conf['telegram']['optional']['template']
        
        indicator_messages = self.get_indicator_messages(new_analysis, market_data, template)
        
        self._create_charts(exchange, indicator_messages, fibonacci)
        
        return indicator_messages

    def get_all_historical_data(self, market_data):
        """Get historical data for each exchange/market pair/candle period

        Args:
            market_data (dict): A dictionary containing the market data of the symbols to get data.
        """

        indicator_dispatcher = self.strategy_analyzer.indicator_dispatcher()
        data = dict()

        for exchange in market_data:
            self.logger.info("Getting candle data of %s", exchange)
            if exchange not in data:
                data[exchange] = dict()

            for market_pair in market_data[exchange]:
                if market_pair not in data[exchange]:
                    data[exchange][market_pair] = dict()

                for indicator in self.indicator_conf:
                    if indicator not in indicator_dispatcher:
                        self.logger.warn("No such indicator %s, skipping.", indicator)
                        continue

                    for indicator_conf in self.indicator_conf[indicator]:
                        if indicator_conf['enabled']:
                            candle_period = indicator_conf['candle_period']

                            if candle_period not in data[exchange][market_pair]:
                                candle_data = self._get_historical_data(market_pair, exchange, candle_period)
                                
                                if len(candle_data) == 0:
                                    self.logger.warn('No candle data for %s %s on %s', market_pair, candle_period, exchange)
                                    continue
                                    
                                data[exchange][market_pair][candle_period] = candle_data
        
        #Return after iterate all exchanges
        return data

    def _test_strategies(self, market_data, output_mode):
        """Test the strategies and perform notifications as required

        Args:
            market_data (dict): A dictionary containing the market data of the symbols to analyze.
            output_mode (str): Which console output mode to use.
        """

        new_result = dict()
        for exchange in market_data:
            
            if exchange not in new_result:
                new_result[exchange] = dict()

            for market_pair in market_data[exchange]:
                self.logger.info("Beginning analysis of %s on %s" % (market_pair, exchange))
                
                if market_pair not in new_result[exchange]:
                    new_result[exchange][market_pair] = dict()

                new_result[exchange][market_pair]['indicators'] = self._get_indicator_results(
                    exchange,
                    market_pair
                )

                new_result[exchange][market_pair]['informants'] = self._get_informant_results(
                    exchange,
                    market_pair
                )

                new_result[exchange][market_pair]['crossovers'] = self._get_crossover_results(
                    new_result[exchange][market_pair]
                )

                if output_mode in self.output:
                    output_data = deepcopy(new_result[exchange][market_pair])
                    print(
                        self.output[output_mode](output_data, market_pair),
                        end=''
                    )
                else:
                    self.logger.warn()

        # Print an empty line when complete
        print()
        return new_result


    def _get_indicator_results(self, exchange, market_pair):
        """Execute the indicator analysis on a particular exchange and pair.

        Args:
            exchange (str): The exchange to get the indicator results for.
            market_pair (str): The pair to get the market pair results for.

        Returns:
            list: A list of dictinaries containing the results of the analysis.
        """

        indicator_dispatcher = self.strategy_analyzer.indicator_dispatcher()
        results = { indicator: list() for indicator in self.indicator_conf.keys() }
        historical_data_cache = self.all_historical_data[exchange][market_pair]

        for indicator in self.indicator_conf:
            if indicator not in indicator_dispatcher:
                self.logger.warn("No such indicator %s, skipping.", indicator)
                continue

            for indicator_conf in self.indicator_conf[indicator]:
                if not indicator_conf['enabled']:
                    continue
                    
                candle_period = indicator_conf['candle_period']
                
                #Exchange doesnt support such candle period
                if candle_period not in historical_data_cache:
                    continue

                if historical_data_cache[candle_period]:
                    analysis_args = {
                        'historical_data': historical_data_cache[candle_period],
                        'signal': indicator_conf['signal'],
                        'hot_thresh': indicator_conf['hot'],
                        'cold_thresh': indicator_conf['cold']
                    }

                    if 'period_count' in indicator_conf:
                        analysis_args['period_count'] = indicator_conf['period_count']
                        
                    if indicator == 'rsi' and 'lrsi_filter' in indicator_conf:
                        analysis_args['lrsi_filter'] = indicator_conf['lrsi_filter']                        

                    results[indicator].append({
                        'result': self._get_analysis_result(
                            indicator_dispatcher,
                            indicator,
                            analysis_args,
                            market_pair
                        ),
                        'config': indicator_conf
                    })
        return results


    def _get_informant_results(self, exchange, market_pair):
        """Execute the informant analysis on a particular exchange and pair.

        Args:
            exchange (str): The exchange to get the indicator results for.
            market_pair (str): The pair to get the market pair results for.

        Returns:
            list: A list of dictinaries containing the results of the analysis.
        """

        informant_dispatcher = self.strategy_analyzer.informant_dispatcher()
        results = { informant: list() for informant in self.informant_conf.keys() }
        #historical_data_cache = dict()
        historical_data_cache = self.all_historical_data[exchange][market_pair]

        for informant in self.informant_conf:
            if informant not in informant_dispatcher:
                self.logger.warn("No such informant %s, skipping.", informant)
                continue

            for informant_conf in self.informant_conf[informant]:
                if not informant_conf['enabled']:
                    continue
                    
                candle_period = informant_conf['candle_period']
                
                #Exchange doesnt support such candle period
                if candle_period not in historical_data_cache:
                    continue

                if historical_data_cache[candle_period]:
                    analysis_args = {
                        'historical_data': historical_data_cache[candle_period]
                    }

                    if 'period_count' in informant_conf:
                        analysis_args['period_count'] = informant_conf['period_count']

                    results[informant].append({
                        'result': self._get_analysis_result(
                            informant_dispatcher,
                            informant,
                            analysis_args,
                            market_pair
                        ),
                        'config': informant_conf
                    })
        return results


    def _get_crossover_results(self, new_result):
        """Execute crossover analysis on the results so far.

        Args:
            new_result (dict): A dictionary containing the results of the informant and indicator
                analysis.

        Returns:
            list: A list of dictinaries containing the results of the analysis.
        """

        crossover_dispatcher = self.strategy_analyzer.crossover_dispatcher()
        results = { crossover: list() for crossover in self.crossover_conf.keys() }

        for crossover in self.crossover_conf:
            if crossover not in crossover_dispatcher:
                self.logger.warn("No such crossover %s, skipping.", crossover)
                continue

            for crossover_conf in self.crossover_conf[crossover]:
                if not crossover_conf['enabled']:
                    self.logger.debug("%s is disabled, skipping.", crossover)
                    continue

                key_indicator = new_result[crossover_conf['key_indicator_type']][crossover_conf['key_indicator']][crossover_conf['key_indicator_index']]
                crossed_indicator = new_result[crossover_conf['crossed_indicator_type']][crossover_conf['crossed_indicator']][crossover_conf['crossed_indicator_index']]

                dispatcher_args = {
                    'key_indicator': key_indicator['result'],
                    'key_signal': crossover_conf['key_signal'],
                    'key_indicator_index': crossover_conf['key_indicator_index'],
                    'crossed_indicator': crossed_indicator['result'],
                    'crossed_signal': crossover_conf['crossed_signal'],
                    'crossed_indicator_index': crossover_conf['crossed_indicator_index']
                }

                results[crossover].append({
                    'result': crossover_dispatcher[crossover](**dispatcher_args),
                    'config': crossover_conf
                })
        return results


    def _get_historical_data(self, market_pair, exchange, candle_period):
        """Gets a list of OHLCV data for the given pair and exchange.

        Args:
            market_pair (str): The market pair to get the OHLCV data for.
            exchange (str): The exchange to get the OHLCV data for.
            candle_period (str): The timeperiod to collect for the given pair and exchange.

        Returns:
            list: A list of OHLCV data.
        """

        historical_data = list()
        try:
            historical_data = self.exchange_interface.get_historical_data(
                market_pair,
                exchange,
                candle_period
            )
        except RetryError:
            self.logger.error(
                'Too many retries fetching information for pair %s, skipping',
                market_pair
            )
        except ExchangeError:
            self.logger.error(
                'Exchange supplied bad data for pair %s, skipping',
                market_pair
            )
        except ValueError as e:
            self.logger.error(e)
            self.logger.error(
                'Invalid data encountered while processing pair %s, skipping',
                market_pair
            )
            self.logger.debug(traceback.format_exc())
        except AttributeError:
            self.logger.error(
                'Something went wrong fetching data for %s, skipping',
                market_pair
            )
            self.logger.debug(traceback.format_exc())
        return historical_data


    def _get_analysis_result(self, dispatcher, indicator, dispatcher_args, market_pair):
        """Get the results of performing technical analysis

        Args:
            dispatcher (dict): A dictionary of functions for performing TA.
            indicator (str): The name of the desired indicator.
            dispatcher_args (dict): A dictionary of arguments to provide the analyser
            market_pair (str): The market pair to analyse

        Returns:
            pandas.DataFrame: Returns a pandas.DataFrame of results or an empty string.
        """

        try:
            results = dispatcher[indicator](**dispatcher_args)
        except TypeError:
            self.logger.info(
                'Invalid type encountered while processing pair %s for indicator %s, skipping',
                market_pair,
                indicator
            )
            self.logger.info(traceback.format_exc())
            results = str()
        return results

    def _create_charts(self, exchange, indicator_messages, fibonacci):
        """Create charts for each market_pair/candle_period

        Args:
            market_data (dict): A dictionary containing the market data of the symbols
        """
                
        charts_dir = './charts'

        if not os.path.exists(charts_dir):
            os.mkdir(charts_dir)

        for market_pair in indicator_messages[exchange]:
            
            candle_messages = indicator_messages[exchange][market_pair]
                               
            #indicators = new_analysis[exchange][market_pair]['indicators']
                        
            #OBV indicators
            #obv = dict()
            #for index, analysis in enumerate(indicators['obv']):
                #if analysis['result'].shape[0] == 0:
                    #continue
                
                #obv[analysis['config']['candle_period']] = analysis['result']          
            
            historical_data = self.all_historical_data[exchange][market_pair]

            fibonacci_levels = fibonacci[exchange][market_pair]

            for candle_period in candle_messages:
                if len(candle_messages[candle_period]) == 0:
                    continue

                candles_data = historical_data[candle_period]
                self.logger.info('Creating chart for %s %s %s', exchange, market_pair, candle_period)
                                   
                self._create_chart(exchange, market_pair, candle_period, candles_data, 
                                   fibonacci_levels, charts_dir)


    def _create_chart(self, exchange, market_pair, candle_period, candles_data, 
                      fibonacci_levels, charts_dir):

        df = self.convert_to_dataframe(candles_data)

        plt.rc('axes', grid=True)
        plt.rc('grid', color='#b0b0b0', linestyle='-', linewidth=0.2, alpha = 0.6)

        left, width = 0.1, 0.8
        rect1 = [left, 0.7, width, 0.25]
        rect2 = [left, 0.5, width, 0.2]
        rect3 = [left, 0.3, width, 0.2]
        rect4 = [left, 0.1, width, 0.2]
        
        fig = plt.figure(facecolor='white')
        fig.set_size_inches(10, 16, forward=True)
        axescolor = '#f6f6f6'  # the axes background color

        ax1 = fig.add_axes(rect1, facecolor=axescolor)  # left, bottom, width, height
        ax2 = fig.add_axes(rect2, facecolor=axescolor, sharex=ax1)
        ax3 = fig.add_axes(rect3, facecolor=axescolor, sharex=ax1)
        ax4 = fig.add_axes(rect4, facecolor=axescolor, sharex=ax1)

        if fibonacci_levels['0.00'] > 0 and fibonacci_levels['0.00'] > fibonacci_levels['100.00']:
            ax1.axhline(fibonacci_levels['0.00'], color='steelblue', linestyle='-', alpha=0.3)
            ax1.axhspan(fibonacci_levels['23.60'], fibonacci_levels['0.00'], alpha=0.2, color='steelblue')
            ax1.axhspan(fibonacci_levels['38.20'], fibonacci_levels['23.60'], alpha=0.3, color='steelblue')
            ax1.axhspan(fibonacci_levels['50.00'], fibonacci_levels['38.20'], alpha=0.2, color='steelblue')
            ax1.axhspan(fibonacci_levels['61.80'], fibonacci_levels['50.00'], alpha=0.3, color='steelblue')
            ax1.axhspan(fibonacci_levels['78.60'], fibonacci_levels['61.80'], alpha=0.2, color='steelblue')
            ax1.axhspan(fibonacci_levels['100.00'], fibonacci_levels['78.60'], alpha=0.3, color='steelblue')
        
        #Plot Candles chart
        self.plot_candlestick(ax1, df, candle_period)

        #Plot RSI (14)
        self.plot_rsi(ax2, df)

        #Plot OBV indicator with data of last analysis
        #if candle_period in obv :
        self.plot_obv(ax3, candles_data, candle_period)
            
        # Calculate and plot MACD       
        self.plot_macd(ax4, df, candle_period)
        

        for ax in ax1, ax2, ax3, ax4:
            if ax != ax4:
                for label in ax.get_xticklabels():
                    label.set_visible(False)
            else:
                for label in ax.get_xticklabels():
                    label.set_rotation(30)
                    label.set_horizontalalignment('right')

            ax.xaxis.set_major_locator(mticker.MaxNLocator(10))
            ax.xaxis.set_major_formatter(DateFormatter('%d/%b'))
            ax.xaxis.set_tick_params(which='major', pad=15) 

        fig.autofmt_xdate()

        title = '{} {} {}'.format(exchange, market_pair, candle_period).upper()
        fig.suptitle(title, fontsize=14)

        market_pair = market_pair.replace('/', '_').lower()
        chart_file = '{}/{}_{}_{}.png'.format(charts_dir, exchange, market_pair, candle_period)

        plt.savefig(chart_file)
        plt.close(fig)

    def candlestick_ohlc(self, ax, quotes, width=0.2, colorup='k', colordown='r',
                    alpha=1.0, ochl=False):
        """
        Plot the time, open, high, low, close as a vertical line ranging
        from low to high.  Use a rectangular bar to represent the
        open-close span.  If close >= open, use colorup to color the bar,
        otherwise use colordown

        Parameters
        ----------
        ax : `Axes`
            an Axes instance to plot to
        quotes : sequence of quote sequences
            data to plot.  time must be in float date format - see date2num
            (time, open, high, low, close, ...) vs
            (time, open, close, high, low, ...)
            set by `ochl`
        width : float
            fraction of a day for the rectangle width
        colorup : color
            the color of the rectangle where close >= open
        colordown : color
            the color of the rectangle where close <  open
        alpha : float
            the rectangle alpha level
        ochl: bool
            argument to select between ochl and ohlc ordering of quotes

        Returns
        -------
        ret : tuple
            returns (lines, patches) where lines is a list of lines
            added and patches is a list of the rectangle patches added

        """

        OFFSET = width / 2.0

        lines = []
        patches = []
        for q in quotes:
            if ochl:
                t, open, close, high, low = q[:5]
            else:
                t, open, high, low, close = q[:5]

            if close >= open:
                color = colorup
                lower = open
                height = close - open
            else:
                color = colordown
                lower = close
                height = open - close

            vline = Line2D(
                xdata=(t, t), ydata=(low, high),
                color=color,
                linewidth=0.5,
                antialiased=False,
            )

            rect = Rectangle(
                xy=(t - OFFSET, lower),
                width=width,
                height=height,
                facecolor=color,
                edgecolor=None,
                antialiased=False,
                alpha=1.0
            )

            lines.append(vline)
            patches.append(rect)
            ax.add_line(vline)
            ax.add_patch(rect)

        ax.autoscale_view()

        return lines, patches

    def plot_candlestick(self, ax, df, candle_period):
        textsize = 11

        _time = mdates.date2num(df.index.to_pydatetime())
        min_x = np.nanmin(_time)
        max_x = np.nanmax(_time)

        stick_width = ((max_x - min_x) / _time.size ) 

        prices = df["close"]

        ax.set_ymargin(0.2)
        ax.ticklabel_format(axis='y', style='plain')

        self.candlestick_ohlc(ax, zip(_time, df['open'], df['high'], df['low'], df['close']),
                    width=stick_width, colorup='olivedrab', colordown='crimson')
                    
        ma25 = self.moving_average(prices, 25, type='simple')
        ma7 = self.moving_average(prices, 7, type='simple')

        ax.plot(df.index, ma25, color='indigo', lw=0.6, label='MA (25)')
        ax.plot(df.index, ma7, color='orange', lw=0.6, label='MA (7)')
    
        ax.text(0.04, 0.94, 'MA (7, close, 0)', color='orange', transform=ax.transAxes, fontsize=textsize, va='top')
        ax.text(0.24, 0.94, 'MA (25, close, 0)', color='indigo', transform=ax.transAxes,  fontsize=textsize, va='top')

    def plot_rsi(self, ax, df):
        textsize = 11
        fillcolor = 'darkmagenta'

        rsi = self.relative_strength(df["close"])

        ax.plot(df.index, rsi, color=fillcolor, linewidth=0.5)
        ax.axhline(70, color='darkmagenta', linestyle='dashed', alpha=0.6)
        ax.axhline(30, color='darkmagenta', linestyle='dashed', alpha=0.6)
        ax.fill_between(df.index, rsi, 70, where=(rsi >= 70),
                        facecolor=fillcolor, edgecolor=fillcolor)
        ax.fill_between(df.index, rsi, 30, where=(rsi <= 30),
                        facecolor=fillcolor, edgecolor=fillcolor)
        ax.set_ylim(0, 100)
        ax.set_yticks([30, 70])
        ax.text(0.024, 0.94, 'RSI (14)', va='top',transform=ax.transAxes, fontsize=textsize)

    def plot_macd(self, ax, df, candle_period):
        textsize = 11

        df = StockDataFrame.retype(df)
        df['macd'] = df.get('macd')

        min_y = df.macd.min()
        max_y = df.macd.max()

        #Reduce Macd Histogram values to have a better visualization
        macd_h = df.macdh * 0.5

        if (macd_h.min() < min_y):
            min_y = macd_h.min()

        if (macd_h.max() > max_y):
            max_y = macd_h.max() 

        #Adding some extra space at bottom/top
        min_y = min_y * 1.2
        max_y = max_y * 1.2

        #Define candle bar width
        _time = mdates.date2num(df.index.to_pydatetime())
        min_x = np.nanmin(_time)
        max_x = np.nanmax(_time)

        bar_width = ((max_x - min_x) / _time.size ) * 0.8            

        ax.bar(x=_time, bottom=[0 for _ in macd_h.index], height=macd_h, width=bar_width, color="red", alpha = 0.4)
        ax.plot(_time, df.macd, color='blue', lw=0.6)
        ax.plot(_time, df.macds, color='red', lw=0.6)
        ax.set_ylim((min_y, max_y))
    
        ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5, prune='upper'))
        ax.text(0.024, 0.94, 'MACD (12, 26, close, 9)', va='top', transform=ax.transAxes, fontsize=textsize)  

    def plot_obv(self, ax, candles_data, candle_period):
        
        obv_df = OBV().analyze(candles_data)
        
        textsize = 11

        min_y = obv_df.obv.min()
        max_y = obv_df.obv.max()

        #Adding some extra space at bottom/top
        min_y = min_y * 1.2
        max_y = max_y * 1.2
      
        _time = mdates.date2num(obv_df.index.to_pydatetime())
      
        ax.plot(_time, obv_df.obv, color='blue', lw=0.6)
        
        ax.set_ylim((min_y, max_y))
    
        ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5, prune='upper'))
        ax.text(0.024, 0.94, 'OBV', va='top', transform=ax.transAxes, fontsize=textsize)
        
    def relative_strength(self, prices, n=14):
        """
        compute the n period relative strength indicator
        http://stockcharts.com/school/doku.php?id=chart_school:glossary_r#relativestrengthindex
        http://www.investopedia.com/terms/r/rsi.asp
        """

        deltas = np.diff(prices)
        seed = deltas[:n + 1]
        up = seed[seed >= 0].sum() / n
        down = -seed[seed < 0].sum() / n
        rs = up / down
        rsi = np.zeros_like(prices)
        rsi[:n] = 100. - 100. / (1. + rs)

        for i in range(n, len(prices)):
            delta = deltas[i - 1]  # cause the diff is 1 shorter

            if delta > 0:
                upval = delta
                downval = 0.
            else:
                upval = 0.
                downval = -delta

            up = (up * (n - 1) + upval) / n
            down = (down * (n - 1) + downval) / n

            rs = up / down
            rsi[i] = 100. - 100. / (1. + rs)

        return rsi


    def moving_average(self, x, n, type='simple'):
        """
        compute an n period moving average.

        type is 'simple' | 'exponential'

        """
        x = np.asarray(x)
        if type == 'simple':
            weights = np.ones(n)
        else:
            weights = np.exp(np.linspace(-1., 0., n))

        weights /= weights.sum()

        a = np.convolve(x, weights, mode='full')[:len(x)]
        a[:n] = a[n]
        return a

    def get_indicator_messages(self, new_analysis, market_data, template):
        """Creates a message list from a user defined template

        Args:
            new_analysis (dict): A dictionary of data related to the analysis to send a message about.
            template (str): A Jinja formatted message template.

        Returns:
            list: A list with the templated messages for the notifier.
        """

        if not self.last_analysis:
            self.last_analysis = new_analysis

        message_template = Template(template)

        new_messages = dict()
        ohlcv_values = dict()
        lrsi_values = dict()

        for exchange in new_analysis:
            
            new_messages[exchange] = dict()
            ohlcv_values[exchange] = dict()
            lrsi_values[exchange] = dict()

            for market_pair in new_analysis[exchange]:

                new_messages[exchange][market_pair] = dict()
                ohlcv_values[exchange][market_pair] = dict()
                lrsi_values[exchange][market_pair] = dict()

                #Getting price values for each market pair and candle period
                for indicator_type in new_analysis[exchange][market_pair]:
                    if indicator_type == 'informants':
                        for index, analysis in enumerate(new_analysis[exchange][market_pair]['informants']['ohlcv']):
                            values = dict()
                            for signal in analysis['config']['signal']:
                                values[signal] = analysis['result'].iloc[-1][signal]
                                ohlcv_values[exchange][market_pair][analysis['config']['candle_period']] = values

                        for index, analysis in enumerate(new_analysis[exchange][market_pair]['informants']['lrsi']):
                            values = dict()
                            for signal in analysis['config']['signal']:
                                values[signal] = analysis['result'].iloc[-1][signal]
                            
                            lrsi_values[exchange][market_pair][analysis['config']['candle_period']] = values                                

                for indicator_type in new_analysis[exchange][market_pair]:
                    if indicator_type == 'informants':
                        continue

                    for indicator in new_analysis[exchange][market_pair][indicator_type]:
                        for index, analysis in enumerate(new_analysis[exchange][market_pair][indicator_type][indicator]):
                            if analysis['result'].shape[0] == 0:
                                continue

                            values = dict()
                            if 'candle_period' in analysis['config']:
                                candle_period = analysis['config']['candle_period']
                                new_messages[exchange][market_pair][candle_period] = list()

                            if indicator_type == 'indicators':                                
                                #Check for any user config
                                #if candle_period not in user_indicators[indicator]:
                                    #self.logger.info('###Skipping %s %s ' % (indicator, candle_period))
                                    #continue
                                
                                for signal in analysis['config']['signal']:
                                    latest_result = analysis['result'].iloc[-1]

                                    values[signal] = analysis['result'].iloc[-1][signal]
                                    if isinstance(values[signal], float):
                                        values[signal] = format(values[signal], '.2f')
                            elif indicator_type == 'crossovers':
                                latest_result = analysis['result'].iloc[-1]

                                key_signal = '{}_{}'.format(
                                    analysis['config']['key_signal'],
                                    analysis['config']['key_indicator_index']
                                )

                                crossed_signal = '{}_{}'.format(
                                    analysis['config']['crossed_signal'],
                                    analysis['config']['crossed_indicator_index']
                                )

                                values[key_signal] = analysis['result'].iloc[-1][key_signal]
                                if isinstance(values[key_signal], float):
                                        values[key_signal] = format(values[key_signal], '.2f')

                                values[crossed_signal] = analysis['result'].iloc[-1][crossed_signal]
                                if isinstance(values[crossed_signal], float):
                                        values[crossed_signal] = format(values[crossed_signal], '.2f')

                            status = 'neutral'
                            if latest_result['is_hot']:
                                status = 'hot'
                            elif latest_result['is_cold']:
                                status = 'cold'

                            # Save status of indicator's new analysis
                            new_analysis[exchange][market_pair][indicator_type][indicator][index]['status'] = status

                            if latest_result['is_hot'] or latest_result['is_cold']:
                                try:
                                    last_status = self.last_analysis[exchange][market_pair][indicator_type][indicator][index]['status']
                                except:
                                    last_status = str()

                                should_alert = True

                                if analysis['config']['alert_frequency'] == 'once':
                                    if last_status == status:
                                        should_alert = False

                                if not analysis['config']['alert_enabled']:
                                    should_alert = False

                                if should_alert:
                                    base_currency, quote_currency = market_pair.split('/')
                                    precision = market_data[exchange][market_pair]['precision']
                                    decimal_format = '.{}f'.format(precision['price'])

                                    candle_period = analysis['config']['candle_period']

                                    prices = ''
                                    candle_values = ohlcv_values[exchange][market_pair]

                                    if candle_period in candle_values :
                                        for key, value in candle_values[candle_period].items():
                                            value = format(value, decimal_format)
                                            prices = '{} {}: {}' . format(prices, key.title(), value)   

                                    lrsi = ''
                                    if candle_period in lrsi_values[exchange][market_pair]:
                                        lrsi = lrsi_values[exchange][market_pair][candle_period]['lrsi']

                                    new_message = message_template.render(
                                        values=values, exchange=exchange, market=market_pair, base_currency=base_currency,
                                        quote_currency=quote_currency, indicator=indicator, indicator_number=index,
                                        analysis=analysis, status=status, last_status=last_status, 
                                        prices=prices, lrsi=lrsi)

                                    new_messages[exchange][market_pair][candle_period].append(new_message)

        # Merge changes from new analysis into last analysis
        self.last_analysis = {**self.last_analysis, **new_analysis}
        return new_messages