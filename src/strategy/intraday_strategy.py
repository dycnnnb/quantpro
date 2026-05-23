"""
日内五分钟线策略
整合信号生成 + 风控 + 持仓管理
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


@dataclass
class IntradayPosition:
    symbol: str
    entry_price: float
    entry_time: pd.Timestamp
    shares: int
    stop_loss: float
    take_profit: float
    entry_bar: int = 0
    max_price: float = 0.0


@dataclass
class TradeRecord:
    symbol: str
    entry_price: float
    exit_price: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    shares: int
    pnl: float
    pnl_pct: float
    exit_reason: str
    hold_bars: int


class IntradayRiskController:

    def __init__(
        self,
        max_positions: int = 3,
        max_daily_loss: float = 0.02,
        max_single_loss: float = 0.004,
        position_size_pct: float = 0.30,
        trailing_stop_ratio: float = 0.003,
    ):
        self.max_positions = max_positions
        self.max_daily_loss = max_daily_loss
        self.max_single_loss = max_single_loss
        self.position_size_pct = position_size_pct
        self.trailing_stop_ratio = trailing_stop_ratio

    def calc_shares(self, capital: float, price: float, atr: float) -> int:
        risk_amount = capital * self.position_size_pct
        atr_risk = atr * 2
        if atr_risk <= 0:
            return 0
        shares = int(risk_amount / atr_risk / 100) * 100
        max_shares = int(capital * self.position_size_pct / price / 100) * 100
        return min(shares, max_shares)

    def calc_stop_loss(self, entry: float, atr: float) -> float:
        sl_by_atr = entry - atr * 1.5
        sl_by_fixed = entry * (1 - self.max_single_loss)
        return max(sl_by_atr, sl_by_fixed)

    def calc_take_profit(self, entry: float, stop_loss: float) -> float:
        risk = entry - stop_loss
        return entry + risk * 2.0

    def update_trailing_stop(
        self, position: IntradayPosition, current_price: float
    ) -> float:
        if current_price > position.max_price:
            position.max_price = current_price
            new_sl = current_price * (1 - self.trailing_stop_ratio)
            return max(new_sl, position.stop_loss)
        return position.stop_loss

    def should_stop_trading(self, daily_pnl: float, initial_capital: float) -> bool:
        loss_pct = daily_pnl / initial_capital
        if loss_pct <= -self.max_daily_loss:
            logger.warning(f"当日亏损 {loss_pct:.2%}，触发熔断")
            return True
        return False


class IntradaySignalGenerator:

    def __init__(self, ml_threshold: float = 0.6, use_ml: bool = True, model=None):
        self.ml_threshold = ml_threshold
        self.use_ml = use_ml
        self.model = model

    def generate(self, df: pd.DataFrame, feature_cols: list) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['ml_prob'] = 0.0
        df['rule_signal'] = self._rule_based_signal(df)

        if self.use_ml and self.model is not None:
            X = df[feature_cols].fillna(0)
            try:
                proba = self.model.predict_proba(X)
                df['ml_prob'] = proba[:, 1]
                df['ml_signal'] = (df['ml_prob'] >= self.ml_threshold).astype(int)
            except Exception as e:
                logger.error(f"ML预测失败: {e}")
                df['ml_signal'] = 0
        else:
            df['ml_signal'] = 0

        if self.use_ml and self.model is not None:
            df['signal'] = (
                (df['rule_signal'] == 1) & (df['ml_signal'] == 1)
            ).astype(int)
        else:
            df['signal'] = (df['rule_signal'] == 1).astype(int)

        return df

    def _rule_based_signal(self, df: pd.DataFrame) -> pd.Series:
        signal = pd.Series(0, index=df.index)

        cond_trend = (
            (df['ma5'] > df['ma20']) &
            (df['ma_rank_score'] >= 2)
        )

        cond_momentum = (
            (df['macd_hist'] > 0) &
            (df['macd_hist'] > df['macd_hist'].shift(1)) &
            (df['rsi6'] > 40) &
            (df['rsi6'] < 75)
        )

        cond_breakout = (
            (df['break_high20'] == 1) &
            (df['vol_ratio_5'] > 1.5)
        )

        cond_pattern = (
            (df['hammer'] == 1) |
            (df['bullish_engulf'] == 1) |
            (df['big_bull_bar'] == 1)
        )

        cond_no_extreme = (
            (df['bb_pos'] < 0.85) &
            (df['rsi14'] < 80)
        )

        signal[
            cond_trend & cond_momentum &
            (cond_breakout | cond_pattern) &
            cond_no_extreme
        ] = 1

        return signal


class IntradayStrategy:

    def __init__(
        self,
        capital: float = 500_000,
        risk_ctrl: IntradayRiskController = None,
        signal_gen: IntradaySignalGenerator = None,
        commission: float = 0.0003,
        slippage: float = 0.0001,
        max_hold_bars: int = 24,
    ):
        self.capital = capital
        self.initial_cap = capital
        self.risk_ctrl = risk_ctrl or IntradayRiskController()
        self.signal_gen = signal_gen or IntradaySignalGenerator()
        self.commission = commission
        self.slippage = slippage
        self.max_hold_bars = max_hold_bars

        self.positions: Dict[str, IntradayPosition] = {}
        self.trades: List[TradeRecord] = []
        self.daily_pnl: float = 0.0
        self.equity_curve: List[float] = []

    def run(self, df: pd.DataFrame, feature_cols: list, symbol: str) -> pd.DataFrame:
        logger.info(f"开始运行策略: {symbol}, 数据量: {len(df)}")
        df = self.signal_gen.generate(df, feature_cols)
        self.daily_pnl = 0.0

        for i, (idx, row) in enumerate(df.iterrows()):
            current_price = row['close']
            total_value = self._calc_total_value(current_price, symbol)
            self.equity_curve.append(total_value)

            if self.risk_ctrl.should_stop_trading(self.daily_pnl, self.initial_cap):
                if symbol in self.positions:
                    self._execute_sell(symbol, row, i, reason='熔断止损')
                continue

            if symbol in self.positions:
                self._manage_position(symbol, row, i)
            elif row['signal'] == 1 and len(self.positions) < self.risk_ctrl.max_positions:
                self._execute_buy(symbol, row, i)

        if symbol in self.positions:
            last_row = df.iloc[-1]
            self._execute_sell(symbol, last_row, len(df) - 1, reason='收盘平仓')

        return df

    def _manage_position(self, symbol: str, row: pd.Series, bar_idx: int):
        pos = self.positions[symbol]
        current_price = row['close']
        pos.stop_loss = self.risk_ctrl.update_trailing_stop(pos, current_price)

        if row['low'] <= pos.stop_loss:
            exit_price = max(pos.stop_loss, row['low'])
            self._execute_sell(symbol, row, bar_idx, reason='止损', override_price=exit_price)
            return

        if row['high'] >= pos.take_profit:
            exit_price = pos.take_profit
            self._execute_sell(symbol, row, bar_idx, reason='止盈', override_price=exit_price)
            return

        hold_bars = bar_idx - pos.entry_bar
        if hold_bars >= self.max_hold_bars:
            self._execute_sell(symbol, row, bar_idx, reason='超时平仓')
            return

        time_str = pd.Timestamp(row['time']).strftime('%H:%M')
        if time_str >= '14:45':
            self._execute_sell(symbol, row, bar_idx, reason='收盘平仓')

    def _execute_buy(self, symbol: str, row: pd.Series, bar_idx: int):
        price = row['close'] * (1 + self.slippage)
        atr = row.get('atr', price * 0.005)

        shares = self.risk_ctrl.calc_shares(self.capital, price, atr)
        if shares == 0:
            return

        cost = shares * price * (1 + self.commission)
        if cost > self.capital:
            return

        stop_loss = self.risk_ctrl.calc_stop_loss(price, atr)
        take_profit = self.risk_ctrl.calc_take_profit(price, stop_loss)

        self.capital -= cost
        self.positions[symbol] = IntradayPosition(
            symbol=symbol, entry_price=price, entry_time=row['time'],
            shares=shares, stop_loss=stop_loss, take_profit=take_profit,
            entry_bar=bar_idx, max_price=price,
        )
        logger.info(
            f"买入 {symbol} | 价格:{price:.2f} | 数量:{shares} | "
            f"止损:{stop_loss:.2f} | 止盈:{take_profit:.2f}"
        )

    def _execute_sell(
        self, symbol: str, row: pd.Series, bar_idx: int,
        reason: str = '', override_price: float = None,
    ):
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        price = (override_price or row['close']) * (1 - self.slippage)

        revenue = pos.shares * price * (1 - self.commission)
        pnl = revenue - pos.shares * pos.entry_price * (1 + self.commission)
        pnl_pct = pnl / (pos.shares * pos.entry_price)

        self.capital += revenue
        self.daily_pnl += pnl

        trade = TradeRecord(
            symbol=symbol, entry_price=pos.entry_price, exit_price=price,
            entry_time=pos.entry_time, exit_time=row['time'],
            shares=pos.shares, pnl=pnl, pnl_pct=pnl_pct,
            exit_reason=reason, hold_bars=bar_idx - pos.entry_bar,
        )
        self.trades.append(trade)
        del self.positions[symbol]
        logger.info(f"卖出 {symbol} | 原因:{reason} | 价格:{price:.2f} | 盈亏:{pnl:.0f}({pnl_pct:.2%})")

    def _calc_total_value(self, price: float, symbol: str) -> float:
        pos_value = 0
        if symbol in self.positions:
            pos_value = self.positions[symbol].shares * price
        return self.capital + pos_value
