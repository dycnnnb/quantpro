"""
日内回测引擎 + 绩效分析
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict
import logging
import json

logger = logging.getLogger(__name__)


class IntradayBacktestEngine:

    def __init__(self, strategy, feature_engineer, label_builder=None):
        self.strategy = strategy
        self.feature_engineer = feature_engineer
        self.label_builder = label_builder

    def run(self, raw_df: pd.DataFrame, symbol: str, output_dir: Path = None) -> Dict:
        logger.info(f"{'=' * 50}")
        logger.info(f"开始回测: {symbol}")

        df = self.feature_engineer.compute(raw_df)
        feature_cols = self.feature_engineer.get_feature_names()
        feature_cols = [c for c in feature_cols if c in df.columns]

        result_df = self.strategy.run(df, feature_cols, symbol)
        metrics = self._calc_metrics(symbol)

        if output_dir:
            self._save_report(metrics, result_df, output_dir, symbol)

        return metrics

    def _calc_metrics(self, symbol: str) -> Dict:
        trades = self.strategy.trades
        equity = self.strategy.equity_curve
        init_cap = self.strategy.initial_cap

        if not trades:
            logger.warning("无交易记录")
            return {'symbol': symbol, 'total_trades': 0}

        df_trades = pd.DataFrame([
            {
                'symbol': t.symbol, 'entry': t.entry_price, 'exit': t.exit_price,
                'entry_time': t.entry_time, 'exit_time': t.exit_time,
                'pnl': t.pnl, 'pnl_pct': t.pnl_pct,
                'reason': t.exit_reason, 'hold_bars': t.hold_bars,
            }
            for t in trades
        ])

        total_trades = len(df_trades)
        win_trades = df_trades[df_trades['pnl'] > 0]
        loss_trades = df_trades[df_trades['pnl'] <= 0]

        win_rate = len(win_trades) / total_trades if total_trades else 0
        avg_win = win_trades['pnl_pct'].mean() if len(win_trades) else 0
        avg_loss = loss_trades['pnl_pct'].mean() if len(loss_trades) else 0
        profit_factor = (
            win_trades['pnl'].sum() / abs(loss_trades['pnl'].sum())
            if len(loss_trades) > 0 and loss_trades['pnl'].sum() != 0
            else np.inf
        )

        equity_series = pd.Series(equity)
        total_return = (equity_series.iloc[-1] - init_cap) / init_cap

        rolling_max = equity_series.cummax()
        drawdown = (equity_series - rolling_max) / rolling_max
        max_drawdown = drawdown.min()

        bar_returns = equity_series.pct_change().dropna()
        sharpe = (
            bar_returns.mean() / bar_returns.std() * np.sqrt(252 * 48)
            if bar_returns.std() > 0 else 0
        )

        calmar = total_return / abs(max_drawdown) if max_drawdown != 0 else 0

        exit_dist = df_trades['reason'].value_counts().to_dict()

        metrics = {
            'symbol': symbol,
            'total_trades': total_trades,
            'win_rate': round(win_rate, 4),
            'avg_win_pct': round(avg_win, 4),
            'avg_loss_pct': round(avg_loss, 4),
            'profit_factor': round(profit_factor, 2),
            'total_return': round(total_return, 4),
            'max_drawdown': round(max_drawdown, 4),
            'sharpe': round(sharpe, 2),
            'calmar': round(calmar, 2),
            'final_capital': round(float(equity_series.iloc[-1]), 0),
            'exit_reasons': exit_dist,
            'equity_curve': [round(float(v), 2) for v in equity[::max(1, len(equity) // 200)]],
        }

        self._print_metrics(metrics)
        return metrics

    def _print_metrics(self, m: Dict):
        print("\n" + "=" * 50)
        print(f"回测结果 - {m['symbol']}")
        print("=" * 50)
        print(f"总交易次数:  {m['total_trades']}")
        print(f"胜率:        {m['win_rate']:.2%}")
        print(f"平均盈利:    {m['avg_win_pct']:.2%}")
        print(f"平均亏损:    {m['avg_loss_pct']:.2%}")
        print(f"盈亏比:      {m['profit_factor']:.2f}")
        print(f"总收益率:    {m['total_return']:.2%}")
        print(f"最大回撤:    {m['max_drawdown']:.2%}")
        print(f"Sharpe:      {m['sharpe']:.2f}")
        print(f"Calmar:      {m['calmar']:.2f}")
        print(f"最终资金:    {m['final_capital']:,.0f}")
        print(f"出场原因:    {m['exit_reasons']}")
        print("=" * 50 + "\n")

    def _save_report(self, metrics: Dict, df: pd.DataFrame, output_dir: Path, symbol: str):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        metrics_path = output_dir / f"intraday_{symbol}_metrics.json"
        with open(metrics_path, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2, default=str)

        if self.strategy.trades:
            trades_df = pd.DataFrame([vars(t) for t in self.strategy.trades])
            trades_path = output_dir / f"intraday_{symbol}_trades.csv"
            trades_df.to_csv(trades_path, index=False, encoding='utf-8-sig')

        logger.info(f"报告已保存至: {output_dir}")
