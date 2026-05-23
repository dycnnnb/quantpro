from __future__ import annotations

import argparse
import json
import logging
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from config.settings import PATHS, DB
from src.data.loader import DataLoader
from src.strategy.position import Position, PositionManager
from src.strategy.risk import RiskController
from src.strategy.signals import generate_signals, rank_select
from src.strategy.regime import RegimeDetector, MarketRegime
from src.features.cs_features import (
    ALL_FEATURES, build_features, zscore_cross_section,
)

CONFIG: Dict = {
    "start_date": "2023-01-01",
    "end_date": "2024-12-31",
    "initial_capital": 1_000_000,
    "max_positions": 10,
    "hold_days": 5,
    "top_k": 10,
    "position_size_pct": 0.09,
    "min_shares": 100,
    "signal_threshold": 0.55,
    "stop_loss_pct": 0.05,
    "portfolio_loss_pct": 0.03,
    "bear_scale": 0.5,
    "commission_buy": 0.0003,
    "commission_sell": 0.0003,
    "stamp_duty": 0.0005,
    "slippage": 0.0001,
    "model_path": None,
    "score_col": "buy_prob",
    "feature_cols": ALL_FEATURES,
    "feature_window": 120,
    "cache_dir": PATHS["cache_dir"],
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def calc_buy_cost(price: float, shares: int, cfg: Dict) -> float:
    exec_price = price * (1 + cfg["slippage"])
    commission = exec_price * shares * cfg["commission_buy"]
    return exec_price * shares + commission


def calc_sell_revenue(price: float, shares: int, cfg: Dict) -> float:
    exec_price = price * (1 - cfg["slippage"])
    cost_rate = cfg["commission_sell"] + cfg["stamp_duty"]
    deduction = exec_price * shares * cost_rate
    return exec_price * shares - deduction


def calc_buy_exec_price(price: float, cfg: Dict) -> float:
    return price * (1 + cfg["slippage"])


def calc_sell_exec_price(price: float, cfg: Dict) -> float:
    return price * (1 - cfg["slippage"])


def load_model(model_path: Optional[str]):
    if model_path:
        path = Path(model_path)
    else:
        model_dir = Path(PATHS["model_dir"])
        candidates = sorted(model_dir.glob("cs_lgbm_*.pkl"))
        if not candidates:
            raise FileNotFoundError(
                f"model_dir={model_dir} 下未找到 cs_lgbm_*.pkl，"
                "请先运行 train_cs_model.py"
            )
        path = candidates[-1]

    logger.info("加载模型: %s", path)
    return joblib.load(path)


class FeatureSnapshot:

    def __init__(self, full_df: pd.DataFrame, cfg: Dict):
        self.df = full_df
        self.cfg = cfg
        self._cache: Dict[pd.Timestamp, pd.DataFrame] = {}

    def get(self, trade_date: pd.Timestamp) -> pd.DataFrame:
        if trade_date in self._cache:
            return self._cache[trade_date]

        snap = self.df[self.df["date"] == trade_date].copy()
        if snap.empty:
            return snap

        snap = zscore_cross_section(
            snap,
            feature_cols=self.cfg["feature_cols"],
            clip=3.0,
        )
        self._cache[trade_date] = snap
        return snap


class BacktestEngine:

    def __init__(self, cfg: Dict, model, full_df: pd.DataFrame):
        self.cfg = cfg
        self.model = model
        self.mgr = PositionManager(
            initial_capital=cfg["initial_capital"],
            max_positions=cfg["max_positions"],
        )
        self.rc = RiskController()
        self.regime = RegimeDetector()
        self.snap = FeatureSnapshot(full_df, cfg)
        self.full_df = full_df

        self.equity_curve: List[Tuple[pd.Timestamp, float]] = []
        self.trade_log: List[Dict] = []
        self.hold_counter: Dict[str, int] = {}

    def run(self, trade_dates: List[pd.Timestamp]) -> Dict:
        logger.info("回测开始: %s ~ %s", trade_dates[0].date(), trade_dates[-1].date())

        for today in trade_dates:
            self._step(today)

        last_date = trade_dates[-1]
        self._force_close_all(last_date)

        return self._calc_performance(trade_dates)

    def _step(self, today: pd.Timestamp):
        snap = self.snap.get(today)
        if snap.empty:
            self._record_equity(today)
            return

        price_map = snap.set_index("code")["close"].to_dict()

        blocked, reason = self.rc.check_portfolio(self.mgr)
        if blocked:
            logger.info("%s 组合风控触发: %s，全部平仓", today.date(), reason)
            self._close_all_positions(today, price_map, reason)
            self._record_equity(today)
            return

        self._check_and_close_positions(today, price_map)

        regime = self.regime.detect()
        scale = self.regime.get_position_scale()
        if regime == MarketRegime.BEAR:
            scale = min(scale, self.cfg["bear_scale"])
            logger.info("%s BEAR 市场，仓位系数: %.2f", today.date(), scale)

        candidates = self._generate_candidates(snap, today, scale)

        if candidates:
            self._open_positions(today, candidates, price_map, scale)

        self._record_equity(today)

    def _check_and_close_positions(
        self, today: pd.Timestamp, price_map: Dict[str, float]
    ):
        codes_to_close: List[Tuple[str, str]] = []

        for code, pos in list(self.mgr.positions.items()):
            current_price = price_map.get(code)
            if current_price is None:
                continue

            should_close, reason = self.rc.check_position(pos, current_price, today)
            if should_close:
                codes_to_close.append((code, reason))
                continue

            self.hold_counter[code] = self.hold_counter.get(code, 0) + 1
            if self.hold_counter[code] >= self.cfg["hold_days"]:
                codes_to_close.append((code, "到期平仓"))

        for code, reason in codes_to_close:
            if code not in self.mgr.positions:
                continue
            exec_price = calc_sell_exec_price(price_map[code], self.cfg)
            pnl = self.mgr.close_position(code, exec_price, reason=reason)
            self.hold_counter.pop(code, None)
            self._log_trade("sell", code, exec_price, None, reason, pnl)

    def _close_all_positions(
        self, today: pd.Timestamp, price_map: Dict[str, float], reason: str
    ):
        for code in list(self.mgr.positions.keys()):
            price = price_map.get(code, 0)
            if price <= 0:
                continue
            exec_price = calc_sell_exec_price(price, self.cfg)
            pnl = self.mgr.close_position(code, exec_price, reason=reason)
            self.hold_counter.pop(code, None)
            self._log_trade("sell", code, exec_price, None, reason, pnl)

    def _force_close_all(self, last_date: pd.Timestamp):
        snap = self.snap.get(last_date)
        price_map = snap.set_index("code")["close"].to_dict() if not snap.empty else {}
        self._close_all_positions(last_date, price_map, "回测结束平仓")

    def _generate_candidates(
        self,
        snap: pd.DataFrame,
        today: pd.Timestamp,
        scale: float,
    ) -> List[Dict]:
        feat = self.cfg["feature_cols"]
        avail_feat = [c for c in feat if c in snap.columns]

        X = snap[avail_feat].fillna(0).values
        try:
            proba = self.model.predict_proba(X)
            snap = snap.copy()
            snap["buy_prob"] = proba[:, 2]
        except Exception as exc:
            logger.error("模型预测失败: %s", exc)
            return []

        scores_df = snap.set_index("code")[[self.cfg["score_col"]]].rename(
            columns={self.cfg["score_col"]: "score"}
        )
        signals = generate_signals(
            scores_df,
            threshold=self.cfg["signal_threshold"],
            top_k=self.cfg["top_k"],
        )
        if signals.empty:
            return []

        candidates = rank_select(scores_df, today, top_k=self.cfg["top_k"])

        held = set(self.mgr.positions.keys())
        candidates = [c for c in candidates if c["code"] not in held]

        free_slots = self.cfg["max_positions"] - len(self.mgr.positions)
        return candidates[:free_slots]

    def _open_positions(
        self,
        today: pd.Timestamp,
        candidates: List[Dict],
        price_map: Dict[str, float],
        scale: float,
    ):
        available_cash = self.mgr.equity * scale * self.cfg["position_size_pct"]

        for c in candidates:
            code = c["code"]
            price = price_map.get(code)
            if not price or price <= 0:
                continue

            exec_price = calc_buy_exec_price(price, self.cfg)
            shares = int(available_cash / exec_price / 100) * 100
            if shares < self.cfg["min_shares"]:
                continue

            actual_cost = calc_buy_cost(price, shares, self.cfg)
            if actual_cost > self.mgr.equity * 0.95:
                continue

            stop_loss = exec_price * (1 - self.cfg["stop_loss_pct"])
            pos = self.mgr.open_position(
                code=code,
                price=exec_price,
                shares=shares,
                stop_loss=stop_loss,
            )
            if pos:
                self.hold_counter[code] = 0
                self._log_trade(
                    "buy", code, exec_price, pos,
                    "信号买入", None,
                    score=c.get("buy_score", 0),
                )

    def _record_equity(self, today: pd.Timestamp):
        self.equity_curve.append((today, self.mgr.equity))

    def _log_trade(
        self,
        action: str,
        code: str,
        price: float,
        pos: Optional[Position],
        reason: str,
        pnl: Optional[float],
        score: float = 0.0,
    ):
        self.trade_log.append({
            "action": action,
            "code": code,
            "price": round(price, 4),
            "shares": pos.shares if pos else 0,
            "reason": reason,
            "pnl": round(pnl, 2) if pnl is not None else None,
            "score": round(score, 4),
        })

    def _calc_performance(self, trade_dates: List[pd.Timestamp]) -> Dict:
        if not self.equity_curve:
            return {}

        equity_df = pd.DataFrame(
            self.equity_curve, columns=["date", "equity"]
        ).set_index("date")
        equity = equity_df["equity"]
        init_cap = self.cfg["initial_capital"]

        n_years = len(trade_dates) / 252.0
        total_ret = (equity.iloc[-1] - init_cap) / init_cap
        cagr = (1 + total_ret) ** (1 / max(n_years, 1e-9)) - 1

        daily_ret = equity.pct_change().dropna()
        sharpe = (
            daily_ret.mean() / daily_ret.std(ddof=1) * np.sqrt(252)
            if daily_ret.std(ddof=1) > 1e-9 else 0.0
        )

        roll_max = equity.cummax()
        drawdown = (equity - roll_max) / roll_max
        max_drawdown = float(drawdown.min())

        closed_pnls = [
            t["pnl"] for t in self.trade_log
            if t["action"] == "sell" and t["pnl"] is not None
        ]
        win_pnls = [p for p in closed_pnls if p > 0]
        loss_pnls = [p for p in closed_pnls if p < 0]
        win_rate = len(win_pnls) / max(len(closed_pnls), 1)
        avg_win = np.mean(win_pnls) if win_pnls else 0.0
        avg_loss = np.mean(loss_pnls) if loss_pnls else 0.0
        pnl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

        buy_trades = [t for t in self.trade_log if t["action"] == "buy"]
        total_turnover = sum(t["price"] * t["shares"] for t in buy_trades)
        avg_equity = float(equity.mean())
        turnover_annual = (
            total_turnover / avg_equity / n_years * 2
            if avg_equity > 0 else 0.0
        )

        report = {
            "cagr": round(float(cagr), 4),
            "total_return": round(float(total_ret), 4),
            "sharpe": round(float(sharpe), 4),
            "max_drawdown": round(float(max_drawdown), 4),
            "win_rate": round(float(win_rate), 4),
            "pnl_ratio": round(float(pnl_ratio), 4),
            "turnover_annual": round(float(turnover_annual), 4),
            "total_trades": len(closed_pnls),
            "final_equity": round(float(equity.iloc[-1]), 2),
            "initial_capital": init_cap,
        }

        logger.info("=" * 55)
        logger.info("回测绩效报告")
        logger.info("  CAGR          : %+.2f%%", report["cagr"] * 100)
        logger.info("  总收益         : %+.2f%%", report["total_return"] * 100)
        logger.info("  年化 Sharpe   : %.2f", report["sharpe"])
        logger.info("  最大回撤       : %.2f%%", report["max_drawdown"] * 100)
        logger.info("  胜率           : %.2f%%", report["win_rate"] * 100)
        logger.info("  盈亏比         : %.2f", report["pnl_ratio"])
        logger.info("  年化换手率      : %.1fx", report["turnover_annual"])
        logger.info("  总交易次数      : %d", report["total_trades"])
        logger.info("  最终资金        : %.0f", report["final_equity"])
        logger.info("=" * 55)

        return report


def generate_daily_picks(
    snap: pd.DataFrame,
    model,
    cfg: Dict,
    trade_date: str,
) -> List[Dict]:
    feat = cfg["feature_cols"]
    avail_feat = [c for c in feat if c in snap.columns]
    X = snap[avail_feat].fillna(0).values

    proba = model.predict_proba(X)
    snap = snap.copy()
    snap["buy_prob"] = proba[:, 2]
    snap["signal"] = np.where(snap["buy_prob"] >= cfg["signal_threshold"], "buy", "hold")

    picked = (
        snap[snap["signal"] == "buy"]
        .nlargest(cfg["top_k"], "buy_prob")
        [["code", "buy_prob", "signal"]]
        .rename(columns={"buy_prob": "final_score"})
    )

    picks = []
    for _, row in picked.iterrows():
        picks.append({
            "code": row["code"],
            "name": "",
            "final_score": round(float(row["final_score"]), 4),
            "signal": row["signal"],
        })

    output = {"date": trade_date, "picks": picks}

    cache_dir = Path(cfg["cache_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / "daily_picks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("daily_picks.json 已生成: %d 只股票  -> %s", len(picks), out_path)
    return picks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="截面选股策略回测")
    parser.add_argument("--start", type=str, default=CONFIG["start_date"])
    parser.add_argument("--end", type=str, default=CONFIG["end_date"])
    parser.add_argument("--capital", type=float, default=CONFIG["initial_capital"])
    parser.add_argument("--model", type=str, default=None, help="模型路径（默认自动最新）")
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = CONFIG.copy()
    cfg["start_date"] = args.start
    cfg["end_date"] = args.end
    cfg["initial_capital"] = args.capital
    cfg["model_path"] = args.model

    logger.info("=" * 60)
    logger.info("多因子截面选股策略  %s ~ %s", cfg["start_date"], cfg["end_date"])
    logger.info("初始资金: %.0f  最大持仓: %d", cfg["initial_capital"], cfg["max_positions"])
    logger.info("=" * 60)

    model = load_model(cfg["model_path"])

    dl = DataLoader()
    symbols = dl.get_daily_symbols(min_days=cfg["feature_window"])

    extend_start = (
        datetime.strptime(cfg["start_date"], "%Y-%m-%d")
        - timedelta(days=int(cfg["feature_window"] * 1.5))
    ).strftime("%Y-%m-%d")

    logger.info("加载日线数据（%d 标的）...", len(symbols))
    raw = dl.load_multi_daily(symbols, extend_start, cfg["end_date"])
    raw = raw.reset_index()
    if "symbol" in raw.columns and "code" not in raw.columns:
        raw = raw.rename(columns={"symbol": "code"})

    logger.info("构建特征 ...")
    full_df = build_features(raw)
    full_df["date"] = pd.to_datetime(full_df["date"])
    full_df = full_df.sort_values(["date", "code"]).reset_index(drop=True)

    bt_start = pd.Timestamp(cfg["start_date"])
    bt_end = pd.Timestamp(cfg["end_date"])
    all_dates = sorted(full_df["date"].unique())
    trade_dates = [d for d in all_dates if bt_start <= d <= bt_end]
    logger.info("回测交易日: %d 天", len(trade_dates))

    engine = BacktestEngine(cfg, model, full_df)
    report = engine.run(trade_dates)

    cache_dir = Path(cfg["cache_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    report_path = cache_dir / "backtest_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            {"config": {k: v for k, v in cfg.items() if k != "feature_cols"},
             "metrics": report,
             "trade_count": len(engine.trade_log)},
            f, ensure_ascii=False, indent=2,
        )
    logger.info("回测报告保存: %s", report_path)

    today_snap = engine.snap.get(trade_dates[-1])
    if not today_snap.empty:
        today_snap_zs = zscore_cross_section(
            today_snap, feature_cols=cfg["feature_cols"]
        )
        generate_daily_picks(
            today_snap_zs, model, cfg,
            trade_date=str(trade_dates[-1].date()),
        )


if __name__ == "__main__":
    main()
