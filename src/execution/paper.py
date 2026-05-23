"""
模拟交易执行器
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.strategy.position import PositionManager
from src.strategy.risk import RiskController
from src.strategy.regime import RegimeDetector
from src.data.loader import DataLoader
from config.settings import PATHS, trade_config


class PaperTrader:
    """模拟交易"""

    def __init__(self):
        self.loader = DataLoader()
        self.manager = PositionManager(
            initial_capital=trade_config.total_capital,
            max_positions=trade_config.max_positions,
        )
        self.risk = RiskController()
        self.log_path = PATHS["log_dir"] / "paper_trading.json"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def run_daily(self, stock_codes: list, top_k: int = 5):
        """每日模拟交易流程"""
        print(f"Paper trading: {len(stock_codes)} stocks")

        # Check portfolio risk
        blocked, reason = self.risk.check_portfolio(self.manager)
        if blocked:
            print(f"Portfolio risk blocked: {reason}")
            return

        # Evaluate existing positions
        for code in list(self.manager.positions.keys()):
            try:
                df = self.loader.load_daily(code)
                if df.empty:
                    continue
                current_price = self.loader.get_realtime_price(code) or float(df['close'].iloc[-1])
                self.manager.positions[code].update_price(current_price)

                should_close, close_reason = self.risk.check_position(
                    self.manager.positions[code], current_price, datetime.now()
                )
                if should_close:
                    pnl = self.manager.close_position(code, current_price, close_reason)
                    print(f"  Close {code}: {close_reason}, PnL={pnl:+,.0f}")
            except Exception as e:
                print(f"  Error evaluating {code}: {e}")

        # Select new stocks (simple scoring for now)
        candidates = self._score_stocks(stock_codes)
        top_stocks = candidates.head(top_k)

        # Open new positions
        available_slots = self.manager.max_positions - len(self.manager.positions)
        for code in top_stocks.index[:available_slots]:
            try:
                df = self.loader.load_daily(code)
                if df.empty:
                    continue
                price = self.loader.get_realtime_price(code) or float(df['close'].iloc[-1])
                capital_per = self.manager.cash / max(available_slots, 1)
                shares = int(capital_per / price / 100) * 100
                if shares >= 100:
                    stop_loss = price * (1 + trade_config.stop_loss_pct)
                    pos = self.manager.open_position(code, price, shares, stop_loss=stop_loss)
                    if pos:
                        print(f"  Open {code}: {shares} shares @ {price:.2f}")
            except Exception as e:
                print(f"  Error opening {code}: {e}")

        self._save_log()

    def _score_stocks(self, codes: list) -> pd.Series:
        """简单因子打分"""
        scores = {}
        for code in codes:
            try:
                df = self.loader.load_daily(code)
                if df.empty or len(df) < 60:
                    continue
                close = df['close']
                low_20 = df['low'].rolling(20).min()
                score = float((close.iloc[-1] - low_20.iloc[-1]) / (close.iloc[-1] + 1e-8))
                scores[code] = score
            except Exception:
                pass
        return pd.Series(scores).sort_values(ascending=False)

    def _save_log(self):
        log = {
            'timestamp': datetime.now().isoformat(),
            'cash': self.manager.cash,
            'equity': self.manager.equity,
            'positions': {
                code: {'entry': p.entry_price, 'shares': p.shares}
                for code, p in self.manager.positions.items()
            },
            'daily_pnl': self.manager.daily_pnl,
        }
        existing = []
        if self.log_path.exists():
            try:
                existing = json.loads(self.log_path.read_text(encoding='utf-8'))
            except Exception:
                pass
        existing.append(log)
        self.log_path.write_text(json.dumps(existing, indent=2, default=str, ensure_ascii=False))
