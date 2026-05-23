"""
技术指标计算
RSI, MACD, KDJ, Bollinger Bands, MA
"""

import pandas as pd
import numpy as np


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return rsi.fillna(50)


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9) -> dict:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = (dif - dea) * 2
    return {'DIF': dif, 'DEA': dea, 'MACD': macd}


def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series,
             n=9, m1=3, m2=3) -> dict:
    lowest = low.rolling(n).min()
    highest = high.rolling(n).max()
    rsv = (close - lowest) / (highest - lowest) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    return {'K': k, 'D': d, 'J': j}


def calc_bollinger(close: pd.Series, period=20, std_dev=2) -> dict:
    middle = close.rolling(period).mean()
    std = close.rolling(period).std()
    return {
        'upper': middle + std_dev * std,
        'middle': middle,
        'lower': middle - std_dev * std,
    }


def calc_ma(close: pd.Series, periods=(5, 10, 20, 60)) -> dict:
    return {f'MA{p}': close.rolling(p).mean() for p in periods}


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    给 OHLCV DataFrame 添加常用技术指标列
    """
    result = df.copy()
    close = df['close']
    high = df['high']
    low = df['low']

    # MA
    for p in [5, 10, 20, 60]:
        result[f'sma{p}'] = close.rolling(p).mean()

    # MACD
    macd = calc_macd(close)
    result['macd'] = macd['DIF']
    result['macd_signal'] = macd['DEA']
    result['macd_hist'] = macd['MACD']

    # RSI
    result['rsi'] = calc_rsi(close)

    # KDJ
    kdj = calc_kdj(high, low, close)
    result['k'] = kdj['K']
    result['d'] = kdj['D']
    result['j'] = kdj['J']

    # Bollinger
    boll = calc_bollinger(close)
    result['boll_upper'] = boll['upper']
    result['boll_middle'] = boll['middle']
    result['boll_lower'] = boll['lower']

    return result
