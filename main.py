#!/usr/bin/env python
"""
量化交易系统 — 统一入口

用法:
  python main.py data update              # 更新行情数据
  python main.py data info                # 查看数据概况
  python main.py train single --symbol 000001   # 单股票训练
  python main.py train cs                 # 截面模型训练
  python main.py backtest single --symbol 000001 # 单股票回测
  python main.py backtest cs --model models/cs_model.pkl  # 截面回测
  python main.py trade run                # 每日模拟交易
  python main.py trade run --dry-run      # 模拟运行（不执行）
  python main.py trade status             # 查看持仓
  python main.py trade history            # 查看交易历史
  python main.py serve                    # 启动 Web 服务
  python main.py diagnose                 # 系统诊断
  python main.py config show              # 显示配置
"""

import sys
import argparse
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="quant",
        description="量化交易系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # ── data ──────────────────────────────────────────────────────
    data_p = sub.add_parser("data", help="数据管理")
    data_sub = data_p.add_subparsers(dest="action")

    data_update = data_sub.add_parser("update", help="更新行情数据")
    data_update.add_argument("--type", default="all", choices=["daily", "minute", "monthly", "all"])
    data_update.add_argument("--minute", type=int, default=5, choices=[5, 15, 30, 60])
    data_update.add_argument("--days", type=int, default=1095, help="历史天数")
    data_update.add_argument("--limit", type=int, default=0, help="限制股票数量 (0=全部)")

    data_info = data_sub.add_parser("info", help="查看数据概况")

    data_merge = data_sub.add_parser("merge", help="合并数据库")
    data_merge.add_argument("--source", required=True)
    data_merge.add_argument("--target", required=True)

    # ── train ─────────────────────────────────────────────────────
    train_p = sub.add_parser("train", help="模型训练")
    train_sub = train_p.add_subparsers(dest="mode")

    train_single = train_sub.add_parser("single", help="单股票训练")
    train_single.add_argument("--symbol", default="000001")
    train_single.add_argument("--start", default="2020-01-01")
    train_single.add_argument("--end", default="2025-12-31")
    train_single.add_argument("--threshold", type=float, default=0.50)

    train_cs = train_sub.add_parser("cs", help="截面模型训练")
    train_cs.add_argument("--start", default="2023-01-01")
    train_cs.add_argument("--end", default="2025-12-31")
    train_cs.add_argument("--min-bars", type=int, default=10000)
    train_cs.add_argument("--max-stocks", type=int, default=100)
    train_cs.add_argument("--top-k", type=int, default=5)
    train_cs.add_argument("--threshold", type=float, default=0.55)

    train_ens = train_sub.add_parser("ensemble", help="集成模型训练")
    train_ens.add_argument("--start", default="2020-01-01")
    train_ens.add_argument("--end", default="2025-12-31")
    train_ens.add_argument("--max-stocks", type=int, default=50)

    train_kronos = train_sub.add_parser("kronos", help="Kronos 特征 + 截面训练")
    train_kronos.add_argument("--start", default="2023-01-01")
    train_kronos.add_argument("--end", default="2025-12-31")
    train_kronos.add_argument("--min-bars", type=int, default=10000)
    train_kronos.add_argument("--max-stocks", type=int, default=50)
    train_kronos.add_argument("--top-k", type=int, default=5)
    train_kronos.add_argument("--threshold", type=float, default=0.55)
    train_kronos.add_argument("--window", type=int, default=48, help="Kronos 滑动窗口大小")
    train_kronos.add_argument("--device", default="cpu", choices=["cpu", "cuda:0"])

    # ── backtest ──────────────────────────────────────────────────
    bt_p = sub.add_parser("backtest", help="回测")
    bt_sub = bt_p.add_subparsers(dest="mode")

    bt_single = bt_sub.add_parser("single", help="单股票回测")
    bt_single.add_argument("--symbol", default="000001")
    bt_single.add_argument("--start", default="2023-01-01")
    bt_single.add_argument("--end", default="2025-12-31")
    bt_single.add_argument("--model", default=None, help="模型路径")
    bt_single.add_argument("--capital", type=float, default=100000)
    bt_single.add_argument("--stop-loss", type=float, default=0.03)
    bt_single.add_argument("--top-k", type=int, default=5)

    bt_cs = bt_sub.add_parser("cs", help="截面回测")
    bt_cs.add_argument("--start", default="2023-06-01")
    bt_cs.add_argument("--end", default="2025-12-31")
    bt_cs.add_argument("--model", required=True, help="模型路径")
    bt_cs.add_argument("--min-bars", type=int, default=10000)
    bt_cs.add_argument("--max-stocks", type=int, default=100)
    bt_cs.add_argument("--capital", type=float, default=100000)
    bt_cs.add_argument("--stop-loss", type=float, default=0.03)
    bt_cs.add_argument("--top-k", type=int, default=5)

    # ── trade ─────────────────────────────────────────────────────
    trade_p = sub.add_parser("trade", help="模拟交易")
    trade_sub = trade_p.add_subparsers(dest="action")

    trade_run = trade_sub.add_parser("run", help="执行每日交易")
    trade_run.add_argument("--dry-run", action="store_true", help="模拟运行，不执行")

    trade_sub.add_parser("status", help="查看持仓")

    trade_hist = trade_sub.add_parser("history", help="交易历史")
    trade_hist.add_argument("--limit", type=int, default=20)

    # ── serve ─────────────────────────────────────────────────────
    serve_p = sub.add_parser("serve", help="启动 Web 服务")
    serve_p.add_argument("--host", default="0.0.0.0")
    serve_p.add_argument("--port", type=int, default=5000)
    serve_p.add_argument("--debug", action="store_true")

    # ── diagnose ──────────────────────────────────────────────────
    sub.add_parser("diagnose", help="系统诊断")

    # ── config ────────────────────────────────────────────────────
    cfg_p = sub.add_parser("config", help="配置管理")
    cfg_sub = cfg_p.add_subparsers(dest="action")
    cfg_sub.add_parser("show", help="显示当前配置")

    # ── news ──────────────────────────────────────────────────────
    news_p = sub.add_parser("news", help="新闻因子分析")
    news_sub = news_p.add_subparsers(dest="action")

    news_fetch = news_sub.add_parser("fetch", help="抓取新闻")
    news_fetch.add_argument("--sources", default=None, help="RSS 源 (逗号分隔)")

    news_analyze = news_sub.add_parser("analyze", help="分析新闻因子")
    news_analyze.add_argument("--batch-size", type=int, default=5)
    news_analyze.add_argument("--limit", type=int, default=0, help="限制分析数量 (0=全部)")

    # ── pick ──────────────────────────────────────────────────────
    pick_p = sub.add_parser("pick", help="每日选股（模型+新闻Agent）")
    pick_p.add_argument("--top-n", type=int, default=20, help="选股数量")
    pick_p.add_argument("--no-news", action="store_true", help="跳过新闻分析")

    # ── intraday ──────────────────────────────────────────────────
    intra_p = sub.add_parser("intraday", help="日内五分钟线策略")
    intra_sub = intra_p.add_subparsers(dest="action")

    intra_bt = intra_sub.add_parser("backtest", help="日内回测")
    intra_bt.add_argument("--symbol", default="000001")
    intra_bt.add_argument("--start", default="2024-01-01")
    intra_bt.add_argument("--end", default="2024-12-31")
    intra_bt.add_argument("--capital", type=float, default=500000)
    intra_bt.add_argument("--use-ml", action="store_true", default=False)
    intra_bt.add_argument("--output", default="data/reports")

    intra_sub.add_parser("info", help="查看策略信息")

    return parser


