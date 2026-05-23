"""
操作日志系统
文件日志 + 数据库日志 + Flask 中间件
"""

import json
import logging
import sqlite3
import sys
import threading
import time
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DB, PATHS

_log_lock = threading.Lock()
_initialized = False


def _get_log_dir() -> Path:
    d = PATHS["log_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_logger(name: str, filename: str) -> logging.Logger:
    logger = logging.getLogger(f"quant.{name}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    log_file = _get_log_dir() / filename
    fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger


# ── 日志器实例 ────────────────────────────────────────────────────
_api_logger = _get_logger("api", "api.log")
_trade_logger = _get_logger("trade", "trade.log")
_system_logger = _get_logger("system", "system.log")
_error_logger = _get_logger("error", "error.log")


# ── 数据库表 ─────────────────────────────────────────────────────
def init_log_table():
    """初始化 operation_logs 表"""
    global _initialized
    if _initialized:
        return
    try:
        conn = sqlite3.connect(str(DB["quantpro"]))
        conn.execute('''CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            category TEXT NOT NULL,
            action TEXT,
            code TEXT,
            name TEXT,
            detail TEXT,
            status TEXT DEFAULT 'ok',
            ip TEXT,
            duration_ms REAL
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_oplog_ts ON operation_logs(timestamp)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_oplog_cat ON operation_logs(category)')
        conn.commit()
        conn.close()
        _initialized = True
    except Exception:
        pass


def _save_to_db(category: str, action: str = '', code: str = '', name: str = '',
                detail: str = '', status: str = 'ok', ip: str = '', duration_ms: float = 0):
    try:
        conn = sqlite3.connect(str(DB["quantpro"]))
        conn.execute(
            '''INSERT INTO operation_logs (timestamp, category, action, code, name, detail, status, ip, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), category, action, code, name, detail, status, ip, duration_ms)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── 便捷函数 ─────────────────────────────────────────────────────
def log_api(method: str, path: str, status_code: int, duration_ms: float,
            ip: str = '', error: str = ''):
    """记录 API 请求"""
    status = 'error' if status_code >= 400 or error else 'ok'
    msg = f"{method} {path} -> {status_code} ({duration_ms:.0f}ms)"
    if error:
        msg += f" [{error}]"
    _api_logger.info(msg)
    _save_to_db('api', f"{method} {path}", detail=msg, status=status, ip=ip, duration_ms=duration_ms)


def log_trade(action: str, code: str, name: str = '', price: float = 0,
              quantity: int = 0, result: str = 'success', details: str = ''):
    """记录交易操作"""
    msg = f"{action.upper()} {code} {name} price={price} qty={quantity} -> {result}"
    if details:
        msg += f" [{details}]"
    level = logging.INFO if result == 'success' else logging.WARNING
    _trade_logger.log(level, msg)
    _save_to_db('trade', action, code=code, name=name, detail=msg, status=result)


def log_system(event: str, detail: str = ''):
    """记录系统事件"""
    msg = f"{event}"
    if detail:
        msg += f" | {detail}"
    _system_logger.info(msg)
    _save_to_db('system', event, detail=detail)


def log_error(error_msg: str, exc_info: bool = True):
    """记录错误"""
    _error_logger.error(error_msg, exc_info=exc_info)
    _save_to_db('error', detail=error_msg, status='error')


def log_ai(operation: str, detail: str = '', duration_ms: float = 0):
    """记录 AI 操作"""
    msg = f"AI: {operation}"
    if detail:
        msg += f" | {detail}"
    _system_logger.info(msg)
    _save_to_db('ai', operation, detail=detail, duration_ms=duration_ms)


# ── Flask 中间件 ─────────────────────────────────────────────────
_request_start = threading.local()


def before_request_handler():
    """Flask before_request 钩子"""
    _request_start.time = time.time()


def after_request_handler(response):
    """Flask after_request 钩子"""
    try:
        duration_ms = (time.time() - getattr(_request_start, 'time', time.time())) * 1000
        from flask import request
        path = request.path
        # 静态文件不记录
        if path.startswith(('/js/', '/css/', '/favicon', '/static/')):
            return response
        log_api(
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            ip=request.remote_addr or '',
        )
    except Exception:
        pass
    return response


# ── 启动时初始化 ─────────────────────────────────────────────────
init_log_table()
