"""
分位数标签 — 单股票
"""

import numpy as np
import pandas as pd


class SmartLabelBuilder:
    """单股票分位数标签"""

    def __init__(self, forward_window=3, signal_pct=0.20):
        self.forward_window = forward_window
        self.signal_pct = signal_pct

    def build(self, df: pd.DataFrame) -> pd.Series:
        forward_ret = self._calc_forward_ret(df)
        labels = self._make_labels(forward_ret)
        return labels.reindex(df.index)

    def _calc_forward_ret(self, df: pd.DataFrame) -> pd.Series:
        close = df['close']
        # For daily data (one row per date), just shift directly
        if hasattr(df.index, 'freq') or df.index.nunique() == len(df):
            fut = close.shift(-self.forward_window)
            return fut / close - 1
        # For intraday data, group by trading day
        forward_ret = pd.Series(np.nan, index=df.index)
        for date, day_df in df.groupby(df.index.date):
            if len(day_df) <= self.forward_window:
                continue
            fut = day_df['close'].shift(-self.forward_window)
            ret = fut / day_df['close'] - 1
            forward_ret.loc[day_df.index] = ret.values
        return forward_ret

    def _make_labels(self, forward_ret: pd.Series) -> pd.Series:
        valid = forward_ret.dropna()
        if valid.empty:
            raise ValueError("No valid forward returns")

        upper_q = valid.quantile(1 - self.signal_pct)
        lower_q = valid.quantile(self.signal_pct)

        labels = pd.Series(2, index=forward_ret.index)
        labels[forward_ret >= upper_q] = 1  # buy
        labels[forward_ret <= lower_q] = 0  # sell
        labels[forward_ret.isna()] = np.nan
        return labels
