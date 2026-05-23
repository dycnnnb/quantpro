"""
分钟线特征工程
"""

import pandas as pd
import numpy as np

from src.features.base import BaseFeature


class MinuteFeatureBuilder(BaseFeature):
    """分钟线 OHLCV 特征"""

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        输入: 单只股票分钟线 DataFrame (index=datetime)
        输出: 特征 DataFrame
        """
        close = df['close']
        high = df['high']
        low = df['low']
        open_ = df['open']
        vol = df['volume']
        ret1 = close.pct_change()

        f = pd.DataFrame(index=df.index)

        # 价格距高低点
        for n in [3, 6, 12, 24, 48]:
            roll_h = high.rolling(n).max()
            roll_l = low.rolling(n).min()
            rng = roll_h - roll_l + 1e-8
            f[f'dist_high_{n}'] = (roll_h - close) / (close + 1e-8)
            f[f'dist_low_{n}'] = (close - roll_l) / (close + 1e-8)
            f[f'price_pos_{n}'] = (close - roll_l) / rng

        # 振幅比
        for n in [6, 12, 24]:
            avg_rng = (high - low).rolling(n).mean()
            f[f'range_ratio_{n}'] = avg_rng / (close + 1e-8)

        # 日内累计收益
        df_c = df.copy()
        df_c['_date'] = df.index.date
        day_open = df_c.groupby('_date')['open'].transform('first')
        f['intraday_ret'] = close / day_open - 1
        f['intraday_ret_abs'] = f['intraday_ret'].abs()
        f['intraday_accel'] = f['intraday_ret'] - f['intraday_ret'].shift(3)

        # 短期动量
        for n in [1, 2, 3, 6]:
            f[f'ret_{n}'] = close.pct_change(n)
            f[f'ret_{n}_abs'] = f[f'ret_{n}'].abs()

        # 成交量
        for n in [6, 12, 24]:
            f[f'vol_ratio_{n}'] = vol / (vol.rolling(n).mean() + 1e-8)

        f['up_vol_ratio'] = (
            (vol * (ret1 > 0)).rolling(6).sum() /
            (vol.rolling(6).sum() + 1e-8)
        )
        f['money_flow_6'] = (ret1 * vol).rolling(6).sum()

        # K线形态
        hl = high - low + 1e-8
        f['upper_shadow'] = (high - close.combine(open_, max)) / hl
        f['lower_shadow'] = (close.combine(open_, min) - low) / hl
        f['body_ratio'] = abs(close - open_) / hl
        f['close_vs_open'] = close / open_ - 1

        # 日内时段
        h = df.index.hour
        m = df.index.minute
        f['is_morning'] = ((h == 9) & (m >= 30) | (h == 10)).astype(int)
        f['is_lunch_open'] = ((h == 13) & (m < 30)).astype(int)
        f['is_close'] = ((h == 14) & (m >= 30)).astype(int)
        mins = (h - 9) * 60 + m - 30
        f['time_progress'] = np.clip(mins / 240, 0, 1)

        # 日内成交量进度
        vol_cum = df_c.groupby('_date')['volume'].cumsum()
        vol_tot = df_c.groupby('_date')['volume'].transform('sum')
        f['vol_progress'] = vol_cum / (vol_tot + 1e-8)

        return f.replace([np.inf, -np.inf], np.nan).ffill().dropna()
