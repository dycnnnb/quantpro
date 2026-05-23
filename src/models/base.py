"""
模型基类 — 所有模型继承此类
"""

from abc import ABC, abstractmethod
from pathlib import Path

import joblib
import pandas as pd


class BaseModel(ABC):
    """模型抽象基类"""

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "BaseModel":
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        ...

    @abstractmethod
    def evaluate(self, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
        ...

    def save(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        print(f"Model saved: {path}")

    @classmethod
    def load(cls, path: str) -> "BaseModel":
        return joblib.load(path)
