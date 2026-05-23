"""
市场状态检测
"""

import pandas as pd
import numpy as np
from enum import Enum


class MarketRegime(Enum):
    BULL = "bull"
    BEAR = "bear"
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"
    NEUTRAL = "neutral"


class RegimeDetector:
    """市场状态检测器"""

    def __init__(self, close_series: pd.Series, lookback: int = 60):
        self.close = close_series
        self.lookback = lookback
        self._precompute()

    def _precompute(self):
        c = self.close
        self.ma_short = c.rolling(20).mean()
        self.ma_long = c.rolling(self.lookback).mean()
        ret = c.pct_change()
        self.vol_20 = ret.rolling(20).std() * np.sqrt(252)
        roll_max = c.rolling(self.lookback).max()
        self.drawdown = (c - roll_max) / roll_max

    def detect(self) -> MarketRegime:
        if len(self.close) < self.lookback:
            return MarketRegime.NEUTRAL

        trend = (self.ma_short.iloc[-1] - self.ma_long.iloc[-1]) / self.ma_long.iloc[-1]
        vol = self.vol_20.iloc[-1]

        if abs(trend) < 0.02 and 0.15 <= vol <= 0.35:
            return MarketRegime.HIGH_VOL
        elif trend > 0.03 and vol < 0.30:
            return MarketRegime.BULL
        elif trend < -0.03 and vol < 0.35:
            return MarketRegime.BEAR
        elif vol > 0.40:
            return MarketRegime.HIGH_VOL
        elif vol < 0.10:
            return MarketRegime.LOW_VOL
        return MarketRegime.NEUTRAL

    def get_position_scale(self) -> float:
        regime = self.detect()
        scales = {
            MarketRegime.BULL: 1.0, MarketRegime.NEUTRAL: 0.5,
            MarketRegime.HIGH_VOL: 0.3, MarketRegime.LOW_VOL: 0.0,
            MarketRegime.BEAR: 0.15,
        }
        return scales.get(regime, 0.5)

    def should_trade(self) -> bool:
        return self.get_position_scale() > 0

    def get_info(self) -> dict:
        regime = self.detect()
        return {
            'regime': regime.value,
            'position_scale': self.get_position_scale(),
            'should_trade': self.should_trade(),
        }
