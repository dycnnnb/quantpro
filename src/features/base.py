"""
特征基类 — 所有特征模块继承此类
"""

from abc import ABC, abstractmethod

import pandas as pd


class BaseFeature(ABC):
    """特征计算抽象基类"""

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算特征，输入 OHLCV DataFrame，返回特征 DataFrame"""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__
