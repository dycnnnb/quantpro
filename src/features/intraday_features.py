"""
五分钟线日内特征工程
策略专用：开盘/收盘噪声过滤 + 防跨日污染
"""

import pandas as pd
import numpy as np
from typing import Optional
from .base import BaseFeature
import logging

logger = logging.getLogger(__name__)


class IntradayFeatureEngineer(BaseFeature):
    """五分钟线特征工程"""

    OPEN_FILTER_MINUTES = 30
    CLOSE_FILTER_MINUTES = 15

    def __init__(self, config: dict = None):
        super().__init__()
        self.config = config or {}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df = self._parse_time(df)
        df = self._filter_time(df)
        df = df.groupby(df['date'], group_keys=False).apply(self._build_single_day)
        df = df.dropna()
        logger.info(f"特征构建完成，有效数据量: {len(df)}")
        return df

    def _parse_time(self, df: pd.DataFrame) -> pd.DataFrame:
        df['time'] = pd.to_datetime(df['time'])
        df['date'] = df['time'].dt.date
        df['hour'] = df['time'].dt.hour
        df['minute'] = df['time'].dt.minute
        df['minutes_from_open'] = (
            (df['hour'] - 9) * 60 + df['minute'] - 30
        ).clip(lower=0)
        return df

    def _filter_time(self, df: pd.DataFrame) -> pd.DataFrame:
        time_str = df['time'].dt.strftime('%H:%M')
        morning = (time_str >= "10:00") & (time_str <= "11:15")
        afternoon = (time_str >= "13:05") & (time_str <= "14:45")
        df = df[morning | afternoon].copy()
        return df

    def _build_single_day(self, day_df: pd.DataFrame) -> pd.DataFrame:
        day_df = day_df.copy().reset_index(drop=True)
        day_df = self._price_features(day_df)
        day_df = self._volume_features(day_df)
        day_df = self._momentum_features(day_df)
        day_df = self._volatility_features(day_df)
        day_df = self._microstructure_features(day_df)
        day_df = self._pattern_features(day_df)
        return day_df

    def _price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        c, h, l, o = df['close'], df['high'], df['low'], df['open']

        for period in [5, 10, 20, 30, 60]:
            df[f'ma{period}'] = c.rolling(period).mean()
            df[f'ma{period}_dist'] = (c - df[f'ma{period}']) / df[f'ma{period}']

        df['ma5_slope'] = df['ma5'].diff(3) / df['ma5'].shift(3)
        df['ma20_slope'] = df['ma20'].diff(5) / df['ma20'].shift(5)

        df['ma_rank_score'] = (
            (df['ma5'] > df['ma10']).astype(int) +
            (df['ma10'] > df['ma20']).astype(int) +
            (df['ma20'] > df['ma60']).astype(int)
        )

        df['body'] = abs(c - o)
        df['body_ratio'] = df['body'] / (h - l + 1e-8)
        df['upper_shadow'] = h - df[['close', 'open']].max(axis=1)
        df['lower_shadow'] = df[['close', 'open']].min(axis=1) - l
        df['shadow_ratio'] = df['upper_shadow'] / (df['body'] + 1e-8)

        day_open = df['open'].iloc[0]
        df['intraday_return'] = (c - day_open) / day_open

        for lag in [1, 2, 3, 5, 10]:
            df[f'ret_{lag}'] = c.pct_change(lag)

        return df

    def _volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        v, c = df['volume'], df['close']

        df['vol_ma5'] = v.rolling(5).mean()
        df['vol_ma20'] = v.rolling(20).mean()
        df['vol_ratio_5'] = v / (df['vol_ma5'] + 1)
        df['vol_ratio_20'] = v / (df['vol_ma20'] + 1)

        df['price_vol_corr'] = c.rolling(10).corr(v)

        df['cum_vol'] = v.cumsum()
        df['cum_vol_ratio'] = df['cum_vol'] / (df['cum_vol'].max() + 1)

        direction = np.sign(c.diff()).fillna(0)
        df['obv'] = (v * direction).cumsum()
        df['obv_ma'] = df['obv'].rolling(10).mean()
        df['obv_dist'] = (df['obv'] - df['obv_ma']) / (df['obv_ma'].abs() + 1)

        df['money_flow'] = (
            (c - df['low']) - (df['high'] - c)
        ) / (df['high'] - df['low'] + 1e-8) * v
        df['mf_ratio'] = (
            df['money_flow'].rolling(10).sum() /
            (v.rolling(10).sum() + 1)
        )

        return df

    def _momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        c = df['close']

        for period in [6, 14]:
            delta = c.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.ewm(span=period, adjust=False).mean()
            avg_loss = loss.ewm(span=period, adjust=False).mean()
            rs = avg_gain / (avg_loss + 1e-8)
            df[f'rsi{period}'] = 100 - 100 / (1 + rs)

        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        df['macd_hist_change'] = df['macd_hist'].diff()

        low_n = df['low'].rolling(9).min()
        high_n = df['high'].rolling(9).max()
        rsv = (c - low_n) / (high_n - low_n + 1e-8) * 100
        df['kdj_k'] = rsv.ewm(com=2, adjust=False).mean()
        df['kdj_d'] = df['kdj_k'].ewm(com=2, adjust=False).mean()
        df['kdj_j'] = 3 * df['kdj_k'] - 2 * df['kdj_d']

        tp = (df['high'] + df['low'] + c) / 3
        ma_tp = tp.rolling(14).mean()
        md = tp.rolling(14).apply(lambda x: np.abs(x - x.mean()).mean())
        df['cci'] = (tp - ma_tp) / (0.015 * md + 1e-8)

        high14 = df['high'].rolling(14).max()
        low14 = df['low'].rolling(14).min()
        df['williams_r'] = -100 * (high14 - c) / (high14 - low14 + 1e-8)

        return df

    def _volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        c = df['close']

        prev_c = c.shift(1)
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - prev_c).abs(),
            (df['low'] - prev_c).abs()
        ], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_pct'] = df['atr'] / c

        bb_mid = c.rolling(20).mean()
        bb_std = c.rolling(20).std()
        df['bb_upper'] = bb_mid + 2 * bb_std
        df['bb_lower'] = bb_mid - 2 * bb_std
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / (bb_mid + 1e-8)
        df['bb_pos'] = (c - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-8)

        for period in [5, 10, 20]:
            df[f'hvol_{period}'] = c.pct_change().rolling(period).std() * np.sqrt(period)

        return df

    def _microstructure_features(self, df: pd.DataFrame) -> pd.DataFrame:
        c, h, l = df['close'], df['high'], df['low']

        high20 = h.rolling(20).max()
        low20 = l.rolling(20).min()
        df['price_position_20'] = (c - low20) / (high20 - low20 + 1e-8)

        high60 = h.rolling(60).max()
        low60 = l.rolling(60).min()
        df['price_position_60'] = (c - low60) / (high60 - low60 + 1e-8)

        df['break_high20'] = (c > high20.shift(1)).astype(int)
        df['break_low20'] = (c < low20.shift(1)).astype(int)

        direction = np.sign(c.diff())
        consecutive = []
        count = 0
        prev = 0
        for d in direction:
            if d == prev and d != 0:
                count += 1
            else:
                count = 1
                prev = d
            consecutive.append(count * d)
        df['consecutive_bars'] = consecutive

        return df

    def _pattern_features(self, df: pd.DataFrame) -> pd.DataFrame:
        c, o, h, l = df['close'], df['open'], df['high'], df['low']

        body = c - o
        body_size = body.abs()

        lower_shadow = df[['close', 'open']].min(axis=1) - l
        upper_shadow = h - df[['close', 'open']].max(axis=1)
        df['hammer'] = (
            (lower_shadow > body_size * 2) &
            (upper_shadow < body_size * 0.3) &
            (body_size > 0)
        ).astype(int)

        prev_body = body.shift(1)
        df['bullish_engulf'] = (
            (body > 0) &
            (prev_body < 0) &
            (c > o.shift(1)) &
            (o < c.shift(1))
        ).astype(int)

        df['big_bull_bar'] = (
            (body > df['atr'] * 1.5) &
            (body > 0)
        ).astype(int)

        df['doji'] = (body_size < (h - l) * 0.1).astype(int)

        return df

    def get_feature_names(self) -> list:
        return [
            'ma5_dist', 'ma10_dist', 'ma20_dist', 'ma60_dist',
            'ma5_slope', 'ma20_slope', 'ma_rank_score',
            'body_ratio', 'upper_shadow', 'lower_shadow', 'shadow_ratio',
            'intraday_return',
            'ret_1', 'ret_2', 'ret_3', 'ret_5', 'ret_10',
            'vol_ratio_5', 'vol_ratio_20',
            'price_vol_corr', 'cum_vol_ratio',
            'obv_dist', 'mf_ratio',
            'rsi6', 'rsi14',
            'macd_hist', 'macd_hist_change',
            'kdj_k', 'kdj_d', 'kdj_j',
            'cci', 'williams_r',
            'atr_pct', 'bb_width', 'bb_pos',
            'hvol_5', 'hvol_10', 'hvol_20',
            'price_position_20', 'price_position_60',
            'break_high20', 'break_low20',
            'consecutive_bars',
            'hammer', 'bullish_engulf', 'big_bull_bar', 'doji',
            'minutes_from_open',
        ]
