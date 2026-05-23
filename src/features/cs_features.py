from __future__ import annotations

import warnings
from typing import List, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)

EXISTING_FEATURES: List[str] = [
    "pct_chg", "amplitude", "turnover", "volume_ratio",
    "ma5_bias", "ma10_bias", "ma20_bias", "rsi_14",
    "vol_20d", "skew_20d", "kurt_20d", "max_ret_20d", "illiq",
]

NEW_FEATURES: List[str] = [
    "mom_1m",
    "mom_3m",
    "vol_ratio_5_20",
    "price_pos_60",
    "atr_pct",
    "ret_skew_corr",
]

NEWS_FEATURES: List[str] = [
    "nf_sentiment_avg", "nf_sentiment_std", "nf_sentiment_max", "nf_sentiment_min",
    "nf_news_count", "nf_industry_heat_avg", "nf_catalyst_avg", "nf_catalyst_max",
    "nf_urgency_avg", "nf_news_momentum", "nf_sentiment_momentum",
    "nf_positive_ratio", "nf_source_diversity",
    "nf_sentiment_range", "nf_news_count_log",
    "nf_catalyst_x_sentiment", "nf_heat_x_catalyst",
]

ALL_FEATURES: List[str] = EXISTING_FEATURES + NEW_FEATURES + NEWS_FEATURES


def build_features(
    daily_df: pd.DataFrame,
    symbol_col: str = "code",
    include_news: bool = True,
) -> pd.DataFrame:
    df = daily_df.copy()
    df = df.sort_values([symbol_col, "date"]).reset_index(drop=True)
    df = _fill_existing_features(df)
    df = _add_new_features(df)
    if include_news:
        df = _merge_news_features(df, symbol_col)
    return df


def zscore_cross_section(
    df: pd.DataFrame,
    feature_cols: List[str],
    date_col: str = "date",
    clip: float = 3.0,
) -> pd.DataFrame:
    df = df.copy()

    def _zscore(group: pd.DataFrame) -> pd.DataFrame:
        for col in feature_cols:
            if col not in group.columns:
                continue
            s = group[col]
            mean = s.mean()
            std = s.std(ddof=1)
            if std < 1e-9:
                group[col] = 0.0
            else:
                group[col] = ((s - mean) / std).clip(-clip, clip)
        return group

    df = df.groupby(date_col, group_keys=False).apply(_zscore)
    return df


def _fill_existing_features(df: pd.DataFrame) -> pd.DataFrame:
    if "pct_chg" not in df.columns or df["pct_chg"].isna().all():
        df["pct_chg"] = df.groupby("code")["close"].pct_change() * 100.0

    if "amplitude" not in df.columns or df["amplitude"].isna().all():
        df["amplitude"] = (df["high"] - df["low"]) / df.groupby("code")["close"].shift(1) * 100.0

    if "turnover" not in df.columns or df["turnover"].isna().all():
        if "amount" in df.columns:
            df["turnover"] = df.groupby("code")["amount"].pct_change() * 100.0
        else:
            df["turnover"] = df.groupby("code")["volume"].pct_change() * 100.0

    if "volume_ratio" not in df.columns or df["volume_ratio"].isna().all():
        df["volume_ratio"] = df.groupby("code")["volume"].transform(
            lambda s: s / s.rolling(20, min_periods=5).mean()
        )

    for col in EXISTING_FEATURES:
        if col not in df.columns:
            df[col] = np.nan
    return df


def _add_new_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.groupby("code", group_keys=False).apply(_calc_new_features_single)
    return df


