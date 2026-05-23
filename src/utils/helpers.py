"""
通用工具函数
"""

from datetime import datetime, timedelta


def is_trading_day(date=None) -> bool:
    from src.utils.market_calendar import is_trading_day as _is_trading_day
    d = date or datetime.now()
    if isinstance(d, datetime):
        d = d.date() if hasattr(d, 'date') else d
    return _is_trading_day(d)


def last_trading_day(date=None) -> datetime:
    from src.utils.market_calendar import last_trading_day as _last_trading_day
    d = date or datetime.now()
    if isinstance(d, datetime):
        d = d.date() if hasattr(d, 'date') else d
    result = _last_trading_day(d)
    if isinstance(result, datetime):
        return result
    return datetime.combine(result, datetime.min.time())


def format_code(code: str) -> str:
    """格式化股票代码为 baostock 格式"""
    code = code.strip()
    if '.' in code:
        return code
    if code.startswith('6'):
        return f"sh.{code}"
    return f"sz.{code}"


def parse_code(bs_code: str) -> str:
    """从 baostock 格式解析纯代码"""
    if '.' in bs_code:
        return bs_code.split('.')[1]
    return bs_code
