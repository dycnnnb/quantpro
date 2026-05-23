"""
回测报告生成
"""

import json
from pathlib import Path
from datetime import datetime

import pandas as pd


def save_report(report: dict, trades: pd.DataFrame, equity: pd.DataFrame,
                output_dir: str = "data/results"):
    """保存回测报告到文件"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON report
    report_path = out / f"backtest_{ts}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False))

    # Trades CSV
    if not trades.empty:
        trades_path = out / f"trades_{ts}.csv"
        trades.to_csv(trades_path, index=False)

    # Equity CSV
    if not equity.empty:
        equity_path = out / f"equity_{ts}.csv"
        equity.to_csv(equity_path, index=False)

    print(f"Report saved: {report_path}")
    return report_path
