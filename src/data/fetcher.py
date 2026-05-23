"""
多源数据抓取器
支持 腾讯HTTP / Sina / baostock 三种数据源，自动检测可用源并回退
优先级: 腾讯HTTP > Sina > baostock
"""

import json
import socket
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Set

import requests

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DB, PATHS, proxy_config

_bs_lock = threading.Lock()
_original_socket = None
_source_cache = None
_source_cache_time = 0

_TENCENT_DAILY_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
_TENCENT_MIN_URL = 'https://ifzq.gtimg.cn/appstock/app/kline/mkline'
_TENCENT_QUOTE_URL = 'https://qt.gtimg.cn/q='
_SINA_LIST_URL = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'

_HTTP_SESSION = None


def _get_session():
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        _HTTP_SESSION = requests.Session()
        _HTTP_SESSION.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    return _HTTP_SESSION


def _code_to_prefix(code: str) -> str:
    if code.startswith('6') or code.startswith('9'):
        return 'sh'
    return 'sz'


def _code_to_bs(code: str) -> str:
    return f"{_code_to_prefix(code)}.{code}"


def detect_source() -> str:
    global _source_cache, _source_cache_time
    if _source_cache and (time.time() - _source_cache_time) < 300:
        return _source_cache

    session = _get_session()

    try:
        url = f'{_TENCENT_DAILY_URL}?param=sh600519,day,,1,qfq'
        r = session.get(url, timeout=8)
        if r.status_code == 200:
            data = json.loads(r.text)
            sd = data.get('data', {}).get('sh600519', {})
            if sd.get('qfqday') or sd.get('day'):
                _source_cache = 'tencent'
                _source_cache_time = time.time()
                print('[FETCHER] Data source: tencent')
                return 'tencent'
    except Exception:
        pass

    try:
        import akshare as ak
        df = ak.stock_zh_a_daily(symbol="sh600519", start_date="20260101", end_date="20260110", adjust="qfq")
        if len(df) > 0:
            _source_cache = 'sina'
            _source_cache_time = time.time()
            print('[FETCHER] Data source: sina')
            return 'sina'
    except Exception:
        pass

    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code == '0':
            bs.logout()
            _source_cache = 'baostock'
            _source_cache_time = time.time()
            print('[FETCHER] Data source: baostock')
            return 'baostock'
    except Exception:
        pass

    _source_cache = 'tencent'
    _source_cache_time = time.time()
    print('[FETCHER] Data source: tencent (fallback)')
    return 'tencent'


def enable_socks5_proxy():
    global _original_socket
    if not proxy_config.enabled:
        return False
    try:
        import socks
        _original_socket = socket.socket
        socks.set_default_proxy(socks.SOCKS5, proxy_config.socks5_host, proxy_config.socks5_port)
        socket.socket = socks.socksocket
        return True
    except ImportError:
        print("[WARN] PySocks not installed. Run: pip install PySocks")
        return False


def disable_socks5_proxy():
    global _original_socket
    if _original_socket is not None:
        socket.socket = _original_socket
        _original_socket = None


def enable_ssh_tunnel():
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
        from ssh_tunnel import start_tunnel
        return start_tunnel()
    except Exception as e:
        print(f"[WARN] SSH tunnel failed: {e}")
        return False


def disable_ssh_tunnel():
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
        from ssh_tunnel import stop_tunnel
        stop_tunnel()
    except Exception:
        pass


def _setup_connection():
    if proxy_config.enabled:
        tunnel_ok = enable_ssh_tunnel()
        if tunnel_ok:
            return 'ssh_tunnel'
        proxy_ok = enable_socks5_proxy()
        if proxy_ok:
            return 'socks5'
    return 'direct'


def _teardown_connection(mode):
    if mode == 'ssh_tunnel':
        disable_ssh_tunnel()
    elif mode == 'socks5':
        disable_socks5_proxy()


