"""
风控模块
"""

from datetime import datetime, time
from typing import Tuple

import pandas as pd

from src.strategy.position import Position, PositionManager


class RiskController:
    """多级风控"""

    def __init__(self, max_daily_loss_pct: float = 0.03,
                 max_total_position: float = 0.95,
                 max_holding_bars: int = 48,
                 close_time: str = "14:55"):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_total_position = max_total_position
        self.max_holding_bars = max_holding_bars
        h, m = close_time.split(':')
        self.close_time = time(int(h), int(m))
        self.risk_events = []

    def check_position(self, position: Position, current_price: float,
                       current_time: datetime) -> Tuple[bool, str]:
        """持仓级风控"""
        price = float(current_price)

        if position.direction == 1:
            if price <= position.stop_loss:
                return True, f"stop_loss ({price:.2f} <= {position.stop_loss:.2f})"
            if price >= position.take_profit:
                return True, f"take_profit ({price:.2f} >= {position.take_profit:.2f})"
        else:
            if price >= position.stop_loss:
                return True, f"stop_loss"
            if price <= position.take_profit:
                return True, f"take_profit"

        if position.holding_bars >= self.max_holding_bars:
            return True, f"timeout ({position.holding_bars} bars)"

        if current_time.time() >= self.close_time:
            return True, "end_of_day"

        return False, ""

    def check_portfolio(self, manager: PositionManager) -> Tuple[bool, str]:
        """组合级风控"""
        daily_loss_pct = manager.daily_pnl / manager.initial_capital
        if daily_loss_pct < -self.max_daily_loss_pct:
            return True, f"daily_loss_limit ({daily_loss_pct*100:.2f}%)"

        pos_val = sum(p.cost for p in manager.positions.values())
        pos_ratio = pos_val / manager.equity if manager.equity > 0 else 0
        if pos_ratio > self.max_total_position:
            return True, f"position_limit ({pos_ratio*100:.1f}%)"

        return False, ""

    def check_market(self, market_data: pd.DataFrame) -> Tuple[bool, str]:
        """市场级风控"""
        if len(market_data) < 20:
            return False, ""

        returns = market_data['close'].pct_change()
        last_ret = returns.iloc[-1]
        hist_vol = returns.rolling(20).std().iloc[-1]

        if abs(last_ret) > 3 * hist_vol:
            return True, f"abnormal_volatility ({last_ret*100:+.2f}%)"

        return False, ""