def cmd_pick(args):
    """每日选股流水线"""
    from src.strategy.daily_pick import DailyPickPipeline
    pipeline = DailyPickPipeline()
    result = pipeline.run()
    if not result.get('success'):
        print(f"Failed: {result.get('error')}")
        sys.exit(1)


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    from src.commands import data_cmd, train_cmd, backtest_cmd, trade_cmd, system_cmd, news_cmd, intraday_cmd

    dispatch = {
        ("data", "update"):     data_cmd.cmd_data_update,
        ("data", "info"):       data_cmd.cmd_data_info,
        ("data", "merge"):      data_cmd.cmd_data_merge,
        ("train", "single"):    train_cmd.cmd_train_single,
        ("train", "cs"):        train_cmd.cmd_train_cs,
        ("train", "ensemble"):  train_cmd.cmd_train_ensemble,
        ("train", "kronos"):    train_cmd.cmd_train_kronos,
        ("backtest", "single"): backtest_cmd.cmd_backtest_single,
        ("backtest", "cs"):     backtest_cmd.cmd_backtest_cs,
        ("trade", "run"):       trade_cmd.cmd_trade_run,
        ("trade", "status"):    trade_cmd.cmd_trade_status,
        ("trade", "history"):   trade_cmd.cmd_trade_history,
        ("serve", None):        system_cmd.cmd_serve,
        ("diagnose", None):     system_cmd.cmd_diagnose,
        ("config", "show"):     system_cmd.cmd_config_show,
        ("news", "fetch"):      news_cmd.cmd_news_fetch,
        ("news", "analyze"):    news_cmd.cmd_news_analyze,
        ("pick", None):         cmd_pick,
        ("intraday", "backtest"): intraday_cmd.cmd_intraday_backtest,
        ("intraday", "info"):     intraday_cmd.cmd_intraday_info,
    }

    key = (args.command, getattr(args, 'mode', None) or getattr(args, 'action', None))
    handler = dispatch.get(key)

    if handler is None:
        parser.print_help()
        return

    handler(args)


if __name__ == "__main__":
    main()
