"""
截面排名标签 — 跨股票
"""

import numpy as np
import pandas as pd


class CrossSectionalLabelBuilder:
    """
    截面排名标签

    同一时间点，对所有股票的未来收益排名
    前 top_pct = 买入(1)
    后 top_pct = 卖出(0)
    中间 = 中性(2)
    """

    def __init__(self, forward_window: int = 6, top_pct: float = 0.20):
        self.forward_window = forward_window
        self.top_pct = top_pct

    def build(self, multi_df: pd.DataFrame) -> pd.Series:
        """
        输入: MultiIndex DataFrame (datetime, code), 必须有 close 列
        输出: MultiIndex Series, label=0/1/2
        """
        codes = multi_df.index.get_level_values('code').unique()
        all_ret = []

        for code in codes:
            stock_df = multi_df.xs(code, level='code')
            forward_ret = self._calc_forward_ret(stock_df)
            forward_ret.index = pd.MultiIndex.from_arrays(
                [forward_ret.index, [code] * len(forward_ret)],
                names=['datetime', 'code']
            )
            all_ret.append(forward_ret)

        all_ret_s = pd.concat(all_ret).sort_index()
        labels = pd.Series(2.0, index=all_ret_s.index)

        for dt in all_ret_s.index.get_level_values('datetime').unique():
            try:
                dt_ret = all_ret_s.loc[dt].dropna()
            except KeyError:
                continue
            if len(dt_ret) < 3:
                continue

            upper_q = dt_ret.quantile(1 - self.top_pct)
            lower_q = dt_ret.quantile(self.top_pct)

            for code, ret in dt_ret.items():
                if ret >= upper_q:
                    labels.loc[(dt, code)] = 1
                elif ret <= lower_q:
                    labels.loc[(dt, code)] = 0

        buy_ret = all_ret_s[labels == 1].mean()
        sell_ret = all_ret_s[labels == 0].mean()

        if not (buy_ret > 0 and sell_ret < 0):
            raise ValueError(f"Label direction error: buy={buy_ret:.4f} sell={sell_ret:.4f}")

        print(f"Ranking labels: buy={buy_ret*100:+.3f}%, sell={sell_ret*100:+.3f}%")
        return labels

    def _calc_forward_ret(self, df: pd.DataFrame) -> pd.Series:
        close = df['close']
        fut = close.shift(-self.forward_window)
        forward_ret = fut / close - 1
        return forward_ret
