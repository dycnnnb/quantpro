"""
A股市场日历 — 休市检测 & 交易日判断

数据源优先级:
  1. akshare 在线交易日历（最准确，需联网）
  2. 内置 2024-2027 法定节假日表（离线兜底）
  3. 周末判断（最终兜底）
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from functools import lru_cache

_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "trade_calendar.json"

_A_SHARE_HOLIDAYS_2024 = {
    "2024-01-01", "2024-02-09", "2024-02-10", "2024-02-11", "2024-02-12",
    "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16", "2024-02-17",
    "2024-04-04", "2024-04-05", "2024-04-06",
    "2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-05",
    "2024-06-08", "2024-06-09", "2024-06-10",
    "2024-09-15", "2024-09-16", "2024-09-17",
    "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04",
    "2024-10-05", "2024-10-06", "2024-10-07",
}

_A_SHARE_HOLIDAYS_2025 = {
    "2025-01-01",
    "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
    "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",
    "2025-04-04", "2025-04-05", "2025-04-06",
    "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
    "2025-05-31", "2025-06-01", "2025-06-02",
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04",
    "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
}

_A_SHARE_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-02",
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-02-20",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07",
}

_A_SHARE_HOLIDAYS_2027 = {
    "2027-01-01",
    "2027-02-06", "2027-02-07", "2027-02-08", "2027-02-09",
    "2027-02-10", "2027-02-11", "2027-02-12",
    "2027-04-03", "2027-04-04", "2027-04-05",
    "2027-05-01", "2027-05-02", "2027-05-03",
    "2027-06-09", "2027-06-10", "2027-06-11",
    "2027-10-01", "2027-10-02", "2027-10-03", "2027-10-04",
    "2027-10-05", "2027-10-06", "2027-10-07",
}

_BUILTIN_HOLIDAYS = (
    _A_SHARE_HOLIDAYS_2024 | _A_SHARE_HOLIDAYS_2025
    | _A_SHARE_HOLIDAYS_2026 | _A_SHARE_HOLIDAYS_2027
)

_A_SHARE_EXTRA_TRADING_DAYS_2024 = {
    "2024-02-04", "2024-04-07", "2024-04-28", "2024-05-11",
    "2024-09-14", "2024-09-29", "2024-10-12",
}

_A_SHARE_EXTRA_TRADING_DAYS_2025 = {
    "2025-01-26", "2025-02-08", "2025-04-27", "2025-09-28", "2025-10-11",
}

_A_SHARE_EXTRA_TRADING_DAYS_2026 = {
    "2026-02-14", "2026-04-26", "2026-09-27", "2026-10-10",
}

_A_SHARE_EXTRA_TRADING_DAYS_2027 = {
    "2027-02-06", "2027-04-25", "2027-09-26", "2027-10-09",
}

_BUILTIN_EXTRA_TRADING = (
    _A_SHARE_EXTRA_TRADING_DAYS_2024 | _A_SHARE_EXTRA_TRADING_DAYS_2025
    | _A_SHARE_EXTRA_TRADING_DAYS_2026 | _A_SHARE_EXTRA_TRADING_DAYS_2027
)


@lru_cache(maxsize=1)
def _load_cached_calendar() -> set:
    if _CACHE_FILE.exists():
        try:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            if data.get("source") == "akshare" and data.get("holidays"):
                return set(data["holidays"])
        except Exception:
            pass
    return set()


def _save_calendar(holidays: set, source: str = "akshare"):
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": source,
        "updated": datetime.now().isoformat(),
        "holidays": sorted(holidays),
    }
    _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_akshare_calendar() -> set | None:
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        trade_dates = set(df["trade_date"].dt.strftime("%Y-%m-%d").tolist())
        all_dates = set()
        start = date(2024, 1, 1)
        end = date(2027, 12, 31)
        d = start
        while d <= end:
            ds = d.strftime("%Y-%m-%d")
            if ds not in trade_dates and d.weekday() < 5:
                all_dates.add(ds)
            d += timedelta(days=1)
        _save_calendar(all_dates, "akshare")
        _load_cached_calendar.cache_clear()
        return all_dates
    except Exception as e:
        print(f"[market_calendar] akshare 日历获取失败: {e}")
        return None


def get_holidays() -> set:
    cached = _load_cached_calendar()
    if cached:
        return cached | _BUILTIN_HOLIDAYS
    return _BUILTIN_HOLIDAYS


def is_trading_day(d: date | datetime | None = None) -> bool:
    if d is None:
        d = datetime.now()
    if isinstance(d, datetime):
        d = d.date()
    ds = d.strftime("%Y-%m-%d")
    if ds in _BUILTIN_EXTRA_TRADING:
        return True
    if ds in get_holidays():
        return False
    return d.weekday() < 5


def is_market_open(dt: datetime | None = None) -> bool:
    if dt is None:
        dt = datetime.now()
    if not is_trading_day(dt):
        return False
    h, m = dt.hour, dt.minute
    if (9 <= h < 11) or (h == 11 and m <= 30) or (13 <= h < 15):
        return True
    return False


def is_premarket(dt: datetime | None = None) -> bool:
    if dt is None:
        dt = datetime.now()
    if not is_trading_day(dt):
        return False
    h, m = dt.hour, dt.minute
    return h < 9 or (h == 9 and m < 15)


def is_market_close_time(dt: datetime | None = None) -> bool:
    if dt is None:
        dt = datetime.now()
    if not is_trading_day(dt):
        return False
    h, m = dt.hour, dt.minute
    return h == 15 and m < 30


def get_market_status(dt: datetime | None = None) -> dict:
    if dt is None:
        dt = datetime.now()
    trading = is_trading_day(dt)
    open_now = is_market_open(dt)

    if not trading:
        reason = "周末休市" if dt.weekday() >= 5 else "法定节假日休市"
        if dt.strftime("%Y-%m-%d") not in _BUILTIN_HOLIDAYS and dt.weekday() < 5:
            reason = "休市"
        status = "closed"
    elif open_now:
        reason = "交易中"
        status = "trading"
    elif is_premarket(dt):
        reason = "盘前集合竞价"
        status = "premarket"
    elif is_market_close_time(dt):
        reason = "盘后清算"
        status = "closing"
    elif dt.hour < 9:
        reason = "盘前等待"
        status = "premarket"
    elif dt.hour >= 15:
        reason = "已收盘"
        status = "closed"
    else:
        reason = "午间休市"
        status = "lunch_break"

    return {
        "is_trading_day": trading,
        "is_market_open": open_now,
        "status": status,
        "reason": reason,
        "current_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
    }


def last_trading_day(d: date | datetime | None = None) -> date:
    if d is None:
        d = datetime.now()
    if isinstance(d, datetime):
        d = d.date()
    d = d - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date | datetime | None = None) -> date:
    if d is None:
        d = datetime.now()
    if isinstance(d, datetime):
        d = d.date()
    d = d + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d
