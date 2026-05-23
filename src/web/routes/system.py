"""
系统状态 API
"""

import platform
import sys
from datetime import datetime

from flask import Blueprint, jsonify
from config.settings import DB, print_config_summary

system_bp = Blueprint('system', __name__, url_prefix='/api/system')


@system_bp.route('/status')
def status():
    db_status = {}
    for name, path in DB.items():
        db_status[name] = {'path': str(path), 'exists': path.exists()}
    return jsonify({'success': True, 'data': {'databases': db_status}})


@system_bp.route('/info')
def system_info():
    import sqlite3
    info = {
        'python': sys.version,
        'platform': platform.platform(),
        'time': datetime.now().isoformat(),
        'databases': {},
    }
    for name, path in DB.items():
        if path.exists():
            size_mb = path.stat().st_size / 1024 / 1024
            try:
                conn = sqlite3.connect(str(path))
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()]
                conn.close()
                info['databases'][name] = {
                    'size_mb': round(size_mb, 1),
                    'tables': len(tables),
                    'exists': True,
                }
            except Exception:
                info['databases'][name] = {'exists': True, 'error': True}
        else:
            info['databases'][name] = {'exists': False}

    try:
        from src.execution.trader import trader
        info['ths_connected'] = trader.is_connected()
    except Exception:
        info['ths_connected'] = False

    try:
        from config.settings import ai_config
        info['ai_configured'] = bool(ai_config.api_key)
        info['ai_model'] = ai_config.pro_model
    except Exception:
        info['ai_configured'] = False

    return jsonify({'success': True, 'data': info})


@system_bp.route('/health')
def health():
    checks = {}
    all_ok = True

    for name, path in DB.items():
        ok = path.exists()
        checks[f'db_{name}'] = ok
        if not ok:
            all_ok = False

    try:
        from src.data.realtime import RealtimeQuote
        rt = RealtimeQuote()
        price = rt.get_price('000001')
        checks['realtime'] = price is not None and price > 0
        if not checks['realtime']:
            all_ok = False
    except Exception:
        checks['realtime'] = False
        all_ok = False

    try:
        from config.settings import DEEPSEEK_API_KEY
        checks['ai_configured'] = bool(DEEPSEEK_API_KEY)
    except Exception:
        checks['ai_configured'] = False

    code = 200 if all_ok else 503
    return jsonify({'success': all_ok, 'status': 'ok' if all_ok else 'degraded', 'checks': checks}), code
