"""
模型训练命令
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def cmd_train_single(args):
    """单股票模型训练"""
    from src.data.loader import DataLoader
    from src.features.daily import DailyFeatureBuilder
    from src.features.technical import add_technical_indicators
    from src.labels.quantile import SmartLabelBuilder
    from src.models.lgbm_model import ThreeClassModel
    from config.settings import model_config, PATHS

    loader = DataLoader()
    df = loader.load_daily(args.symbol, args.start, args.end)

    if df.empty:
        print(f"No data for {args.symbol}")
        return

    print(f"Data: {len(df)} rows, {df.index[0]} ~ {df.index[-1]}")

    # Features
    builder = DailyFeatureBuilder()
    features = builder.compute(df)
    tech = add_technical_indicators(df)
    X = features.join(tech, how='inner')

    # Labels
    label_builder = SmartLabelBuilder(forward_window=5, signal_pct=0.20)
    y = label_builder.build(df)
    y = y.reindex(X.index)

    # Train/test split
    n = len(X)
    split = int(n * 0.8)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    print(f"\nTrain: {len(X_train)}, Test: {len(X_test)}")

    # Train
    model = ThreeClassModel(confidence_threshold=args.threshold)
    model.fit(X_train, y_train)

    # Evaluate
    metrics = model.evaluate(X_test, y_test)

    # Save
    out_path = PATHS["model_dir"] / f"single_{args.symbol}_{datetime.now():%Y%m%d}.pkl"
    model.save(str(out_path))

    report_path = PATHS["model_dir"] / f"single_{args.symbol}_report.json"
    report_path.write_text(json.dumps(metrics, indent=2, default=str))
    print(f"Report: {report_path}")


def cmd_train_cs(args):
    """截面模型训练"""
    from src.data.loader import DataLoader
    from src.features.cross_sectional import build_cross_sectional_features
    from src.labels.ranking import CrossSectionalLabelBuilder
    from src.models.lgbm_model import CrossSectionalModel
    from config.settings import model_config, PATHS

    loader = DataLoader()
    symbols = loader.get_available_symbols(min_bars=args.min_bars)[:args.max_stocks]

    if not symbols:
        print("No symbols available")
        return

    print(f"Training pool: {len(symbols)} stocks")

    # Load minute data
    multi_df = loader.load_multi_minute(symbols, args.start, args.end, freq="5min")
    if multi_df.empty:
        print("No minute data")
        return

    print(f"Data: {len(multi_df):,} rows, {multi_df.index.get_level_values('code').nunique()} stocks")

    # Split by time
    datetimes = multi_df.index.get_level_values('datetime').unique()
    n = len(datetimes)
    train_end = int(n * 0.7)
    test_start = int(n * 0.85)

    train_dts = datetimes[:train_end]
    test_dts = datetimes[test_start:]

    print(f"Train: {train_dts[0]} ~ {train_dts[-1]}")
    print(f"Test:  {test_dts[0]} ~ {test_dts[-1]}")

    # Features
    print("\nBuilding features...")
    X_all = build_cross_sectional_features(multi_df)

    # Labels
    print("Building labels...")
    label_builder = CrossSectionalLabelBuilder(forward_window=6, top_pct=0.20)
    y_all = label_builder.build(multi_df)

    # Align
    common = X_all.index.intersection(y_all.index)
    X_all = X_all.loc[common]
    y_all = y_all.loc[common]

    # Train on train set
    tr_mask = X_all.index.get_level_values('datetime').isin(train_dts)
    model = CrossSectionalModel(top_k=args.top_k, confidence_threshold=args.threshold)
    model.fit(X_all[tr_mask], y_all[tr_mask])

    # Evaluate on test set
    te_mask = X_all.index.get_level_values('datetime').isin(test_dts)
    metrics = model.evaluate(X_all[te_mask], y_all[te_mask])

    # Save
    out_path = PATHS["model_dir"] / f"cs_model_{datetime.now():%Y%m%d}.pkl"
    model.save(str(out_path))

    report_path = PATHS["model_dir"] / "cs_train_report.json"
    report_path.write_text(json.dumps(metrics, indent=2, default=str))
    print(f"\nModel: {out_path}")
    print(f"Report: {report_path}")


def cmd_train_ensemble(args):
    """集成模型训练"""
    from datetime import datetime
    import json
    from src.data.loader import DataLoader
    from src.features.daily import DailyFeatureBuilder, build_daily_features_panel
    from src.features.technical import add_technical_indicators
    from src.labels.quantile import SmartLabelBuilder
    from src.models.ensemble import EnsembleModel
    from config.settings import PATHS

    loader = DataLoader()
    symbols = loader.get_daily_symbols(min_days=200)[:args.max_stocks]

    if not symbols:
        print("No symbols")
        return

    print(f"Ensemble training: {len(symbols)} stocks")

    # Build features panel
    features = build_daily_features_panel(symbols, loader, args.start, args.end)

    # Build labels — use first stock's daily data for label direction
    # For ensemble, we use binary labels: top 20% = 1 (buy), rest = 0
    from src.features.daily import DailyFeatureBuilder as DFB
    import pandas as pd
    import numpy as np

    all_labels = []
    builder = DFB()
    for code in symbols:
        df = loader.load_daily(code, args.start, args.end)
        if df.empty or len(df) < 60:
            continue
        # Compute forward return
        close = df['close']
        fwd_ret = close.shift(-5) / close - 1
        # Binary label: top 20% = 1
        threshold = fwd_ret.quantile(0.80)
        labels = (fwd_ret >= threshold).astype(int)
        labels.name = code
        all_labels.append(labels)

    if not all_labels:
        print("No labels built")
        return

    label_panel = pd.concat(all_labels, axis=1)
    # Align with features index
    common_dates = features.index.intersection(label_panel.index)
    if len(common_dates) == 0:
        # Try aligning on date level
        features_flat = features.copy()
        features_flat['date'] = features_flat.index
        label_panel_flat = label_panel.copy()
        label_panel_flat['date'] = label_panel_flat.index
        # This is complex with MultiIndex, let's use a simpler approach
        print("Aligning features and labels...")
        # Stack labels to match feature MultiIndex
        y_all = label_panel.stack()
        y_all.index.names = ['date', 'code']
        common = features.index.intersection(y_all.index)
        X = features.loc[common]
        y = y_all.loc[common]
    else:
        X = features.loc[common_dates]
        y = label_panel.loc[common_dates].stack()
        y.index.names = ['date', 'code']

    print(f"Samples: {len(X):,}, features: {X.shape[1]}")

    # Split
    n = len(X)
    split = int(n * 0.8)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    print(f"Train: {len(X_train):,}, Test: {len(X_test):,}")

    # Train
    model = EnsembleModel()
    model.fit(X_train, y_train)

    # Evaluate
    print("\n--- Evaluation ---")
    metrics = model.evaluate(X_test, y_test)

    # Save
    date_str = datetime.now().strftime('%Y%m%d')
    model_path = PATHS["model_dir"] / f"ensemble_{date_str}.pkl"
    report_path = PATHS["model_dir"] / f"ensemble_{date_str}_report.json"

    model.save(str(model_path))
    report_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"\nModel: {model_path}")
    print(f"Report: {report_path}")


def cmd_train_kronos(args):
    """Kronos 特征 + 截面模型训练"""
    from src.data.loader import DataLoader
    from src.features.cross_sectional import build_cross_sectional_features
    from src.labels.ranking import CrossSectionalLabelBuilder
    from src.models.lgbm_model import CrossSectionalModel
    from config.settings import PATHS

    loader = DataLoader()
    symbols = loader.get_available_symbols(min_bars=args.min_bars)[:args.max_stocks]

    if not symbols:
        print("No symbols available")
        return

    print(f"Kronos training pool: {len(symbols)} stocks")

    multi_df = loader.load_multi_minute(symbols, args.start, args.end, freq="5min")
    if multi_df.empty:
        print("No minute data")
        return

    print(f"Data: {len(multi_df):,} rows, {multi_df.index.get_level_values('code').nunique()} stocks")

    datetimes = multi_df.index.get_level_values('datetime').unique()
    n = len(datetimes)
    train_end = int(n * 0.7)
    test_start = int(n * 0.85)

    train_dts = datetimes[:train_end]
    test_dts = datetimes[test_start:]

    print(f"Train: {train_dts[0]} ~ {train_dts[-1]}")
    print(f"Test:  {test_dts[0]} ~ {test_dts[-1]}")

    print("\nBuilding Kronos features...")
    X_all = build_cross_sectional_features(
        multi_df,
        use_kronos=True,
        kronos_window=args.window,
        kronos_device=args.device,
    )

    print("Building labels...")
    label_builder = CrossSectionalLabelBuilder(forward_window=48, top_pct=0.20)
    y_all = label_builder.build(multi_df)

    common = X_all.index.intersection(y_all.index)
    X_all = X_all.loc[common]
    y_all = y_all.loc[common]

    tr_mask = X_all.index.get_level_values('datetime').isin(train_dts)
    model = CrossSectionalModel(top_k=args.top_k, confidence_threshold=args.threshold)
    model.fit(X_all[tr_mask], y_all[tr_mask])

    te_mask = X_all.index.get_level_values('datetime').isin(test_dts)
    metrics = model.evaluate(X_all[te_mask], y_all[te_mask])

    from datetime import datetime as dt
    out_path = PATHS["model_dir"] / f"kronos_cs_{dt.now():%Y%m%d}.pkl"
    model.save(str(out_path))

    report_path = PATHS["model_dir"] / "kronos_cs_report.json"
    report_path.write_text(json.dumps(metrics, indent=2, default=str))
    print(f"\nModel: {out_path}")
    print(f"Report: {report_path}")
