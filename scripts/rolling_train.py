"""
滚动化训练脚本 — GPU加速 + 低换手 + 最优模型选取

用法:
    python scripts/rolling_train.py
    python scripts/rolling_train.py --no-gpu
    python scripts/rolling_train.py --train-days 750 --valid-days 90
    python scripts/rolling_train.py --mode regression
    python scripts/rolling_train.py --freq minute   (使用5分钟线数据)
"""

import sys
import sqlite3
import warnings
import argparse
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import DB


# ═══════════════════════════════════════════════════════════════
# 1. 数据加载 — 高质量过滤
# ═══════════════════════════════════════════════════════════════

def load_stock_list(min_days: int = 250) -> list:
    conn = sqlite3.connect(str(DB["market"]))
    rows = conn.execute(
        "SELECT code FROM stock_kline "
        "GROUP BY code HAVING COUNT(*) >= ? "
        "AND code NOT LIKE '4%' AND code NOT LIKE '8%' "
        "ORDER BY code",
        (min_days,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def load_price_data(codes: list, start: str, end: str) -> pd.DataFrame:
    conn = sqlite3.connect(str(DB["market"]))
    placeholders = ",".join(["?"] * len(codes))
    df = pd.read_sql(
        f"SELECT code, date, open, high, low, close, volume, amount "
        f"FROM stock_kline WHERE code IN ({placeholders}) "
        f"AND date >= ? AND date <= ? ORDER BY code, date",
        conn, params=codes + [start, end]
    )
    conn.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index(["date", "code"])
    return df


def load_minute_stock_list(min_days: int = 100, top_n: int = 500) -> list:
    conn = sqlite3.connect(str(DB["market"]))
    rows = conn.execute(
        "SELECT code, SUM(volume) as total_vol FROM minute_kline "
        "WHERE code NOT LIKE '4%' AND code NOT LIKE '8%' "
        "GROUP BY code HAVING COUNT(DISTINCT date) >= ? "
        "ORDER BY total_vol DESC LIMIT ?",
        (min_days, top_n)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def load_minute_data(codes: list, start: str, end: str) -> pd.DataFrame:
    conn = sqlite3.connect(str(DB["market"]))
    placeholders = ",".join(["?"] * len(codes))
    df = pd.read_sql(
        f"SELECT code, date, time, open, high, low, close, volume "
        f"FROM minute_kline WHERE code IN ({placeholders}) "
        f"AND date >= ? AND date <= ? "
        f"ORDER BY code, date, time",
        conn, params=codes + [start, end]
    )
    conn.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df


def aggregate_minute_to_daily(minute_df: pd.DataFrame) -> pd.DataFrame:
    if minute_df.empty:
        return pd.DataFrame()
    daily = minute_df.groupby(["code", "date"]).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()
    daily = daily.set_index(["date", "code"])
    return daily


def build_intraday_features(minute_df: pd.DataFrame) -> pd.DataFrame:
    if minute_df.empty:
        return pd.DataFrame()
    all_feats = []
    for code in minute_df["code"].unique():
        stock_min = minute_df[minute_df["code"] == code].copy()
        if len(stock_min) < 200:
            continue
        stock_min = stock_min.sort_values(["date", "time"])
        grouped = stock_min.groupby("date")

        daily_feats = pd.DataFrame()
        daily_feats["open"] = grouped["open"].first()
        daily_feats["high"] = grouped["high"].max()
        daily_feats["low"] = grouped["low"].min()
        daily_feats["close"] = grouped["close"].last()
        daily_feats["volume"] = grouped["volume"].sum()

        daily_feats["intraday_range"] = (daily_feats["high"] - daily_feats["low"]) / (daily_feats["open"] + 1e-8)
        daily_feats["upper_shadow"] = (daily_feats["high"] - daily_feats[["open", "close"]].max(axis=1)) / (daily_feats["high"] - daily_feats["low"] + 1e-8)
        daily_feats["lower_shadow"] = (daily_feats[["open", "close"]].min(axis=1) - daily_feats["low"]) / (daily_feats["high"] - daily_feats["low"] + 1e-8)

        def _tail_momentum(g):
            if len(g) < 4:
                return 0.0
            tail = g.tail(4)
            return (tail["close"].iloc[-1] - tail["close"].iloc[0]) / (tail["close"].iloc[0] + 1e-8)

        daily_feats["tail_momentum"] = grouped.apply(_tail_momentum)

        def _open_gap(g):
            if len(g) < 2:
                return 0.0
            return (g["open"].iloc[0] - g["close"].iloc[-1]) / (g["close"].iloc[-1] + 1e-8)

        daily_feats["open_gap"] = grouped.apply(_open_gap)

        def _vol_concentration(g):
            if g["volume"].sum() == 0:
                return 0.0
            last_vol = g.tail(8)["volume"].sum()
            return last_vol / (g["volume"].sum() + 1e-8)

        daily_feats["vol_concentration"] = grouped.apply(_vol_concentration)

        def _vwap_dev(g):
            if g["volume"].sum() == 0:
                return 0.0
            vwap = (g["close"] * g["volume"]).sum() / (g["volume"].sum() + 1e-8)
            return (g["close"].iloc[-1] - vwap) / (vwap + 1e-8)

        daily_feats["vwap_deviation"] = grouped.apply(_vwap_dev)

        def _morning_vol_ratio(g):
            if len(g) < 8 or g["volume"].sum() == 0:
                return 1.0
            morning = g.head(8)["volume"].sum()
            return morning / (g["volume"].sum() + 1e-8)

        daily_feats["morning_vol_ratio"] = grouped.apply(_morning_vol_ratio)

        def _afternoon_vol_ratio(g):
            if len(g) < 8 or g["volume"].sum() == 0:
                return 1.0
            afternoon = g.tail(8)["volume"].sum()
            return afternoon / (g["volume"].sum() + 1e-8)

        daily_feats["afternoon_vol_ratio"] = grouped.apply(_afternoon_vol_ratio)

        def _intraday_reversal(g):
            if len(g) < 5:
                return 0.0
            first_ret = (g["close"].iloc[4] - g["open"].iloc[0]) / (g["open"].iloc[0] + 1e-8)
            last_ret = (g["close"].iloc[-1] - g["close"].iloc[-4]) / (g["close"].iloc[-4] + 1e-8)
            return last_ret - first_ret

        daily_feats["intraday_reversal"] = grouped.apply(_intraday_reversal)

        daily_feats["code"] = code
        all_feats.append(daily_feats)

    if not all_feats:
        return pd.DataFrame()
    panel = pd.concat(all_feats)
    panel = panel.reset_index()
    panel = panel.set_index(["date", "code"])
    panel = panel.replace([np.inf, -np.inf], np.nan)
    return panel


def filter_st_stocks(df: pd.DataFrame) -> pd.DataFrame:
    conn = sqlite3.connect(str(DB["market"]))
    rows = conn.execute(
        "SELECT code FROM stock_info WHERE name LIKE '%ST%' OR name LIKE '%*ST%'"
    ).fetchall()
    st_codes = {r[0] for r in rows}
    conn.close()
    mask = ~df.index.get_level_values("code").isin(st_codes)
    return df[mask]


# ═══════════════════════════════════════════════════════════════
# 2. 特征工程 — Alpha158 + 自定义因子 + 截面z-score标准化
# ═══════════════════════════════════════════════════════════════

def build_features(df: pd.DataFrame, use_alpha158: bool = True) -> pd.DataFrame:
    from src.features.qlib_alpha import Alpha158Builder

    alpha158 = Alpha158Builder()
    all_features = []

    for code in df.index.get_level_values("code").unique():
        stock_data = df.xs(code, level="code")
        if len(stock_data) < 60:
            continue

        close = stock_data["close"]
        high = stock_data["high"]
        low = stock_data["low"]
        volume = stock_data["volume"]
        open_ = stock_data["open"]

        f = pd.DataFrame(index=stock_data.index)

        if use_alpha158:
            a158 = alpha158.compute(stock_data)
            for col in a158.columns:
                f[col] = a158[col]

        high_60 = high.rolling(60).max()
        low_60 = low.rolling(60).min()
        f["price_position"] = (close - low_60) / (high_60 - low_60 + 1e-8)

        ma5 = close.rolling(5).mean()
        ma60 = close.rolling(60).mean()
        f["trend_strength"] = (ma5 - ma60) / (ma60 + 1e-8)

        f["reversal"] = -close.pct_change(20)

        low20 = low.rolling(20).min()
        f["dist_low"] = (close - low20) / (close + 1e-8)

        f["volatility"] = close.pct_change().rolling(20).std()

        vol_ma20 = volume.rolling(20).mean()
        f["volume_ratio"] = volume / (vol_ma20 + 1e-8)

        f["momentum_5"] = close.pct_change(5)
        f["momentum_20"] = close.pct_change(20)
        f["momentum_60"] = close.pct_change(60)

        vwap = close.rolling(20).mean()
        f["vwap_dev"] = (close - vwap) / (vwap + 1e-8)

        f["range_ratio"] = (high - low).rolling(20).mean() / (close + 1e-8)

        f["vol_shrink"] = volume / (volume.rolling(60).mean() + 1e-8)

        f["turnover_proxy"] = volume.pct_change(5).rolling(10).mean()

        f["skewness"] = close.pct_change().rolling(20).skew()

        f["kurtosis"] = close.pct_change().rolling(20).kurt()

        f["code"] = code
        all_features.append(f)

    panel = pd.concat(all_features)
    panel = panel.reset_index()
    panel = panel.rename(columns={panel.columns[0]: "date"})
    panel = panel.set_index(["date", "code"])

    panel = panel.replace([np.inf, -np.inf], np.nan)

    factor_cols = [c for c in panel.columns]
    for col in factor_cols:
        group = panel[col].groupby(level="date")
        mean = group.transform("mean")
        std = group.transform("std")
        panel[col] = ((panel[col] - mean) / (std + 1e-8)).fillna(0.0)

    return panel


# ═══════════════════════════════════════════════════════════════
# 3. 标签构建 — 二分类 + 回归
# ═══════════════════════════════════════════════════════════════

def build_labels(df: pd.DataFrame, forward_window: int = 10, top_pct: float = 0.15) -> pd.Series:
    close = df["close"]
    forward_ret = close.groupby(level="code").shift(-forward_window) / close - 1

    labels = pd.Series(np.nan, index=df.index, dtype=float)
    for dt in forward_ret.index.get_level_values("date").unique():
        try:
            dt_ret = forward_ret.loc[dt].dropna()
        except KeyError:
            continue
        if len(dt_ret) < 10:
            continue
        upper_q = dt_ret.quantile(1 - top_pct)
        lower_q = dt_ret.quantile(top_pct)
        for code, ret in dt_ret.items():
            if ret >= upper_q:
                labels.loc[(dt, code)] = 1
            elif ret <= lower_q:
                labels.loc[(dt, code)] = 0

    return labels


def build_regression_labels(df: pd.DataFrame, forward_window: int = 10) -> pd.Series:
    close = df["close"]
    forward_ret = close.groupby(level="code").shift(-forward_window) / close - 1
    return forward_ret


# ═══════════════════════════════════════════════════════════════
# 4. 模型配置 — GPU加速 + 大参数
# ═══════════════════════════════════════════════════════════════

def get_model_configs(use_gpu: bool = True, mode: str = "classification") -> list:
    gpu_lgbm = {"device": "gpu", "gpu_platform_id": 0, "gpu_device_id": 0} if use_gpu else {}
    gpu_xgb = {"tree_method": "hist", "device": "cuda"} if use_gpu else {"tree_method": "hist"}
    gpu_cat = {"task_type": "GPU", "devices": "0"} if use_gpu else {}

    configs = []

    if mode == "classification":
        configs.append({
            "name": "lgbm_deep",
            "type": "lgbm",
            "params": {
                "n_estimators": 2000, "learning_rate": 0.02, "max_depth": 9,
                "num_leaves": 127, "min_child_samples": 50,
                "subsample": 0.7, "colsample_bytree": 0.7,
                "reg_alpha": 0.5, "reg_lambda": 1.0,
                "random_state": 42, "verbose": -1,
                **gpu_lgbm,
            },
        })

        configs.append({
            "name": "lgbm_wide",
            "type": "lgbm",
            "params": {
                "n_estimators": 1500, "learning_rate": 0.03, "max_depth": 7,
                "num_leaves": 63, "min_child_samples": 80,
                "subsample": 0.8, "colsample_bytree": 0.6,
                "reg_alpha": 1.0, "reg_lambda": 2.0,
                "random_state": 42, "verbose": -1,
                **gpu_lgbm,
            },
        })

        configs.append({
            "name": "lgbm_conservative",
            "type": "lgbm",
            "params": {
                "n_estimators": 1000, "learning_rate": 0.01, "max_depth": 6,
                "num_leaves": 31, "min_child_samples": 100,
                "subsample": 0.85, "colsample_bytree": 0.8,
                "reg_alpha": 2.0, "reg_lambda": 3.0,
                "random_state": 42, "verbose": -1,
                **gpu_lgbm,
            },
        })

        configs.append({
            "name": "xgb_deep",
            "type": "xgb",
            "params": {
                "n_estimators": 1500, "learning_rate": 0.02, "max_depth": 8,
                "min_child_weight": 50, "subsample": 0.7, "colsample_bytree": 0.7,
                "reg_alpha": 0.5, "reg_lambda": 1.5,
                "random_state": 42, "eval_metric": "logloss", "verbosity": 0,
                **gpu_xgb,
            },
        })

        configs.append({
            "name": "catboost_gpu",
            "type": "catboost",
            "params": {
                "iterations": 1500, "learning_rate": 0.02, "depth": 8,
                "l2_leaf_reg": 5.0, "random_seed": 42, "verbose": 0,
                **gpu_cat,
            },
        })
    else:
        configs.append({
            "name": "lgbm_reg_deep",
            "type": "lgbm_reg",
            "params": {
                "n_estimators": 2000, "learning_rate": 0.02, "max_depth": 9,
                "num_leaves": 127, "min_child_samples": 50,
                "subsample": 0.7, "colsample_bytree": 0.7,
                "reg_alpha": 0.5, "reg_lambda": 1.0,
                "random_state": 42, "verbose": -1,
                **gpu_lgbm,
            },
        })

        configs.append({
            "name": "lgbm_reg_wide",
            "type": "lgbm_reg",
            "params": {
                "n_estimators": 1500, "learning_rate": 0.03, "max_depth": 7,
                "num_leaves": 63, "min_child_samples": 80,
                "subsample": 0.8, "colsample_bytree": 0.6,
                "reg_alpha": 1.0, "reg_lambda": 2.0,
                "random_state": 42, "verbose": -1,
                **gpu_lgbm,
            },
        })

        configs.append({
            "name": "xgb_reg_deep",
            "type": "xgb_reg",
            "params": {
                "n_estimators": 1500, "learning_rate": 0.02, "max_depth": 8,
                "min_child_weight": 50, "subsample": 0.7, "colsample_bytree": 0.7,
                "reg_alpha": 0.5, "reg_lambda": 1.5,
                "random_state": 42, "verbosity": 0,
                **gpu_xgb,
            },
        })

    return configs


def create_model(config: dict):
    if config["type"] == "lgbm":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(**config["params"])
    elif config["type"] == "xgb":
        from xgboost import XGBClassifier
        return XGBClassifier(**config["params"])
    elif config["type"] == "catboost":
        from catboost import CatBoostClassifier
        return CatBoostClassifier(**config["params"])
    elif config["type"] == "lgbm_reg":
        from lightgbm import LGBMRegressor
        return LGBMRegressor(**config["params"])
    elif config["type"] == "xgb_reg":
        from xgboost import XGBRegressor
        return XGBRegressor(**config["params"])
    else:
        raise ValueError(f"Unknown model type: {config['type']}")


# ═══════════════════════════════════════════════════════════════
# 5. 评估指标 — RankIC + 换手惩罚
# ═══════════════════════════════════════════════════════════════

def calc_rank_ic(y_true, y_score) -> float:
    try:
        if isinstance(y_true, pd.Series):
            y_true = y_true.values
        if isinstance(y_score, pd.Series):
            y_score = y_score.values
        ic, _ = spearmanr(y_true, y_score)
        return float(ic) if not np.isnan(ic) else 0.0
    except Exception:
        return 0.0


def evaluate_classification(model, X_val: pd.DataFrame, y_val: pd.Series) -> dict:
    mask = y_val.notna()
    X_v = X_val.loc[mask]
    y_v = y_val.loc[mask].astype(int)

    if len(X_v) < 50 or y_v.nunique() < 2:
        return {"rank_ic": 0, "icir": 0, "auc": 0, "avg_turnover": 0.5, "score": 0}

    proba = model.predict_proba(X_v)
    classes = list(model.classes_)
    buy_idx = classes.index(1) if 1 in classes else len(classes) - 1
    buy_score = proba[:, buy_idx]

    y_arr = y_v.values
    dates_arr = X_v.index.get_level_values("date").values
    codes_arr = X_v.index.get_level_values("code").values
    unique_dates = np.unique(dates_arr)

    daily_ics = []
    for dt in unique_dates:
        dt_mask = dates_arr == dt
        dt_y = y_arr[dt_mask]
        dt_s = buy_score[dt_mask]
        if len(dt_y) > 5:
            ic = calc_rank_ic(dt_y, dt_s)
            daily_ics.append(ic)

    mean_ic = np.mean(daily_ics) if daily_ics else 0
    std_ic = np.std(daily_ics) if len(daily_ics) > 1 else 1
    icir = mean_ic / (std_ic + 1e-8)

    from sklearn.metrics import roc_auc_score
    try:
        auc = roc_auc_score(y_v, buy_score)
    except Exception:
        auc = 0.5

    top_pct = 0.15
    daily_turnover = []
    prev_top = None
    for dt in sorted(unique_dates):
        dt_mask = dates_arr == dt
        dt_scores = pd.Series(buy_score[dt_mask], index=codes_arr[dt_mask])
        n_top = max(1, int(len(dt_scores) * top_pct))
        top_codes = set(dt_scores.nlargest(n_top).index)
        if prev_top is not None:
            turnover = 1 - len(top_codes & prev_top) / max(len(prev_top), 1)
            daily_turnover.append(turnover)
        prev_top = top_codes

    avg_turnover = np.mean(daily_turnover) if daily_turnover else 0.5

    composite_score = mean_ic * (1 - 0.5 * avg_turnover) + 0.3 * icir

    return {
        "rank_ic": round(mean_ic, 4),
        "icir": round(icir, 4),
        "auc": round(auc, 4),
        "avg_turnover": round(avg_turnover, 4),
        "score": round(composite_score, 4),
    }


def evaluate_regression(model, X_val: pd.DataFrame, y_val: pd.Series) -> dict:
    mask = y_val.notna()
    X_v = X_val.loc[mask]
    y_v = y_val.loc[mask]

    if len(X_v) < 50:
        return {"rank_ic": 0, "icir": 0, "avg_turnover": 0.5, "score": 0}

    pred = model.predict(X_v)

    y_arr = y_v.values
    dates_arr = X_v.index.get_level_values("date").values
    codes_arr = X_v.index.get_level_values("code").values
    unique_dates = np.unique(dates_arr)

    daily_ics = []
    for dt in unique_dates:
        dt_mask = dates_arr == dt
        dt_y = y_arr[dt_mask]
        dt_s = pred[dt_mask]
        valid = ~(np.isnan(dt_y) | np.isnan(dt_s))
        if valid.sum() > 5:
            ic = calc_rank_ic(dt_y[valid], dt_s[valid])
            daily_ics.append(ic)

    mean_ic = np.mean(daily_ics) if daily_ics else 0
    std_ic = np.std(daily_ics) if len(daily_ics) > 1 else 1
    icir = mean_ic / (std_ic + 1e-8)

    top_pct = 0.15
    daily_turnover = []
    prev_top = None
    for dt in sorted(unique_dates):
        dt_mask = dates_arr == dt
        dt_scores = pd.Series(pred[dt_mask], index=codes_arr[dt_mask])
        n_top = max(1, int(len(dt_scores) * top_pct))
        top_codes = set(dt_scores.nlargest(n_top).index)
        if prev_top is not None:
            turnover = 1 - len(top_codes & prev_top) / max(len(prev_top), 1)
            daily_turnover.append(turnover)
        prev_top = top_codes

    avg_turnover = np.mean(daily_turnover) if daily_turnover else 0.5

    composite_score = mean_ic * (1 - 0.5 * avg_turnover) + 0.3 * icir

    return {
        "rank_ic": round(mean_ic, 4),
        "icir": round(icir, 4),
        "avg_turnover": round(avg_turnover, 4),
        "score": round(composite_score, 4),
    }


# ═══════════════════════════════════════════════════════════════
# 6. 滚动训练主流程
# ═══════════════════════════════════════════════════════════════

def rolling_train(
    use_gpu: bool = True,
    train_days: int = 500,
    valid_days: int = 60,
    step_days: int = 60,
    forward_window: int = 10,
    top_pct: float = 0.15,
    mode: str = "classification",
    use_alpha158: bool = True,
    log_fn=None,
    freq: str = "daily",
):
    _log = log_fn or print

    _log("=" * 60)
    _log("  QuantPro 滚动化训练 — GPU加速 + 低换手 + 最优选取")
    _log("=" * 60)
    _log(f"  数据频率: {freq}")
    _log(f"  模式: {mode}")
    _log(f"  Alpha158: {'ON' if use_alpha158 else 'OFF'}")
    _log(f"  GPU: {'ON' if use_gpu else 'OFF'}")
    _log(f"  训练窗口: {train_days}天  验证窗口: {valid_days}天  步长: {step_days}天")
    _log(f"  前瞻窗口: {forward_window}天  Top%: {top_pct}")
    _log("")

    if freq == "minute":
        _log("[1/5] 加载5分钟线股票列表...")
        codes = load_minute_stock_list(min_days=100, top_n=500)
        _log(f"  合格股票(按成交量Top500): {len(codes)} 只")

        _log("[2/5] 加载5分钟线数据...")
        minute_df = load_minute_data(codes, "2020-01-01", "2026-12-31")
        _log(f"  原始5分钟线: {len(minute_df):,} 条")

        if minute_df.empty:
            _log("5分钟线数据为空，退出")
            return

        _log("  聚合5分钟线为日线OHLCV...")
        df = aggregate_minute_to_daily(minute_df)
        _log(f"  聚合后日线: {len(df):,} 条")

        _log("  构建日内特征...")
        intraday_feats = build_intraday_features(minute_df)
        _log(f"  日内特征: {intraday_feats.shape[1] if not intraday_feats.empty else 0} 个")
        del minute_df

        _log("  过滤ST/退市...")
        df = filter_st_stocks(df)
        _log(f"  过滤后: {len(df):,} 条")

        _log("[3/5] 构建特征 (日线Alpha158 + 自定义 + 日内)...")
        features = build_features(df, use_alpha158=use_alpha158)
        _log(f"  日线特征维度: {features.shape[1]} 个因子")

        if not intraday_feats.empty:
            common = features.index.intersection(intraday_feats.index)
            intraday_aligned = intraday_feats.loc[common]
            feat_cols = [c for c in intraday_aligned.columns if c != "code"]
            for col in feat_cols:
                if col not in features.columns:
                    group = intraday_aligned[col].groupby(level="date")
                    mean = group.transform("mean")
                    std = group.transform("std")
                    features[col] = ((intraday_aligned[col] - mean) / (std + 1e-8)).fillna(0.0)
            _log(f"  合并后特征维度: {features.shape[1]} 个因子 (含日内特征)")
        del intraday_feats
    else:
        _log("[1/5] 加载股票列表...")
        codes = load_stock_list(min_days=250)
        _log(f"  合格股票: {len(codes)} 只")

        _log("[2/5] 加载价格数据...")
        df = load_price_data(codes, "2020-01-01", "2026-12-31")
        _log(f"  原始数据: {len(df):,} 条")

        _log("  过滤ST/退市...")
        df = filter_st_stocks(df)
        _log(f"  过滤后: {len(df):,} 条")

        _log("[3/5] 构建特征...")
        features = build_features(df, use_alpha158=use_alpha158)
        _log(f"  特征维度: {features.shape[1]} 个因子")

    _log(f"  特征统计: mean={features.mean().mean():.4f} std={features.std().mean():.4f}")

    _log(f"[4/5] 构建标签 (forward_window={forward_window})...")
    if mode == "classification":
        labels = build_labels(df, forward_window=forward_window, top_pct=top_pct)
        n_buy = (labels == 1).sum()
        n_sell = (labels == 0).sum()
        n_nan = labels.isna().sum()
        _log(f"  标签分布: buy={n_buy:,}, sell={n_sell:,}, neutral(丢弃)={n_nan:,}")
    else:
        labels = build_regression_labels(df, forward_window=forward_window)
        n_valid = labels.notna().sum()
        _log(f"  回归标签: 有效={n_valid:,}, mean={labels.mean():.6f}, std={labels.std():.6f}")

    common_idx = features.index.intersection(labels.index).intersection(df.index)
    X_all = features.loc[common_idx].fillna(0.0)
    y_all = labels.loc[common_idx]

    dates = sorted(X_all.index.get_level_values("date").unique())
    _log(f"  日期范围: {dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')} ({len(dates)} 个交易日)")

    _log("[5/5] 滚动训练...")
    model_configs = get_model_configs(use_gpu, mode)
    _log(f"  模型配置: {len(model_configs)} 个")

    all_results = []
    best_overall_score = -999
    best_overall_model = None
    best_overall_config = None
    best_overall_fold = None

    fold = 0
    start_idx = 0
    while True:
        train_end_idx = start_idx + train_days
        valid_end_idx = train_end_idx + valid_days

        if valid_end_idx >= len(dates):
            break

        train_dates = dates[start_idx:train_end_idx]
        valid_dates = dates[train_end_idx:valid_end_idx]

        fold += 1
        _log(f"\n--- Fold {fold} ---")
        _log(f"  Train: {train_dates[0].strftime('%Y-%m-%d')} ~ {train_dates[-1].strftime('%Y-%m-%d')}")
        _log(f"  Valid: {valid_dates[0].strftime('%Y-%m-%d')} ~ {valid_dates[-1].strftime('%Y-%m-%d')}")

        train_mask = X_all.index.get_level_values("date").isin(train_dates)
        valid_mask = X_all.index.get_level_values("date").isin(valid_dates)

        X_train_raw = X_all[train_mask]
        y_train_raw = y_all[train_mask]
        X_valid = X_all[valid_mask]
        y_valid = y_all[valid_mask]

        train_valid_mask = y_train_raw.notna()
        X_train = X_train_raw.loc[train_valid_mask]
        y_train = y_train_raw.loc[train_valid_mask]

        if mode == "classification":
            y_train = y_train.astype(int)

        if len(X_train) < 1000:
            _log("  训练数据不足，跳过")
            start_idx += step_days
            continue

        if mode == "classification" and y_train.nunique() < 2:
            _log("  标签只有一类，跳过")
            start_idx += step_days
            continue

        _log(f"  训练样本: {len(X_train):,}  验证样本: {len(X_valid):,}")
        if mode == "classification":
            _log(f"  训练标签: buy={(y_train==1).sum():,} sell={(y_train==0).sum():,}")

        for config in model_configs:
            model_name = config["name"]
            try:
                model = create_model(config)
                model.fit(X_train, y_train)

                if mode == "classification":
                    metrics = evaluate_classification(model, X_valid, y_valid)
                else:
                    metrics = evaluate_regression(model, X_valid, y_valid)
                metrics["fold"] = fold
                metrics["config"] = model_name
                metrics["train_start"] = train_dates[0].strftime("%Y-%m-%d")
                metrics["valid_start"] = valid_dates[0].strftime("%Y-%m-%d")
                all_results.append(metrics)

                if mode == "classification":
                    _log(f"  {model_name:20s} | IC={metrics['rank_ic']:+.4f} ICIR={metrics['icir']:+.4f} "
                          f"AUC={metrics['auc']:.4f} Turnover={metrics['avg_turnover']:.4f} "
                          f"Score={metrics['score']:+.4f}")
                else:
                    _log(f"  {model_name:20s} | IC={metrics['rank_ic']:+.4f} ICIR={metrics['icir']:+.4f} "
                          f"Turnover={metrics['avg_turnover']:.4f} "
                          f"Score={metrics['score']:+.4f}")

                if metrics["score"] > best_overall_score:
                    best_overall_score = metrics["score"]
                    best_overall_model = model
                    best_overall_config = config
                    best_overall_fold = fold

            except Exception as e:
                _log(f"  {model_name:20s} | ERROR: {str(e)[:80]}")

        start_idx += step_days

    if not all_results:
        _log("\n没有成功的训练结果")
        return

    _log("\n" + "=" * 60)
    _log("  训练结果汇总")
    _log("=" * 60)

    results_df = pd.DataFrame(all_results)
    agg_cols = {c: "mean" for c in ["rank_ic", "icir", "score"] if c in results_df.columns}
    if "auc" in results_df.columns:
        agg_cols["auc"] = "mean"
    if "avg_turnover" in results_df.columns:
        agg_cols["avg_turnover"] = "mean"

    summary = results_df.groupby("config").agg(agg_cols).sort_values("score", ascending=False)

    _log(summary.to_string())

    best_config_name = summary.index[0]
    best_avg_score = summary.iloc[0]["score"]
    _log(f"\n最优配置: {best_config_name} (平均 Score={best_avg_score:+.4f})")

    model_dir = ROOT / "data" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = model_dir / f"rolling_best_{timestamp}.pkl"

    import joblib
    joblib.dump(best_overall_model, model_path)
    _log(f"最优模型已保存: {model_path}")

    report = {
        "timestamp": timestamp,
        "mode": mode,
        "freq": freq,
        "alpha158": use_alpha158,
        "gpu": use_gpu,
        "train_days": train_days,
        "valid_days": valid_days,
        "step_days": step_days,
        "forward_window": forward_window,
        "top_pct": top_pct,
        "best_config": best_overall_config["name"],
        "best_fold": best_overall_fold,
        "best_score": best_overall_score,
        "n_features": int(X_all.shape[1]),
        "summary": summary.to_dict(),
        "fold_results": all_results,
    }

    report_path = model_dir / f"rolling_report_{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    _log(f"训练报告已保存: {report_path}")

    default_path = model_dir / "cs_model.pkl"
    joblib.dump(best_overall_model, default_path)
    _log(f"已更新默认截面模型: {default_path}")

    if hasattr(best_overall_model, "feature_importances_"):
        fi = pd.Series(best_overall_model.feature_importances_,
                       index=X_all.columns).sort_values(ascending=False)
        _log("\n特征重要性 Top 10:")
        for name, imp in fi.head(10).items():
            bar = "#" * int(imp / fi.max() * 30)
            _log(f"  {name:20s} {imp:8.1f} {bar}")

    _log("滚动训练完成!")


# ═══════════════════════════════════════════════════════════════
# 7. 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QuantPro Rolling Train")
    parser.add_argument("--no-gpu", action="store_true")
    parser.add_argument("--mode", choices=["classification", "regression"], default="classification")
    parser.add_argument("--no-alpha158", action="store_true")
    parser.add_argument("--train-days", type=int, default=500)
    parser.add_argument("--valid-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=60)
    parser.add_argument("--forward", type=int, default=10)
    parser.add_argument("--top-pct", type=float, default=0.15)
    parser.add_argument("--freq", choices=["daily", "minute"], default="daily")
    args = parser.parse_args()

    rolling_train(
        use_gpu=not args.no_gpu,
        train_days=args.train_days,
        valid_days=args.valid_days,
        step_days=args.step_days,
        forward_window=args.forward,
        top_pct=args.top_pct,
        mode=args.mode,
        use_alpha158=not args.no_alpha158,
        freq=args.freq,
    )