def _calc_new_features_single(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    c = g["close"]
    v = g["volume"]
    h = g["high"]
    l = g["low"]
    o = g["open"] if "open" in g.columns else c
    if "pct_chg" not in g.columns or g["pct_chg"].isna().all():
        g["pct_chg"] = c.pct_change() * 100.0
    ret = g["pct_chg"] / 100.0

    if "amplitude" not in g.columns or g["amplitude"].isna().all():
        g["amplitude"] = (h - l) / c.shift(1) * 100.0

    if "turnover" not in g.columns or g["turnover"].isna().all():
        g["turnover"] = v.pct_change() * 100.0

    if "volume_ratio" not in g.columns or g["volume_ratio"].isna().all():
        vol_ma20 = v.rolling(20, min_periods=5).mean()
        g["volume_ratio"] = v / (vol_ma20 + 1e-9)

    ma5 = c.rolling(5, min_periods=3).mean()
    ma10 = c.rolling(10, min_periods=5).mean()
    ma20 = c.rolling(20, min_periods=10).mean()
    g["ma5_bias"] = (c - ma5) / (ma5 + 1e-9)
    g["ma10_bias"] = (c - ma10) / (ma10 + 1e-9)
    g["ma20_bias"] = (c - ma20) / (ma20 + 1e-9)

    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=7).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=7).mean()
    rs = gain / (loss + 1e-9)
    g["rsi_14"] = 100 - 100 / (1 + rs)

    g["vol_20d"] = ret.rolling(20, min_periods=10).std()
    g["skew_20d"] = ret.rolling(20, min_periods=10).skew()
    g["kurt_20d"] = ret.rolling(20, min_periods=10).kurt()
    g["max_ret_20d"] = ret.rolling(20, min_periods=10).max()

    if "amount" in g.columns:
        g["illiq"] = ret.abs() / (g["amount"] + 1e-9)
    else:
        g["illiq"] = ret.abs() / (v * c + 1e-9)

    g["mom_1m"] = c.shift(1).pct_change(20)
    g["mom_3m"] = c.shift(1).pct_change(60)

    vol_ma5 = v.rolling(5, min_periods=3).mean()
    vol_ma20_v = v.rolling(20, min_periods=10).mean()
    g["vol_ratio_5_20"] = vol_ma5 / (vol_ma20_v + 1e-9)

    high60 = h.rolling(60, min_periods=20).max()
    low60 = l.rolling(60, min_periods=20).min()
    g["price_pos_60"] = (c - low60) / (high60 - low60 + 1e-9)

    prev_c = c.shift(1)
    tr = pd.concat([
        h - l,
        (h - prev_c).abs(),
        (l - prev_c).abs(),
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14, min_periods=5).mean()
    g["atr_pct"] = atr14 / (c + 1e-9)

    amp = g["amplitude"] / 100.0
    g["ret_skew_corr"] = ret.rolling(20, min_periods=10).corr(amp)

    return g


def _merge_news_features(df: pd.DataFrame, symbol_col: str = "code") -> pd.DataFrame:
    from src.features.news import build_news_features_panel
    from config.settings import DB

    for col in NEWS_FEATURES:
        if col not in df.columns:
            df[col] = 0.0

    if symbol_col not in df.columns or "date" not in df.columns:
        return df

    try:
        codes = df[symbol_col].unique().tolist()
        codes = [str(c).zfill(6) for c in codes]
        start = str(df["date"].min().date()) if hasattr(df["date"].min(), "date") else str(df["date"].min())[:10]
        end = str(df["date"].max().date()) if hasattr(df["date"].max(), "date") else str(df["date"].max())[:10]

        news_panel = build_news_features_panel(codes, start, end, db_path=DB["market"])
        if news_panel.empty:
            return df

        news_flat = news_panel.reset_index()
        if "code" in news_flat.columns:
            news_flat[symbol_col] = news_flat["code"].astype(str).str.zfill(6)
        if "date" in news_flat.columns:
            news_flat["date"] = pd.to_datetime(news_flat["date"])
        df["date"] = pd.to_datetime(df["date"])
        df[symbol_col] = df[symbol_col].astype(str).str.zfill(6)

        nf_cols = [c for c in news_flat.columns if c.startswith("nf_")]
        if nf_cols:
            merge_keys = ["date", symbol_col]
            df = df.merge(news_flat[merge_keys + nf_cols], on=merge_keys, how="left", suffixes=("", "_news"))
            for col in nf_cols:
                if col in df.columns:
                    df[col] = df[col].fillna(0.0)
    except Exception:
        pass

    return df
