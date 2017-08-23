from __future__ import print_function
from time import time
from time import sleep
import logging
from operator import itemgetter
from pymongo import MongoClient
import pandas as pd
import numpy as np
import json, requests, re, multiprocessing, subprocess
from decimal import *
global buystr
global sellstr
logger = logging.getLogger(__name__)

# Please dont use this version... THANKS.. it does NOT work.
def rsi(df, window, targetcol='weightedAverage', colname='rsi'):
    """ Calculates the Relative Strength Index (RSI) from a pandas dataframe
    http://stackoverflow.com/a/32346692/3389859
    """
    series = df[targetcol]
    delta = series.diff().dropna()
    u = delta * 0
    d = u.copy()
    u[delta > 0] = delta[delta > 0]
    d[delta < 0] = -delta[delta < 0]
    # first value is sum of avg gains
    u[u.index[window - 1]] = np.mean(u[:window])
    u = u.drop(u.index[:(window - 1)])
    # first value is sum of avg losses
    d[d.index[window - 1]] = np.mean(d[:window])
    d = d.drop(d.index[:(window - 1)])
    rs = u.ewm(com=window - 1,
               ignore_na=False,
               min_periods=0,
               adjust=False).mean() / d.ewm(com=window - 1,
                                            ignore_na=False,
                                            min_periods=0,
                                            adjust=False).mean()
    df[colname] = 100 - 100 / (1 + rs)
    return df


def sma(df, window, targetcol='weightedAverage', colname='sma'):
    """ Calculates Simple Moving Average on a 'targetcol' in a pandas dataframe
    """
    df[colname] = df[targetcol].rolling(window=window, center=False).mean()
    return df


def ema(df, window, targetcol='weightedAverage', colname='ema', **kwargs):
    """ Calculates Expodential Moving Average on a 'targetcol' in a pandas
    dataframe """
    df[colname] = df[targetcol].ewm(
        span=window,
        min_periods=kwargs.get('min_periods', 1),
        adjust=kwargs.get('adjust', True),
        ignore_na=kwargs.get('ignore_na', False)
    ).mean()
    return df


def macd(df, fastcol='emafast', slowcol='emaslow', colname='macd'):
    """ Calculates the differance between 'fastcol' and 'slowcol' in a pandas
    dataframe """
    df[colname] = df[fastcol] - df[slowcol]
    return df


def bbands(df, window, targetcol='weightedAverage', stddev=2.0):
    """ Calculates Bollinger Bands for 'targetcol' of a pandas dataframe """
    if not 'sma' in df:
        df = sma(df, window, targetcol)
    df['bbtop'] = df['sma'] + stddev * df[targetcol].rolling(
        min_periods=window,
        window=window,
        center=False).std()
    df['bbbottom'] = df['sma'] - stddev * df[targetcol].rolling(
        min_periods=window,
        window=window,
        center=False).std()
    df['bbrange'] = df['bbtop'] - df['bbbottom']
    df['bbpercent'] = ((df[targetcol] - df['bbbottom']) / df['bbrange']) - 0.5
    return df


