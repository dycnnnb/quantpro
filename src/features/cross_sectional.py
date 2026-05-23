"""
截面特征 — 跨股票 z-score 标准化
"""

import pandas as pd
import numpy as np


def cross_sectional_normalize(feat_df: pd.DataFrame) -> pd.DataFrame:
    """
    同一时间点，对所有股票的每个特征做 z-score
    消除不同股票间的量纲差异
    """
    normed = feat_df.copy()
    for col in feat_df.columns:
        cs_mean = feat_df[col].groupby(level='datetime').transform('mean')
        cs_std = feat_df[col].groupby(level='datetime').transform('std')
        normed[col] = (feat_df[col] - cs_mean) / (cs_std + 1e-8)
    return normed.clip(-3, 3)


def build_cross_sectional_features(
    multi_df: pd.DataFrame,
    use_kronos: bool = False,
    kronos_window: int = 48,
    kronos_device: str = "cpu",
) -> pd.DataFrame:
    """
    截面特征：对每只股票计算原始特征，再做截面标准化

    输入: MultiIndex DataFrame (datetime, code)
    输出: 同结构的特征 DataFrame
    """
    from src.features.minute import MinuteFeatureBuilder

    builder = MinuteFeatureBuilder()
    kronos_builder = None
    if use_kronos:
        from src.features.kronos import KronosMinuteFeatureBuilder
        kronos_builder = KronosMinuteFeatureBuilder(
            window=kronos_window, device=kronos_device
        )

    codes = multi_df.index.get_level_values('code').unique()
    all_feats = []

    for i, code in enumerate(codes):
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(codes)} done")

        stock_df = multi_df.xs(code, level='code')
        feat_df = builder.compute(stock_df)

        if kronos_builder is not None:
            kronos_feat = kronos_builder.compute(stock_df)
            if not kronos_feat.empty:
                feat_df = feat_df.loc[kronos_feat.index]
                feat_df = pd.concat([feat_df, kronos_feat], axis=1)

        feat_df.index = pd.MultiIndex.from_arrays(
            [feat_df.index, [code] * len(feat_df)],
            names=['datetime', 'code']
        )
        all_feats.append(feat_df)

    combined = pd.concat(all_feats).sort_index()
    normalized = cross_sectional_normalize(combined)

    print(f"Cross-sectional features: {normalized.shape[1]} features, {len(normalized):,} rows")
    return normalized
