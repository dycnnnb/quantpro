#!/usr/bin/env python
"""
全市场回测入口
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.loader import DataLoader
from src.backtest.engine import SingleStockBacktest, BacktestConfig


def main():
    print("=" * 60)
    print("Full Backtest")
    print("=" * 60)

    loader = DataLoader()
    symbols = loader.get_daily_symbols(min_days=200)
    print(f"Backtest pool: {len(symbols)} stocks")

    if not symbols:
        print("No stocks available")
        return

    # Example: single stock backtest
    code = symbols[0]
    print(f"\nBacktesting {code}...")

    df = loader.load_daily(code, "2023-01-01", "2025-12-31")
    if df.empty:
        print("No data")
        return

    # Generate simple signals (placeholder)
    import pandas as pd
    signals = pd.DataFrame(index=df.index)
    signals['signal'] = 2
    signals['buy_prob'] = 0.5

    bt = SingleStockBacktest(BacktestConfig())
    report, trades, equity = bt.run(df, signals)

    print("Backtest complete.")


if __name__ == '__main__':
    main()