class Chart(object):
    """ Saves and retrieves chart data to/from mongodb. It saves the chart
    based on candle size, and when called, it will automaticly update chart
    data if needed using the timestamp of the newest candle to determine how
    much data needs to be updated """

    def __init__(self, api, pair, **kwargs):
        """
        api = poloniex api object
        pair = market pair
        period = time period of candles (default: 5 Min)
        """
        self.pair = pair
        self.api = api
        self.period = kwargs.get('period', self.api.MINUTE * 5)
        self.db = MongoClient()['poloniex']['%s_%s_chart' %
                                            (self.pair, str(self.period))]

    def __call__(self, size=0):
        """ Returns raw data from the db, updates the db if needed """
        # get old data from db
        old = sorted(list(self.db.find()), key=itemgetter('_id'))
        try:
            # get last candle
            last = old[-1]
        except:
            # no candle found, db collection is empty
            last = False
        # no entrys found, get last year of data to fill the db
        if not last:
            logger.warning('%s collection is empty!',
                           '%s_%s_chart' % (self.pair, str(self.period)))
            new = self.api.returnChartData(self.pair,
                                           period=self.period,
                                           start=time() - self.api.YEAR)
        # we have data in db already
        else:
            new = self.api.returnChartData(self.pair,
                                           period=self.period,
                                           start=int(last['_id']))
        # add new candles
        updateSize = len(new)
        logger.info('Updating %s with %s new entrys!',
                    self.pair + '-' + str(self.period), str(updateSize))
        # show progress
        for i in range(updateSize):
            print("\r%s/%s" % (str(i + 1), str(updateSize)), end=" complete ")
            date = new[i]['date']
            del new[i]['date']
            self.db.update_one({'_id': date}, {"$set": new[i]}, upsert=True)
        print('')
        logger.debug('Getting chart data from db')
        # return data from db
        return sorted(list(self.db.find()), key=itemgetter('_id'))[-size:]

    def dataFrame(self, size=0, window=120):
        # get data from db
        data = self.__call__(size)
        # make dataframe
        df = pd.DataFrame(data)
        # format dates
        df['date'] = [pd.to_datetime(c['_id'], unit='s') for c in data]
        # del '_id'
        del df['_id']
        # set 'date' col as index
        df.set_index('date', inplace=True)
        # calculate/add sma and bbands
        df = bbands(df, window)
        # add slow ema
        df = ema(df, window // 2, colname='emaslow')
        # add fast ema
        df = ema(df, window // 4, colname='emafast')
        # add macd
        df = macd(df)
        # add rsi
        df = rsi(df, window // 5)
        # add candle body and shadow size
        df['bodysize'] = df['open'] - df['close']
        df['shadowsize'] = df['high'] - df['low']
        # add percent change
        df['percentChange'] = df['close'].pct_change()
        return df
def run():
    while True:
        global buystr
        global sellstr
        # Below is the coin list, please follow its format... I choose coins with volume above 1000 daily.
        word_list = ["BTC_XRP", "BTC_ETH", "BTC_XMR", "BTC_BCH", "BTC_STR", "BTC_LTC", "BTC_DASH", "BTC_ETC", "BTC_STRAT", "BTC_BTS"]
        # Let's just use 5 for now... keeps things going quicker.
        for word in word_list:
            # initiate the data calculations
            df = Chart(api, word).dataFrame()
            df.dropna(inplace=False)
            data = (df.tail(2)[['macd']])
            #Turn Data into a string
            txt=str(data)
            print(data)
            # search for floats in the returned data
            re1='.*?'	# Non-greedy match on filler
            re2='([+-]?\\d*\\.\\d+)(?![-+0-9\\.])'	# Float 1
            re3='.*?'	# Non-greedy match on filler
            re4='([+-]?\\d*\\.\\d+)(?![-+0-9\\.])'	# Float 2
            rg = re.compile(re1+re2+re3+re4,re.IGNORECASE|re.DOTALL)
            m = rg.search(txt)
            # Search for floats that are too small to trade decision on
            re1='.*?'	# Non-greedy match on filler
            re2='([+-]?\\d*\\.\\d+)(?![-+0-9\\.])'	# Float 1
            re3='((?:[a-z][a-z0-9_]*))'	# Variable Name 1
            re4='([-+]\\d+)'	# Integer Number 1
            re5='.*?'	# Non-greedy match on filler
            re6='([+-]?\\d*\\.\\d+)(?![-+0-9\\.])'	# Float 2
            re7='((?:[a-z][a-z0-9_]*))'	# Variable Name 2
            re8='([-+]\\d+)'	# Integer Number 2
            rg = re.compile(re1+re2+re3+re4+re5+re6+re7+re8,re.IGNORECASE|re.DOTALL)
            deny = rg.search(txt)
            # Two if statements to decide what will happen... buy/sell/deny trade on limited data
            if m:
                if deny:
                    print(word + ' -- Percent changed too small to care')
                else:
                    # Set the floats from the data that are real numbers
                    float1=m.group(1)
                    float2=m.group(2)
                    float3 = float(float1)
                    float4 = float(float2)
                    # Calculate the difference in the two numbers
                    diff = Decimal(float(float4 - float3))
                    diffstr = str(diff)
                    if (Decimal(float3) == 0):
                        print(word + ' -- Not Enough Data On This Measurement')
                    elif (Decimal(float4) == 0):
                        print(word + ' -- Not Enough Data On This Measurement')
                    # If Macd is not positive, then sell
                    
                    elif (float4 > 0.000002):
                        print('Check 1 Reached - Macd is positive')
                        if (diff > 0.000002):
                            print('Check 2 Reached - Buying')
                            print(word, Decimal(float3), Decimal(float4))
                            print('Current diff is: ' + diffstr)
                            ke1=word.replace('BTC_', '')
                            ke3='-BTC'
                            ke8=ke1+ke3
                            buystr=ke8
                            print('Buying on Uptrend')
                            m = buy()
                            m.start()
                        elif (float4 < 0.000002):
                            print(word, Decimal(float3), Decimal(float4))
                            print('Current diff is: ' + diffstr)
                            ke1=word.replace('BTC_', '')
                            ke3='-BTC'
                            ke8=ke1+ke3
                            sellstr=ke8
                            print('Selling on Downtrend, macd less than 0.000002')
                            m = sell()
                            m.start()
                        elif (diff < 0.000002):
                            print(word, Decimal(float3), Decimal(float4))
                            print('Current diff is: ' + diffstr)
                            ke1=word.replace('BTC_', '')
                            ke3='-BTC'
                            ke8=ke1+ke3
                            sellstr=ke8
                            print('Selling on Downtrend, diff less than 0.000002')
                            m = sell()
                            m.start()
                    elif (float4 < 0.000002):
                        print(word, Decimal(float3), Decimal(float4))
                        print('Current diff is: ' + diffstr)
                        ke1=word.replace('BTC_', '')
                        ke3='-BTC'
                        ke8=ke1+ke3
                        sellstr=ke8
                        print('Selling on Downtrend, macd less than 0.000002')
                        m = sell()
                        m.start()
                    elif (diff < 0.000002):
                        print(word, Decimal(float3), Decimal(float4))
                        print('Current diff is: ' + diffstr)
                        ke1=word.replace('BTC_', '')
                        ke3='-BTC'
                        ke8=ke1+ke3
                        sellstr=ke8
                        print('Selling on Downtrend, diff less than 0.000002')
                        m = sell()
                        m.start()
                    else:
                        print(word, Decimal(float3), Decimal(float4))
                        print('Current diff is: ' + diffstr)
                        print('Waiting...')



def buy():
    return multiprocessing.Process(target = buybuy , args = ())
 
def buybuy():
    global buystr
    variable=str(buystr)
    variablestr=str(variable)
    print('Starting BUY Of: ' + variablestr + ' -- MACD Is Increasing')
    process1='./zenbot.sh buy --order_adjust_time=10000 --debug  poloniex.' + variablestr	
    subprocess.Popen(process1,shell=True)
def sell():
    return multiprocessing.Process(target = sellsell , args = ())
 
def sellsell():
    global sellstr
    variable=str(sellstr)
    variablestr=str(variable)
    print('Starting SELL Of: ' + variablestr + ' -- Macd Is Decreasing')
    process1='./zenbot.sh sell --order_adjust_time=10000 --debug  poloniex.' + variablestr	
    subprocess.Popen(process1,shell=True)

if __name__ == '__main__':
    from poloniex import Poloniex
    #logging.basicConfig(level=logging.DEBUG)
    #logging.getLogger("poloniex").setLevel(logging.INFO)
    #logging.getLogger('requests').setLevel(logging.ERROR)
    api = Poloniex(jsonNums=float)
    run()



    
