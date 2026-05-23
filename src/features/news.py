"""
新闻因子特征 — 从 news_daily_factor 表读取并构建模型特征
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from config.settings import DB
from src.features.base import BaseFeature

NEWS_FACTOR_COLS = [
    "sentiment_avg", "sentiment_std", "sentiment_max", "sentiment_min",
    "news_count", "industry_heat_avg", "catalyst_avg", "catalyst_max",
    "urgency_avg", "news_momentum", "sentiment_momentum",
    "positive_ratio", "source_diversity",
]


class NewsFeatureBuilder(BaseFeature):
    """新闻因子特征构建器"""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or DB["market"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """输入: 单股票日线 OHLCV DataFrame (index=date)
        输出: 新闻因子特征 DataFrame (同 index)"""
        stock_code = self._detect_stock_code(df)
        if not stock_code:
            return pd.DataFrame(index=df.index, columns=self._feature_names())

        news_df = self._load_daily_factors(stock_code, df.index)
        result = pd.DataFrame(index=df.index)

        for col in NEWS_FACTOR_COLS:
            result[f"nf_{col}"] = news_df[col].reindex(df.index).ffill().fillna(0)

        # 衍生特征
        result["nf_sentiment_range"] = result["nf_sentiment_max"] - result["nf_sentiment_min"]
        result["nf_news_count_log"] = np.log1p(result["nf_news_count"])
        result["nf_catalyst_x_sentiment"] = result["nf_catalyst_avg"] * result["nf_sentiment_avg"]
        result["nf_heat_x_catalyst"] = result["nf_industry_heat_avg"] * result["nf_catalyst_avg"]

        return result

    def _detect_stock_code(self, df: pd.DataFrame) -> str:
        if hasattr(df, "attrs") and "stock_code" in df.attrs:
            return df.attrs["stock_code"]
        if "code" in df.columns:
            return str(df["code"].iloc[0])
        return ""

    def _load_daily_factors(self, stock_code: str, date_index: pd.DatetimeIndex) -> pd.DataFrame:
        conn = sqlite3.connect(str(self.db_path))
        start = date_index.min().strftime("%Y-%m-%d")
        end = date_index.max().strftime("%Y-%m-%d")

        try:
            df = pd.read_sql(
                f"SELECT * FROM news_daily_factor WHERE stock_code = ? AND trade_date >= ? AND trade_date <= ?",
                conn, params=(stock_code, start, end))
        except Exception:
            df = pd.DataFrame(columns=["trade_date"] + NEWS_FACTOR_COLS)
        finally:
            conn.close()

        if df.empty:
            return pd.DataFrame(columns=NEWS_FACTOR_COLS)

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date")
        return df[NEWS_FACTOR_COLS]

    def _feature_names(self) -> list[str]:
        return [f"nf_{col}" for col in NEWS_FACTOR_COLS] + [
            "nf_sentiment_range", "nf_news_count_log",
            "nf_catalyst_x_sentiment", "nf_heat_x_catalyst",
        ]


def build_news_features_panel(
    stock_codes: list[str],
    start_date: str,
    end_date: str,
    db_path: Path = None,
) -> pd.DataFrame:
    """构建多股票新闻因子面板，返回 MultiIndex (date, code) DataFrame"""
    db_path = db_path or DB["market"]
    conn = sqlite3.connect(str(db_path))

    try:
        df = pd.read_sql(
            """SELECT * FROM news_daily_factor
               WHERE stock_code IN ({}) AND trade_date >= ? AND trade_date <= ?""".format(
                ",".join(["?"] * len(stock_codes))),
            conn, params=(*stock_codes, start_date, end_date))
    except Exception:
        conn.close()
        return pd.DataFrame()
    finally:
        conn.close()

    if df.empty:
        return pd.DataFrame()

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.rename(columns={"stock_code": "code", "trade_date": "date"})
    df = df.set_index(["date", "code"])

    # 截面标准化
    for col in NEWS_FACTOR_COLS:
        if col in df.columns:
            df[col] = df.groupby("date")[col].rank(pct=True)

    return df
