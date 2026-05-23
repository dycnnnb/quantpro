"""
日线特征工程
基于截面 IC 验证通过的因子集合
"""

import pandas as pd
import numpy as np

from src.features.base import BaseFeature


class DailyFeatureBuilder(BaseFeature):
    """日线 OHLCV 特征"""

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        输入: 单只股票的日线 DataFrame (index=date, columns=open/high/low/close/volume)
        输出: 特征 DataFrame
        """
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']

        f = pd.DataFrame(index=df.index)

        # 价格位置
        high_60 = high.rolling(60).max()
        low_60 = low.rolling(60).min()
        f['price_position'] = (close - low_60) / (high_60 - low_60 + 1e-8)

        # 趋势强度
        ma_5 = close.rolling(5).mean()
        ma_60 = close.rolling(60).mean()
        f['trend_strength'] = (ma_5 - ma_60) / (ma_60 + 1e-8)

        # 反转因子
        f['reversal'] = -close.pct_change(20)

        # 距离低点
        low_20 = low.rolling(20).min()
        f['dist_low'] = (close - low_20) / (close + 1e-8)

        # 波动率
        f['volatility'] = close.pct_change().rolling(20).std()

        # 成交量比率
        vol_ma20 = volume.rolling(20).mean()
        f['volume_ratio'] = volume / (vol_ma20 + 1e-8)

        # 动量
        f['momentum_5'] = close.pct_change(5)
        f['momentum_20'] = close.pct_change(20)
        f['momentum_60'] = close.pct_change(60)

        # VWAP 偏离
        vwap = close.rolling(20).mean()
        f['vwap_dev'] = (close - vwap) / (vwap + 1e-8)

        # 振幅
        f['range_ratio'] = (high - low).rolling(20).mean() / (close + 1e-8)

        # 换手率代理
        f['vol_shrink'] = volume / (volume.rolling(60).mean() + 1e-8)

        return f.replace([np.inf, -np.inf], np.nan).ffill()


def build_daily_features_panel(
    stock_codes: list,
    data_loader,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    构建多股票日线特征面板
    返回: MultiIndex DataFrame (date, code), columns=特征
    """
    builder = DailyFeatureBuilder()
    all_factors = []

    for code in stock_codes:
        df = data_loader.load_daily(code, start_date, end_date)
        if df.empty or len(df) < 60:
            continue
        factors = builder.compute(df)
        factors['code'] = code
        all_factors.append(factors)

    if not all_factors:
        raise ValueError("No features computed")

    panel = pd.concat(all_factors)
    panel = panel.reset_index().rename(columns={'date': 'date'})
    panel = panel.set_index(['date', 'code'])

    factor_cols = [c for c in panel.columns if c != 'code']

    # 截面排名标准化
    normalized = panel[factor_cols].groupby(level='date').apply(
        lambda g: g.rank(pct=True)
    )
    if isinstance(normalized.index, pd.MultiIndex) and normalized.index.nlevels > 2:
        normalized = normalized.droplevel(0)
    normalized = normalized.fillna(0.5)

    print(f"Daily features: {len(stock_codes)} stocks, {len(factor_cols)} factors, shape={normalized.shape}")
    return normalized
