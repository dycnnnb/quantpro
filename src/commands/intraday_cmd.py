"""
日内五分钟线策略 CLI 命令
"""

import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def cmd_intraday_backtest(args):
    """运行日内回测"""
    from src.data.loader import DataLoader
    from src.features.intraday_features import IntradayFeatureEngineer
    from src.labels.intraday_labels import IntradayLabelBuilder
    from src.strategy.intraday_strategy import (
        IntradayStrategy, IntradayRiskController, IntradaySignalGenerator
    )
    from src.backtest.intraday_backtest import IntradayBacktestEngine

    symbol = getattr(args, 'symbol', '000001')
    start = getattr(args, 'start', '2024-01-01')
    end = getattr(args, 'end', '2024-12-31')
    capital = getattr(args, 'capital', 500000)
    use_ml = getattr(args, 'use_ml', False)
    output = getattr(args, 'output', 'data/reports')

    print(f"开始日内回测: {symbol} [{start} ~ {end}]")

    loader = DataLoader()
    df = loader.load_minute(symbol, start, end, freq="5min")

    if df is None or df.empty:
        print(f"无法加载数据: {symbol}")
        return

    print(f"数据加载完成: {len(df)} 根K线")

    feature_eng = IntradayFeatureEngineer()
    label_builder = IntradayLabelBuilder(forward_bars=6, take_profit=0.008, stop_loss=0.004)
    risk_ctrl = IntradayRiskController(
        max_positions=3, max_daily_loss=0.02,
        max_single_loss=0.004, position_size_pct=0.30,
        trailing_stop_ratio=0.003,
    )
    signal_gen = IntradaySignalGenerator(ml_threshold=0.6, use_ml=use_ml)
    strategy = IntradayStrategy(
        capital=capital, risk_ctrl=risk_ctrl, signal_gen=signal_gen,
        max_hold_bars=24,
    )

    engine = IntradayBacktestEngine(feature_eng, label_builder)
    metrics = engine.run(df, symbol, output_dir=Path(output))

    print(f"\n回测完成！报告保存至: {output}")
    print(f"  总收益率: {metrics.get('total_return', 0):.2%}")
    print(f"  最大回撤: {metrics.get('max_drawdown', 0):.2%}")
    print(f"  Sharpe:   {metrics.get('sharpe', 0):.2f}")


def cmd_intraday_info(args):
    """查看日内策略信息"""
    from src.features.intraday_features import IntradayFeatureEngineer
    from src.strategy.intraday_strategy import IntradayRiskController

    eng = IntradayFeatureEngineer()
    features = eng.get_feature_names()
    print(f"日内特征数量: {len(features)}")
    print(f"特征列表: {', '.join(features[:10])}...")

    risk = IntradayRiskController()
    print(f"\n风控参数:")
    print(f"  最大持仓数: {risk.max_positions}")
    print(f"  单日最大亏损: {risk.max_daily_loss:.1%}")
    print(f"  单笔止损: {risk.max_single_loss:.1%}")
    print(f"  单仓占比: {risk.position_size_pct:.0%}")
    print(f"  移动止损: {risk.trailing_stop_ratio:.1%}")
