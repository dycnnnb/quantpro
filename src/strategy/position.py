"""
持仓管理
修复旧 PositionManager 的 Path-to-float 类型错误
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class Position:
    code: str
    entry_price: float
    shares: int
    entry_time: datetime
    direction: int = 1  # 1=long, -1=short
    stop_loss: float = 0.0
    take_profit: float = 999.0
    highest_price: float = 0.0
    lowest_price: float = float('inf')
    holding_bars: int = 0

    @property
    def cost(self) -> float:
        return self.entry_price * self.shares

    def update_price(self, price: float):
        self.highest_price = max(self.highest_price, price)
        self.lowest_price = min(self.lowest_price, price)
        self.holding_bars += 1

    def pnl(self, current_price: float) -> float:
        return (current_price - self.entry_price) * self.shares * self.direction

    def pnl_pct(self, current_price: float) -> float:
        if self.entry_price == 0:
            return 0.0
        return (current_price / self.entry_price - 1) * self.direction


class PositionManager:
    """持仓管理器"""

    def __init__(self, initial_capital: float = 1_000_000,
                 max_positions: int = 10,
                 max_daily_trades: int = 20):
        self.initial_capital = float(initial_capital)
        self.cash = float(initial_capital)
        self.max_positions = max_positions
        self.max_daily_trades = max_daily_trades
        self.positions: Dict[str, Position] = {}
        self.closed_trades: list = []
        self.daily_pnl = 0.0
        self.daily_trades = 0

    @property
    def equity(self) -> float:
        return self.cash + sum(p.cost for p in self.positions.values())

    def open_position(self, code: str, price: float, shares: int,
                      stop_loss: float = 0.0, take_profit: float = 999.0) -> Optional[Position]:
        """开仓"""
        if code in self.positions:
            return None
        if len(self.positions) >= self.max_positions:
            return None

        # Ensure price and shares are numeric
        price = float(price)
        shares = int(shares)

        cost = price * shares
        if cost > self.cash:
            return None

        self.cash -= cost
        pos = Position(
            code=code, entry_price=price, shares=shares,
            entry_time=datetime.now(), stop_loss=stop_loss,
            take_profit=take_profit, highest_price=price, lowest_price=price,
        )
        self.positions[code] = pos
        self.daily_trades += 1
        return pos

    def close_position(self, code: str, price: float, reason: str = "") -> Optional[float]:
        """平仓，返回盈亏"""
        if code not in self.positions:
            return None

        pos = self.positions.pop(code)
        price = float(price)
        proceeds = price * pos.shares
        self.cash += proceeds

        pnl = pos.pnl(price)
        self.daily_pnl += pnl
        self.closed_trades.append({
            'code': code, 'entry_price': pos.entry_price,
            'exit_price': price, 'shares': pos.shares,
            'pnl': pnl, 'reason': reason,
            'entry_time': pos.entry_time, 'exit_time': datetime.now(),
        })
        return pnl

    def reset_daily(self):
        self.daily_pnl = 0.0
        self.daily_trades = 0
