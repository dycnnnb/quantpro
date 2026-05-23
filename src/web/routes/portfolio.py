"""
持仓/组合 API
"""

import sqlite3
from flask import Blueprint, request, jsonify
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DB, PATHS

portfolio_bp = Blueprint('portfolio', __name__, url_prefix='/api/portfolio')


@portfolio_bp.route('/positions')
def positions():
    """持仓列表 — 读取模拟账户"""
    try:
        from src.strategy.position import PositionManager
        pm = PositionManager()
        pos_list = []
        for code, pos in pm.positions.items():
            pos_list.append({
                'code': code,
                'entry_price': pos.entry_price,
                'shares': pos.shares,
                'entry_time': str(pos.entry_time),
                'current_price': pos.entry_price,
                'pnl': pos.pnl(),
                'pnl_pct': pos.pnl_pct(),
            })
        return jsonify({'success': True, 'data': pos_list})
    except Exception:
        return jsonify({'success': True, 'data': []})


@portfolio_bp.route('/summary')
def summary():
    """账户概览"""
    try:
        cache_file = PATHS.get("cache_dir", Path("data/cache")) / "mock_account.json"
        if cache_file.exists():
            import json
            state = json.loads(cache_file.read_text(encoding='utf-8'))
            cash = state.get('cash', 0)
            positions = state.get('positions', {})
            position_value = sum(
                p.get('shares', 0) * p.get('current_price', p.get('entry_price', 0))
                for p in positions.values()
            )
            total_value = cash + position_value
            return jsonify({'success': True, 'data': {
                'cash': cash,
                'equity': total_value,
                'positions': len(positions),
                'total_value': total_value,
                'daily_pnl': state.get('daily_pnl', 0),
            }})
    except Exception:
        pass
    return jsonify({'success': True, 'data': {'cash': 0, 'equity': 0, 'positions': 0, 'total_value': 0, 'daily_pnl': 0}})


@portfolio_bp.route('/history')
def portfolio_history():
    """资金曲线历史 — 仅返回真实交易记录，无数据时返回空列表"""
    try:
        cache_file = PATHS.get("cache_dir", Path("data/cache")) / "mock_account_history.json"
        if cache_file.exists():
            import json
            history = json.loads(cache_file.read_text(encoding='utf-8'))
            if history:
                return jsonify({'success': True, 'data': history})
        return jsonify({'success': True, 'data': [], 'source': 'no_data'})
    except Exception as e:
        return jsonify({'success': True, 'data': [], 'error': str(e)})