class StockFetcher:
    """多源数据抓取器（腾讯HTTP / Sina / baostock 自动回退）"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB["market"]
        self.log_dir = PATHS["log_dir"]
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._source = None

    @property
    def source(self):
        if self._source is None:
            self._source = detect_source()
        return self._source

    def init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS stock_kline (
            code TEXT, date TEXT, open REAL, high REAL, low REAL,
            close REAL, volume INTEGER, amount REAL,
            PRIMARY KEY (code, date)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS minute_kline (
            code TEXT, date TEXT, time TEXT, open REAL, high REAL,
            low REAL, close REAL, volume INTEGER, minute_type TEXT,
            PRIMARY KEY (code, date, time, minute_type)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS monthly_kline (
            code TEXT, date TEXT, open REAL, high REAL, low REAL,
            close REAL, volume INTEGER, amount REAL,
            PRIMARY KEY (code, date)
        )''')

        conn.commit()
        conn.close()

    def get_stock_list(self) -> List[str]:
        src = self.source
        if src == 'tencent':
            stocks = self._get_stock_list_sina()
            if stocks:
                return stocks
            return self._get_stock_list_db()
        elif src == 'sina':
            stocks = self._get_stock_list_sina()
            if stocks:
                return stocks
            return self._get_stock_list_db()
        else:
            return self._get_stock_list_baostock()

    def _get_stock_list_sina(self) -> List[str]:
        session = _get_session()
        stocks = []
        page = 1
        try:
            while True:
                url = f'{_SINA_LIST_URL}?page={page}&num=80&sort=symbol&asc=1&node=hs_a'
                r = session.get(url, timeout=10)
                if r.status_code != 200 or not r.text.strip():
                    break
                data = json.loads(r.text)
                if not data:
                    break
                for item in data:
                    code = item.get('code', '')
                    symbol = item.get('symbol', '')
                    if code and len(code) == 6 and code.isdigit():
                        if symbol.startswith('sh') and code.startswith('6'):
                            stocks.append(code)
                        elif symbol.startswith('sz') and code.startswith(('0', '1', '2', '3')):
                            stocks.append(code)
                page += 1
                time.sleep(0.3)
                if len(data) < 80:
                    break
        except Exception as e:
            print(f"[WARN] Sina stock list failed: {e}")

        if not stocks:
            return self._get_stock_list_eastmoney()
        return sorted(set(stocks))

    def _get_stock_list_eastmoney(self) -> List[str]:
        session = _get_session()
        stocks = []
        try:
            url = ('https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=6000&po=1&np=1'
                   '&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12'
                   '&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048'
                   '&fields=f12,f13')
            r = session.get(url, timeout=15)
            if r.status_code == 200:
                data = json.loads(r.text)
                diff = data.get('data', {}).get('diff', [])
                for item in diff:
                    code = str(item.get('f12', ''))
                    market = item.get('f13', 0)
                    if code and len(code) == 6 and code.isdigit():
                        if market == 1 and code.startswith('6'):
                            stocks.append(code)
                        elif market == 0 and code.startswith(('0', '1', '2', '3')):
                            stocks.append(code)
        except Exception as e:
            print(f"[WARN] Eastmoney stock list failed: {e}")
        return sorted(set(stocks))

    def _get_stock_list_db(self) -> List[str]:
        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute('SELECT DISTINCT code FROM stock_kline')
            stocks = sorted(set(str(row[0]) for row in c.fetchall()))
            conn.close()
            return stocks
        except Exception:
            return []

    def _get_stock_list_baostock(self) -> List[str]:
        import baostock as bs
        today = datetime.now().strftime('%Y-%m-%d')
        lg = bs.login()
        if lg.error_code != '0':
            print(f"[ERROR] baostock login failed: {lg.error_msg}")
            return self._get_stock_list_db()

        try:
            rs = bs.query_all_stock(today)
            stocks = []
            if rs.error_code == '0':
                while rs.next():
                    row = rs.get_row_data()
                    bs_code = str(row[0]).lower()
                    parts = bs_code.split('.', 1)
                    if len(parts) != 2:
                        continue
                    market, code = parts
                    if not code.isdigit() or len(code) != 6:
                        continue
                    if market == 'sh' and code.startswith('6'):
                        stocks.append(code)
                    elif market == 'sz' and code.startswith(('0', '1', '2', '3')):
                        stocks.append(code)

            if not stocks:
                return self._get_stock_list_db()
            return sorted(set(stocks))
        finally:
            try:
                bs.logout()
            except Exception:
                pass

    def get_existing_codes(self) -> Set[str]:
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute('SELECT DISTINCT code FROM stock_kline')
        codes = set(row[0] for row in c.fetchall())
        conn.close()
        return codes

    def get_stale_codes(self, stale_days: int = 3) -> Set[str]:
        cutoff = (datetime.now() - timedelta(days=stale_days)).strftime('%Y-%m-%d')
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute("SELECT code FROM stock_kline GROUP BY code HAVING MAX(date) < ?", (cutoff,))
        codes = set(row[0] for row in c.fetchall())
        conn.close()
        return codes

    def fetch_daily_kline(self, stock_code: str, days: int = 1095) -> list:
        src = self.source
        if src == 'tencent':
            data = self._fetch_daily_tencent(stock_code, days)
            if data:
                return data
            data = self._fetch_daily_sina(stock_code, days)
            if data:
                return data
            return self._fetch_daily_baostock(stock_code, days)
        elif src == 'sina':
            data = self._fetch_daily_sina(stock_code, days)
            if data:
                return data
            data = self._fetch_daily_tencent(stock_code, days)
            if data:
                return data
            return self._fetch_daily_baostock(stock_code, days)
        else:
            data = self._fetch_daily_baostock(stock_code, days)
            if data:
                return data
            return self._fetch_daily_tencent(stock_code, days)

    def _fetch_daily_tencent(self, stock_code: str, days: int = 1095) -> list:
        prefix = _code_to_prefix(stock_code)
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        count = min(days, 800)

        session = _get_session()
        try:
            url = f'{_TENCENT_DAILY_URL}?param={prefix}{stock_code},day,{start},{end},{count},qfq'
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                return []

            data = json.loads(r.text)
            sd = data.get('data', {}).get(f'{prefix}{stock_code}', {})
            raw = sd.get('qfqday') or sd.get('day') or []

            result = []
            for row in raw:
                if len(row) >= 6:
                    result.append({
                        'code': stock_code, 'date': row[0],
                        'open': float(row[1] or 0), 'close': float(row[2] or 0),
                        'high': float(row[3] or 0), 'low': float(row[4] or 0),
                        'volume': int(float(row[5] or 0)), 'amount': 0,
                    })
            return result
        except Exception:
            return []

    def _fetch_daily_sina(self, stock_code: str, days: int = 1095) -> list:
        try:
            import akshare as ak
            prefix = _code_to_prefix(stock_code)
            end = datetime.now().strftime('%Y%m%d')
            start = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

            df = ak.stock_zh_a_daily(
                symbol=f"{prefix}{stock_code}",
                start_date=start, end_date=end, adjust="qfq"
            )
            if df is None or df.empty:
                return []

            result = []
            for _, row in df.iterrows():
                result.append({
                    'code': stock_code,
                    'date': str(row.get('date', ''))[:10],
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': int(float(row.get('volume', 0))),
                    'amount': float(row.get('amount', 0)),
                })
            return result
        except Exception:
            return []

    def _fetch_daily_baostock(self, stock_code: str, days: int = 1095) -> list:
        import baostock as bs
        bs_code = _code_to_bs(stock_code)
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        try:
            rs = bs.query_history_k_data_plus(
                bs_code, 'date,code,open,high,low,close,volume,amount',
                start_date=start, end_date=end, frequency='d', adjustflag='2'
            )
            if rs.error_code != '0':
                return []

            data = []
            while rs.next():
                row = rs.get_row_data()
                if row[0]:
                    data.append({
                        'code': stock_code, 'date': row[0],
                        'open': float(row[2] or 0), 'high': float(row[3] or 0),
                        'low': float(row[4] or 0), 'close': float(row[5] or 0),
                        'volume': int(float(row[6] or 0)), 'amount': float(row[7] or 0),
                    })
            return data
        except Exception:
            return []

    def fetch_minute_kline(self, stock_code: str, minute_type: int = 5, days: int = 30) -> list:
        src = self.source
        if src == 'tencent':
            data = self._fetch_minute_tencent(stock_code, minute_type, days)
            if data:
                return data
            return self._fetch_minute_baostock(stock_code, minute_type, days)
        else:
            data = self._fetch_minute_baostock(stock_code, minute_type, days)
            if data:
                return data
            return self._fetch_minute_tencent(stock_code, minute_type, days)

    def _fetch_minute_tencent(self, stock_code: str, minute_type: int = 5, days: int = 30) -> list:
        prefix = _code_to_prefix(stock_code)
        freq_map = {5: 'm5', 15: 'm15', 30: 'm30', 60: 'm60'}
        freq = freq_map.get(minute_type, 'm5')
        count = days * 48

        session = _get_session()
        try:
            url = f'{_TENCENT_MIN_URL}?param={prefix}{stock_code},{freq},,{count}'
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                return []

            data = json.loads(r.text)
            raw = data.get('data', {}).get(f'{prefix}{stock_code}', {}).get(freq, [])

            result = []
            for row in raw:
                if len(row) >= 6:
                    dt_str = str(row[0])
                    if len(dt_str) == 12:
                        date_part = f'{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]}'
                        time_part = f'{dt_str[8:10]}:{dt_str[10:12]}'
                    else:
                        date_part = dt_str[:10]
                        time_part = dt_str[11:16] if len(dt_str) > 11 else ''

                    result.append({
                        'code': stock_code, 'date': date_part, 'time': time_part,
                        'open': float(row[1] or 0), 'close': float(row[2] or 0),
                        'high': float(row[3] or 0), 'low': float(row[4] or 0),
                        'volume': int(float(row[5] or 0)),
                    })
            return result
        except Exception:
            return []

    def _fetch_minute_baostock(self, stock_code: str, minute_type: int = 5, days: int = 30) -> list:
        import baostock as bs
        freq_map = {5: '5', 15: '15', 30: '30', 60: '60'}
        freq = freq_map.get(minute_type, '5')
        bs_code = _code_to_bs(stock_code)
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        try:
            rs = bs.query_history_k_data_plus(
                bs_code, 'date,time,code,open,high,low,close,volume',
                start_date=start, end_date=end, frequency=freq, adjustflag='2'
            )
            if rs.error_code != '0':
                return []

            data = []
            while rs.next():
                row = rs.get_row_data()
                if row[0] and row[1]:
                    data.append({
                        'code': stock_code, 'date': row[0], 'time': row[1],
                        'open': float(row[3] or 0), 'high': float(row[4] or 0),
                        'low': float(row[5] or 0), 'close': float(row[6] or 0),
                        'volume': int(float(row[7] or 0)),
                    })
            return data
        except Exception:
            return []

    def fetch_monthly_kline(self, stock_code: str, months: int = 24) -> list:
        src = self.source
        if src == 'tencent':
            data = self._fetch_monthly_tencent(stock_code, months)
            if data:
                return data
            return self._fetch_monthly_baostock(stock_code, months)
        else:
            data = self._fetch_monthly_baostock(stock_code, months)
            if data:
                return data
            return self._fetch_monthly_tencent(stock_code, months)

    def _fetch_monthly_tencent(self, stock_code: str, months: int = 24) -> list:
        prefix = _code_to_prefix(stock_code)
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=months * 35)).strftime('%Y-%m-%d')
        count = min(months + 5, 120)

        session = _get_session()
        try:
            url = f'{_TENCENT_DAILY_URL}?param={prefix}{stock_code},month,{start},{end},{count},qfq'
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                return []

            data = json.loads(r.text)
            sd = data.get('data', {}).get(f'{prefix}{stock_code}', {})
            raw = sd.get('qfqmonth') or sd.get('month') or []

            result = []
            for row in raw:
                if len(row) >= 6:
                    result.append({
                        'code': stock_code, 'date': row[0],
                        'open': float(row[1] or 0), 'close': float(row[2] or 0),
                        'high': float(row[3] or 0), 'low': float(row[4] or 0),
                        'volume': int(float(row[5] or 0)), 'amount': 0,
                    })
            return result
        except Exception:
            return []

    def _fetch_monthly_baostock(self, stock_code: str, months: int = 24) -> list:
        import baostock as bs
        bs_code = _code_to_bs(stock_code)
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=months * 35)).strftime('%Y-%m-%d')

        try:
            rs = bs.query_history_k_data_plus(
                bs_code, 'date,code,open,high,low,close,volume,amount',
                start_date=start, end_date=end, frequency='m', adjustflag='2'
            )
            if rs.error_code != '0':
                return []

            data = []
            while rs.next():
                row = rs.get_row_data()
                if row[0]:
                    data.append({
                        'code': stock_code, 'date': row[0],
                        'open': float(row[2] or 0), 'high': float(row[3] or 0),
                        'low': float(row[4] or 0), 'close': float(row[5] or 0),
                        'volume': int(float(row[6] or 0)), 'amount': float(row[7] or 0),
                    })
            return data
        except Exception:
            return []

    def save_daily(self, data_list: list) -> int:
        if not data_list:
            return 0
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        saved = 0
        for d in data_list:
            try:
                c.execute('''INSERT OR REPLACE INTO stock_kline
                    (code, date, open, high, low, close, volume, amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (d['code'], d['date'], d['open'], d['high'],
                     d['low'], d['close'], d['volume'], d['amount']))
                saved += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
        return saved

    def save_minute(self, data_list: list, minute_type: str) -> int:
        if not data_list:
            return 0
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        saved = 0
        for d in data_list:
            try:
                c.execute('''INSERT OR REPLACE INTO minute_kline
                    (code, date, time, open, high, low, close, volume, minute_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (d['code'], d['date'], d['time'], d['open'],
                     d['high'], d['low'], d['close'], d['volume'], minute_type))
                saved += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
        return saved

    def save_monthly(self, data_list: list) -> int:
        if not data_list:
            return 0
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        saved = 0
        for d in data_list:
            try:
                c.execute('''INSERT OR REPLACE INTO monthly_kline
                    (code, date, open, high, low, close, volume, amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (d['code'], d['date'], d['open'], d['high'],
                     d['low'], d['close'], d['volume'], d['amount']))
                saved += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
        return saved

    def _progress_bar(self, current: int, total: int, code: str, saved: int):
        pct = current / total * 100
        filled = int(30 * pct / 100)
        bar = '█' * filled + '░' * (30 - filled)
        print(f"\r[{bar}] {current}/{total} ({pct:.0f}%) {code} saved:{saved}", end='', flush=True)

    def fetch_all_daily(self, days: int = 1095, limit: int = 0) -> int:
        src = self.source
        if src == 'baostock':
            return self._fetch_all_daily_baostock(days, limit)
        return self._fetch_all_daily_http(days, limit)

    def _fetch_all_daily_http(self, days: int, limit: int) -> int:
        all_stocks = self.get_stock_list()
        if not all_stocks:
            print("[ERROR] Stock pool is empty")
            return 0

        existing = self.get_existing_codes()
        stale = self.get_stale_codes()
        remaining = [s for s in all_stocks if s not in existing or s in stale]
        if limit > 0:
            remaining = remaining[:limit]

        print(f"\nDaily [{self.source}]: total={len(all_stocks)}, existing={len(existing)}, stale={len(stale)}, remaining={len(remaining)}")
        if not remaining:
            print("All daily data is up to date.")
            return 0

        total_saved = 0
        failed = []
        for i, code in enumerate(remaining):
            data = []
            for _ in range(2):
                data = self.fetch_daily_kline(code, days)
                if data:
                    break
                time.sleep(0.5)
            saved = self.save_daily(data)
            total_saved += saved
            if not data:
                failed.append(code)
            self._progress_bar(i + 1, len(remaining), code, saved)
            time.sleep(0.15)

        print()

        if failed:
            print(f"Retrying {len(failed)} failed stocks...")
            for code in failed:
                data = self.fetch_daily_kline(code, max(days, 1825))
                total_saved += self.save_daily(data)
                time.sleep(0.3)

        return total_saved

    def _fetch_all_daily_baostock(self, days: int, limit: int) -> int:
        with _bs_lock:
            conn_mode = _setup_connection()
            if conn_mode != 'direct':
                print(f"[PROXY] Connection mode: {conn_mode}")
            try:
                return self._fetch_all_daily_http(days, limit)
            finally:
                _teardown_connection(conn_mode)

    def fetch_all_minute(self, minute_type: int = 5, days: int = 30, limit: int = 0) -> int:
        src = self.source
        if src == 'baostock':
            return self._fetch_all_minute_baostock(minute_type, days, limit)
        return self._fetch_all_minute_http(minute_type, days, limit)

    def _fetch_all_minute_http(self, minute_type: int, days: int, limit: int) -> int:
        minute_str = f"{minute_type}min"
        all_stocks = self.get_stock_list()
        if not all_stocks:
            return 0

        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute("SELECT DISTINCT code FROM minute_kline WHERE minute_type=?", (minute_str,))
        existing = set(row[0] for row in c.fetchall())
        conn.close()

        remaining = [s for s in all_stocks if s not in existing]
        if limit > 0:
            remaining = remaining[:limit]

        print(f"\n{minute_type}min [{self.source}]: total={len(all_stocks)}, existing={len(existing)}, remaining={len(remaining)}")
        if not remaining:
            return 0

        total_saved = 0
        for i, code in enumerate(remaining):
            data = self.fetch_minute_kline(code, minute_type, days)
            total_saved += self.save_minute(data, minute_str)
            self._progress_bar(i + 1, len(remaining), code, len(data))
            time.sleep(0.15)

        print()
        return total_saved

    def _fetch_all_minute_baostock(self, minute_type: int, days: int, limit: int) -> int:
        with _bs_lock:
            conn_mode = _setup_connection()
            if conn_mode != 'direct':
                print(f"[PROXY] Connection mode: {conn_mode}")
            try:
                return self._fetch_all_minute_http(minute_type, days, limit)
            finally:
                _teardown_connection(conn_mode)

    def fetch_all_monthly(self, months: int = 24, limit: int = 0) -> int:
        src = self.source
        if src == 'baostock':
            return self._fetch_all_monthly_baostock(months, limit)
        return self._fetch_all_monthly_http(months, limit)

    def _fetch_all_monthly_http(self, months: int, limit: int) -> int:
        all_stocks = self.get_stock_list()
        if not all_stocks:
            return 0

        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute('SELECT DISTINCT code FROM monthly_kline')
        existing = set(row[0] for row in c.fetchall())
        conn.close()

        remaining = [s for s in all_stocks if s not in existing]
        if limit > 0:
            remaining = remaining[:limit]

        print(f"\nMonthly [{self.source}]: total={len(all_stocks)}, existing={len(existing)}, remaining={len(remaining)}")
        if not remaining:
            return 0

        total_saved = 0
        for i, code in enumerate(remaining):
            data = self.fetch_monthly_kline(code, months)
            total_saved += self.save_monthly(data)
            self._progress_bar(i + 1, len(remaining), code, len(data))
            time.sleep(0.15)

        print()
        return total_saved

    def _fetch_all_monthly_baostock(self, months: int, limit: int) -> int:
        with _bs_lock:
            conn_mode = _setup_connection()
            if conn_mode != 'direct':
                print(f"[PROXY] Connection mode: {conn_mode}")
            try:
                return self._fetch_all_monthly_http(months, limit)
            finally:
                _teardown_connection(conn_mode)

    def get_db_stats(self) -> dict:
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()

        c.execute('SELECT COUNT(*), COUNT(DISTINCT code), MIN(date), MAX(date) FROM stock_kline')
        daily_count, daily_stocks, daily_min, daily_max = c.fetchone()

        c.execute("SELECT COUNT(*), COUNT(DISTINCT code), MIN(date), MAX(date) FROM minute_kline")
        minute_count, minute_stocks, minute_min, minute_max = c.fetchone()

        conn.close()

        return {
            'daily': {'stocks': daily_stocks, 'rows': daily_count, 'start': daily_min, 'end': daily_max},
            'minute': {'stocks': minute_stocks, 'rows': minute_count, 'start': minute_min, 'end': minute_max},
        }
