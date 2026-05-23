"""
操作日志查询 API
"""

import sqlite3
from flask import Blueprint, request, jsonify
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DB

logs_bp = Blueprint('logs', __name__, url_prefix='/api/logs')


@logs_bp.route('')
def query_logs():
    """查询操作日志 支持分页和筛选"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    category = request.args.get('category', '')
    action = request.args.get('action', '')
    search = request.args.get('search', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    where = []
    params = []
    if category:
        where.append("category = ?")
        params.append(category)
    if action:
        where.append("action LIKE ?")
        params.append(f"%{action}%")
    if search:
        where.append("(detail LIKE ? OR code LIKE ? OR name LIKE ?)")
        params += [f"%{search}%"] * 3
    if start_date:
        where.append("timestamp >= ?")
        params.append(start_date)
    if end_date:
        where.append("timestamp <= ?")
        params.append(end_date + " 23:59:59")

    where_clause = " AND ".join(where) if where else "1=1"

    try:
        with sqlite3.connect(str(DB["quantpro"])) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            c.execute(f"SELECT COUNT(*) FROM operation_logs WHERE {where_clause}", params)
            total = c.fetchone()[0]

            offset = (page - 1) * per_page
            c.execute(
                f"SELECT * FROM operation_logs WHERE {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [per_page, offset]
            )
            rows = [dict(r) for r in c.fetchall()]
    except Exception:
        total = 0
        rows = []

    return jsonify({
        'success': True,
        'data': rows,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
    })


@logs_bp.route('/stats')
def log_stats():
    """日志统计"""
    try:
        with sqlite3.connect(str(DB["quantpro"])) as conn:
            c = conn.cursor()

            c.execute("SELECT COUNT(*) FROM operation_logs")
            total = c.fetchone()[0]

            c.execute("SELECT category, COUNT(*) FROM operation_logs GROUP BY category")
            by_category = dict(c.fetchall())

            c.execute("SELECT COUNT(*) FROM operation_logs WHERE status = 'error'")
            errors = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM operation_logs WHERE category = 'trade'")
            trades = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM operation_logs WHERE category = 'api'")
            api_calls = c.fetchone()[0]

            c.execute("SELECT AVG(duration_ms) FROM operation_logs WHERE category = 'api' AND duration_ms > 0")
            avg_duration = c.fetchone()[0] or 0
    except Exception:
        total = 0
        by_category = {}
        errors = 0
        trades = 0
        api_calls = 0
        avg_duration = 0

    return jsonify({
        'success': True,
        'data': {
            'total': total,
            'by_category': by_category,
            'errors': errors,
            'trades': trades,
            'api_calls': api_calls,
            'avg_api_duration_ms': round(avg_duration, 1),
        }
    })


@logs_bp.route('/recent')
def recent_logs():
    """最近日志"""
    limit = request.args.get('limit', 20, type=int)
    try:
        with sqlite3.connect(str(DB["quantpro"])) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM operation_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()]
    except Exception:
        rows = []
    return jsonify({'success': True, 'data': rows, 'count': len(rows)})
