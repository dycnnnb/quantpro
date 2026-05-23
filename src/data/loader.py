"""
统一数据加载接口
所有数据访问通过 DataLoader 类
"""

import sqlite3
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DB, data_config


class DataLoader:
    """SQLite 数据加载器"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB["market"]

    def _check_db(self):
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    @staticmethod
    def _normalize_code(symbol: str) -> str:
        """将 sh.600519 / sz.000001 / sh600519 / sz000001 / 600519.SH / 000001.SZ 格式转为 600519 / 000001"""
        if '.' in symbol:
            parts = symbol.split('.')
            if parts[0].isdigit():
                return parts[0]
            return parts[1]
        for prefix in ('sh', 'sz'):
            if symbol.lower().startswith(prefix):
                return symbol[len(prefix):]
        return symbol

    # ── 日线 ────────────────────────────────────────────────────────
    def load_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """加载单只股票日线数据"""
        self._check_db()
        symbol = self._normalize_code(symbol)
        query = "SELECT date, open, high, low, close, volume, amount FROM stock_kline WHERE code = ?"
        params = [symbol]
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        query += " ORDER BY date ASC"

        with self._conn() as conn:
            df = pd.read_sql(query, conn, params=params)

        if df.empty:
            return df

        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df

    def load_multi_daily(
        self,
        symbols: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """加载多只股票日线数据，返回 MultiIndex (date, symbol)"""
        self._check_db()
        symbols = [self._normalize_code(s) for s in symbols]
        placeholders = ",".join(["?"] * len(symbols))
        query = f"SELECT code, date, open, high, low, close, volume, amount FROM stock_kline WHERE code IN ({placeholders})"
        params: list = list(symbols)
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        query += " ORDER BY date ASC, code ASC"

        with self._conn() as conn:
            df = pd.read_sql(query, conn, params=params)

        if df.empty:
            return df

        df['date'] = pd.to_datetime(df['date'])
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.rename(columns={'code': 'symbol'})
        df = df.set_index(['date', 'symbol']).sort_index()
        return df

    # ── 分钟线 ──────────────────────────────────────────────────────
    def load_minute(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        freq: str = "5min",
    ) -> pd.DataFrame:
        """加载单只股票分钟线数据"""
        self._check_db()
        symbol = self._normalize_code(symbol)
        minute_type = "1min" if freq == "1min" else "5min"

        query = """
            SELECT date, time, open, high, low, close, volume
            FROM minute_kline
            WHERE code = ? AND date >= ? AND date <= ? AND minute_type = ?
            ORDER BY date ASC, time ASC
        """
        with self._conn() as conn:
            df = pd.read_sql(query, conn, params=(symbol, start_date, end_date, minute_type))

        if df.empty:
            return df

        df['datetime'] = pd.to_datetime(df['time'].astype(str), format='%Y%m%d%H%M%S%f')
        df = df.drop(columns=['date', 'time']).set_index('datetime').sort_index()
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = self._filter_trading_hours(df)
        return df

    def load_multi_minute(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        freq: str = "5min",
    ) -> pd.DataFrame:
        """加载多只股票分钟线数据，返回 MultiIndex (datetime, symbol)"""
        self._check_db()
        symbols = [self._normalize_code(s) for s in symbols]
        minute_type = "1min" if freq == "1min" else "5min"
        placeholders = ",".join(["?"] * len(symbols))

        query = f"""
            SELECT code, date, time, open, high, low, close, volume
            FROM minute_kline
            WHERE code IN ({placeholders}) AND date >= ? AND date <= ? AND minute_type = ?
            ORDER BY date ASC, time ASC, code ASC
        """
        params = list(symbols) + [start_date, end_date, minute_type]

        with self._conn() as conn:
            df = pd.read_sql(query, conn, params=params)

        if df.empty:
            return df

        df['datetime'] = pd.to_datetime(df['time'].astype(str), format='%Y%m%d%H%M%S%f')
        df = df.drop(columns=['date', 'time'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.set_index('datetime')
        df = self._filter_trading_hours(df)
        df = df.reset_index()
        df = df.set_index(['datetime', 'code']).sort_index()
        return df

    # ── 月线 ────────────────────────────────────────────────────────
    def load_monthly(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """加载月线数据"""
        self._check_db()
        symbol = self._normalize_code(symbol)
        query = "SELECT date, open, high, low, close, volume, amount FROM monthly_kline WHERE code = ?"
        params = [symbol]
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        query += " ORDER BY date ASC"

        with self._conn() as conn:
            df = pd.read_sql(query, conn, params=params)

        if df.empty:
            return df

        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df

    # ── 实时行情 ────────────────────────────────────────────────────
    def get_realtime_price(self, code: str) -> Optional[float]:
        """获取实时价格（交易时段），非交易时段返回 None"""
        code = self._normalize_code(code)
        try:
            from src.data.realtime import RealtimeQuote
            if not hasattr(self, '_realtime'):
                self._realtime = RealtimeQuote(data_config.realtime_source)
            return self._realtime.get_price(code)
        except Exception:
            return None

    def get_realtime_prices(self, codes: list) -> dict:
        """批量获取实时价格 {code: price}"""
        codes = [self._normalize_code(c) for c in codes]
        try:
            from src.data.realtime import RealtimeQuote
            if not hasattr(self, '_realtime'):
                self._realtime = RealtimeQuote(data_config.realtime_source)
            return self._realtime.get_prices(codes)
        except Exception:
            return {}

    # ── 辅助方法 ────────────────────────────────────────────────────
    def get_available_symbols(self, min_bars: int = 1000) -> List[str]:
        """获取数据充足的股票列表"""
        self._check_db()
        with self._conn() as conn:
            df = pd.read_sql(f"""
                SELECT code FROM minute_kline
                WHERE minute_type = '5min'
                GROUP BY code
                HAVING COUNT(*) >= {min_bars}
                ORDER BY COUNT(*) DESC
            """, conn)
        return df['code'].tolist()

    def get_daily_symbols(self, min_days: int = 100) -> List[str]:
        """获取日线数据充足的股票"""
        self._check_db()
        with self._conn() as conn:
            df = pd.read_sql(f"""
                SELECT code FROM stock_kline
                GROUP BY code
                HAVING COUNT(*) >= {min_days}
                ORDER BY COUNT(*) DESC
            """, conn)
        return df['code'].tolist()

    def get_db_info(self) -> dict:
        """获取数据库概览"""
        self._check_db()
        with self._conn() as conn:
            daily = pd.read_sql("""
                SELECT COUNT(DISTINCT code) as stocks, COUNT(*) as rows,
                       MIN(date) as start, MAX(date) as end
                FROM stock_kline
            """, conn)
            minute = pd.read_sql("""
                SELECT COUNT(DISTINCT code) as stocks, COUNT(*) as rows,
                       MIN(date) as start, MAX(date) as end
                FROM minute_kline WHERE minute_type = '5min'
            """, conn)
        return {
            'daily': daily.iloc[0].to_dict(),
            'minute': minute.iloc[0].to_dict(),
        }

    @staticmethod
    def _filter_trading_hours(df: pd.DataFrame) -> pd.DataFrame:
        """过滤交易时间"""
        h, m = df.index.hour, df.index.minute
        morning = ((h > 9) | ((h == 9) & (m >= 30))) & ((h < 11) | ((h == 11) & (m <= 30)))
        afternoon = ((h >= 13) & (h < 15)) | ((h == 15) & (m == 0))
        return df[morning | afternoon].copy()
