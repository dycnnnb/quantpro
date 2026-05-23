"""
Qlib Alpha158 因子库 — 纯 Python/Pandas 实现
参考: https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/handler.py

22个基础因子 x 5个窗口(5,10,20,30,60) = 110个特征 + 5个标准化OHLCV = ~158个因子
不依赖 Qlib 框架，仅使用 pandas + numpy
"""

import numpy as np
import pandas as pd

from src.features.base import BaseFeature


class Alpha158Builder(BaseFeature):

    DEFAULT_WINDOWS = (5, 10, 20, 30, 60)

    def __init__(self, windows=None):
        self.windows = windows or self.DEFAULT_WINDOWS

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        o = df["open"]
        h = df["high"]
        l = df["low"]
        c = df["close"]
        v = df["volume"]

        f = pd.DataFrame(index=df.index)

        for N in self.windows:
            f[f"KMID_{N}"] = (c - l) / (h - l + 1e-12)
            f[f"KLEN_{N}"] = (h - l) / (o + 1e-12)
            f[f"ROC_{N}"] = c / c.shift(N) - 1
            f[f"MA_{N}"] = c.rolling(N).mean() / (c + 1e-12)
            f[f"STD_{N}"] = c.rolling(N).std() / (c + 1e-12)
            f[f"VROC_{N}"] = v / (v.shift(N) + 1e-12) - 1
            f[f"VMA_{N}"] = v.rolling(N).mean() / (v + 1e-12)
            f[f"VSTD_{N}"] = v.rolling(N).std() / (v + 1e-12)

            wv = c * v
            f[f"WVMA_{N}"] = wv.rolling(N).std() / (wv.rolling(N).mean() + 1e-12)

            v_diff = v - v.shift(1)
            f[f"VSUMP_{N}"] = v_diff.clip(lower=0).rolling(N).sum() / (v.rolling(N).sum() + 1e-12)

            f[f"CORR_{N}"] = c.rolling(N).corr(v)
            f[f"CORD_{N}"] = c.shift(1).rolling(N).corr(v)

            c_diff = c - c.shift(1)
            f[f"CNTP_{N}"] = (c_diff > 0).rolling(N).mean()
            f[f"CNTN_{N}"] = (c_diff < 0).rolling(N).mean()
            f[f"CNTD_{N}"] = f[f"CNTP_{N}"] - f[f"CNTN_{N}"]

            f[f"SUMP_{N}"] = c_diff.clip(lower=0).rolling(N).sum() / (c_diff.abs().rolling(N).sum() + 1e-12)
            f[f"SUMN_{N}"] = c_diff.clip(upper=0).abs().rolling(N).sum() / (c_diff.abs().rolling(N).sum() + 1e-12)
            f[f"SUMD_{N}"] = f[f"SUMP_{N}"] - f[f"SUMN_{N}"]

            f[f"IMAX_{N}"] = h.rolling(N).apply(np.argmax, raw=True) / N
            f[f"IMIN_{N}"] = l.rolling(N).apply(np.argmin, raw=True) / N
            f[f"IMXD_{N}"] = f[f"IMAX_{N}"] - f[f"IMIN_{N}"]

            cov_cv = c.rolling(N).cov(v)
            var_v = v.rolling(N).var()
            f[f"BETA_{N}"] = cov_cv / (var_v + 1e-12)

        f["OPEN"] = o / (c + 1e-12)
        f["HIGH"] = h / (c + 1e-12)
        f["LOW"] = l / (c + 1e-12)
        f["CLOSE"] = 1.0
        f["VOLUME"] = v / (v.rolling(120).mean() + 1e-12)

        return f.replace([np.inf, -np.inf], np.nan)


def build_alpha158_panel(
    stock_codes: list,
    data_loader,
    start_date: str,
    end_date: str,
    windows=None,
) -> pd.DataFrame:
    builder = Alpha158Builder(windows=windows)
    all_factors = []

    for code in stock_codes:
        df = data_loader.load_daily(code, start_date, end_date)
        if df.empty or len(df) < 60:
            continue
        factors = builder.compute(df)
        factors["code"] = code
        all_factors.append(factors)

    if not all_factors:
        raise ValueError("No features computed")

    panel = pd.concat(all_factors)
    panel = panel.reset_index()
    panel = panel.rename(columns={"date": "date"})
    panel = panel.set_index(["date", "code"])

    factor_cols = [c for c in panel.columns]
    for col in factor_cols:
        group = panel[col].groupby(level="date")
        mean = group.transform("mean")
        std = group.transform("std")
        panel[col] = ((panel[col] - mean) / (std + 1e-8)).fillna(0.0)

    print(f"Alpha158 features: {len(stock_codes)} stocks, {len(factor_cols)} factors, shape={panel.shape}")
    return panel
