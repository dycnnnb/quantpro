"""
数据缓存管理
避免重复计算和查询
"""

import hashlib
import json
import pickle
from pathlib import Path
from typing import Optional

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import PATHS


class DataCache:
    """数据缓存管理器"""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or PATHS["cache_dir"]
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, namespace: str, **kwargs) -> str:
        raw = json.dumps(kwargs, sort_keys=True, default=str)
        h = hashlib.md5(f"{namespace}:{raw}".encode()).hexdigest()
        return h

    def get(self, namespace: str, **kwargs) -> Optional[pd.DataFrame]:
        key = self._key(namespace, **kwargs)
        path = self.cache_dir / f"{key}.pkl"
        if path.exists():
            try:
                return pickle.loads(path.read_bytes())
            except Exception:
                path.unlink(missing_ok=True)
        return None

    def set(self, df: pd.DataFrame, namespace: str, **kwargs):
        key = self._key(namespace, **kwargs)
        path = self.cache_dir / f"{key}.pkl"
        path.write_bytes(pickle.dumps(df))

    def invalidate(self, namespace: str, **kwargs):
        key = self._key(namespace, **kwargs)
        path = self.cache_dir / f"{key}.pkl"
        path.unlink(missing_ok=True)

    def clear(self):
        for f in self.cache_dir.glob("*.pkl"):
            f.unlink()

    def stats(self) -> dict:
        files = list(self.cache_dir.glob("*.pkl"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            'count': len(files),
            'total_size_mb': round(total_size / 1024 / 1024, 2),
        }
