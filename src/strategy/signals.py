"""
信号生成 — 模型输出转换为交易信号
"""

import pandas as pd


def generate_signals(scores_df: pd.DataFrame, threshold: float = 0.55,
                     top_k: int = 5) -> pd.DataFrame:
    """
    从模型得分生成交易信号

    输入: scores_df with columns [buy_score, sell_score]
    输出: DataFrame with columns [signal, confidence]
    """
    res = pd.DataFrame(index=scores_df.index)
    res['signal'] = 2  # hold
    res['confidence'] = scores_df['buy_score']

    buy_mask = scores_df['buy_score'] >= threshold
    res.loc[buy_mask, 'signal'] = 1  # buy

    sell_mask = scores_df['sell_score'] >= threshold
    res.loc[sell_mask, 'signal'] = 0  # sell

    return res


def rank_select(scores_df: pd.DataFrame, datetime: pd.Timestamp,
                top_k: int = 5, threshold: float = 0.55) -> list:
    """截面排名选股"""
    try:
        dt_scores = scores_df.loc[datetime, 'buy_score']
    except KeyError:
        return []
    if isinstance(dt_scores, float):
        return []
    filtered = dt_scores[dt_scores >= threshold]
    return filtered.nlargest(top_k).index.tolist() if len(filtered) > 0 else []
