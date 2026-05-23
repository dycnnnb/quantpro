"""
回测命令
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def cmd_backtest_single(args):
    """单股票回测"""
    from src.data.loader import DataLoader
    from src.features.daily import DailyFeatureBuilder
    from src.models.lgbm_model import ThreeClassModel
    from src.backtest.engine import SingleStockBacktest, BacktestConfig
    from src.backtest.report import save_report
    from config.settings import PATHS

    loader = DataLoader()
    df = loader.load_daily(args.symbol, args.start, args.end)

    if df.empty:
        print(f"No data for {args.symbol}")
        return

    print(f"Data: {len(df)} rows, {df.index[0]} ~ {df.index[-1]}")

    # Generate signals
    if args.model:
        from src.models.lgbm_model import ThreeClassModel
        model = ThreeClassModel.load(args.model)
        builder = DailyFeatureBuilder()
        X = builder.compute(df)
        signals = model.predict(X)
    else:
        # Simple momentum signals
        import pandas as pd
        signals = pd.DataFrame(index=df.index)
        close = df['close']
        ma5 = close.rolling(5).mean()
        ma20 = close.rolling(20).mean()
        signals['signal'] = 2
        signals.loc[ma5 > ma20, 'signal'] = 1
        signals['buy_prob'] = 0.6

    # Backtest
    config = BacktestConfig(
        initial_capital=args.capital,
        stop_loss=args.stop_loss,
        top_k=args.top_k,
    )
    bt = SingleStockBacktest(config)
    report, trades, equity = bt.run(df, signals)

    # Save
    if report:
        save_report(report, trades, equity, str(PATHS["log_dir"] / "backtest"))


def cmd_backtest_cs(args):
    """截面回测"""
    from src.data.loader import DataLoader
    from src.features.cross_sectional import build_cross_sectional_features
    from src.models.lgbm_model import CrossSectionalModel
    from src.backtest.engine import CrossSectionalBacktest, BacktestConfig
    from src.backtest.report import save_report
    from config.settings import PATHS

    loader = DataLoader()
    symbols = loader.get_available_symbols(min_bars=args.min_bars)[:args.max_stocks]

    if not symbols:
        print("No symbols")
        return

    print(f"Backtest pool: {len(symbols)} stocks")

    # Load model
    if args.model:
        model = CrossSectionalModel.load(args.model)
    else:
        print("No model specified, use --model <path>")
        return

    # Load data
    multi_df = loader.load_multi_minute(symbols, args.start, args.end)
    if multi_df.empty:
        print("No data")
        return

    # Test split
    datetimes = multi_df.index.get_level_values('datetime').unique()
    test_start = int(len(datetimes) * 0.85)
    test_dts = datetimes[test_start:]
    test_mask = multi_df.index.get_level_values('datetime').isin(test_dts)
    test_df = multi_df[test_mask]

    # Generate scores
    print("Generating signals...")
    X_test = build_cross_sectional_features(test_df)
    scores = model.predict(X_test)

    # Backtest
    config = BacktestConfig(
        initial_capital=args.capital,
        stop_loss=args.stop_loss,
        top_k=args.top_k,
    )
    engine = CrossSectionalBacktest(config)
    report, trades, equity = engine.run(test_df, scores)

    if report:
        save_report(report, trades, equity, str(PATHS["log_dir"] / "backtest_cs"))
