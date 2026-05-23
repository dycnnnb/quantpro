"""
日内标签构建
基于前向N根K线的止盈/止损路径判断
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


class IntradayLabelBuilder:

    def __init__(
        self,
        forward_bars: int = 6,
        take_profit: float = 0.008,
        stop_loss: float = 0.004,
        min_profit: float = 0.003,
    ):
        self.forward_bars = forward_bars
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.min_profit = min_profit

    def build(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        labels = []
        prices = df['close'].values
        highs = df['high'].values
        lows = df['low'].values

        for i in range(len(df)):
            end = min(i + self.forward_bars, len(df) - 1)
            if i >= len(df) - self.forward_bars:
                labels.append(np.nan)
                continue

            entry = prices[i]
            tp_price = entry * (1 + self.take_profit)
            sl_price = entry * (1 - self.stop_loss)

            hit_tp = False
            hit_sl = False
            tp_bar = end
            sl_bar = end

            for j in range(i + 1, end + 1):
                if highs[j] >= tp_price:
                    hit_tp = True
                    tp_bar = j
                    break
                if lows[j] <= sl_price:
                    hit_sl = True
                    sl_bar = j
                    break

            if hit_tp and not hit_sl:
                labels.append(1)
            elif hit_sl and not hit_tp:
                labels.append(-1)
            elif hit_tp and hit_sl:
                labels.append(1 if tp_bar <= sl_bar else -1)
            else:
                future_ret = (prices[end] - entry) / entry
                if future_ret >= self.min_profit:
                    labels.append(1)
                elif future_ret <= -self.min_profit:
                    labels.append(-1)
                else:
                    labels.append(0)

        df['label'] = labels
        dist = pd.Series(labels).value_counts()
        logger.info(f"标签分布: {dist.to_dict()}")
        return df.dropna(subset=['label'])

    def build_regression_label(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        future_max_ret = []
        prices = df['close'].values
        highs = df['high'].values

        for i in range(len(df)):
            end = min(i + self.forward_bars, len(df) - 1)
            if i >= len(df) - self.forward_bars:
                future_max_ret.append(np.nan)
                continue
            max_high = highs[i + 1:end + 1].max()
            ret = (max_high - prices[i]) / prices[i]
            future_max_ret.append(ret)

        df['label_reg'] = future_max_ret
        return df.dropna(subset=['label_reg'])
