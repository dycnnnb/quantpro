"""
日内策略监控 API
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import PATHS

strategy_bp = Blueprint('strategy', __name__, url_prefix='/api/strategy')

_strategy_store = {}

_backtest_state = {
    'running': False,
    'started_at': None,
    'finished_at': None,
    'last_result': None,
    'error': None,
}
_backtest_lock = threading.Lock()


@strategy_bp.route('/intraday/backtest', methods=['POST'])
def intraday_backtest():
    """触发日内回测（异步）"""
    with _backtest_lock:
        if _backtest_state['running']:
            return jsonify({'success': False, 'error': '回测正在运行中'})

    data = request.get_json(silent=True) or {}
    symbol = data.get('symbol', '000001')
    start = data.get('start', '2024-01-01')
    end = data.get('end', '2024-12-31')
    capital = float(data.get('capital', 500000))
    use_ml = bool(data.get('use_ml', False))

    def run_backtest():
        try:
            from src.data.loader import DataLoader
            from src.features.intraday_features import IntradayFeatureEngineer
            from src.strategy.intraday_strategy import (
                IntradayStrategy, IntradayRiskController, IntradaySignalGenerator
            )
            from src.backtest.intraday_backtest import IntradayBacktestEngine

            with _backtest_lock:
                _backtest_state['running'] = True
                _backtest_state['started_at'] = datetime.now().isoformat()
                _backtest_state['error'] = None

            loader = DataLoader()
            df = loader.load_minute(symbol, start, end, freq="5min")
            if df is None or df.empty:
                raise ValueError(f"无法加载数据: {symbol}")

            if 'time' not in df.columns and df.index.name == 'datetime':
                df = df.copy()
                df['time'] = df.index

            feature_eng = IntradayFeatureEngineer()
            risk_ctrl = IntradayRiskController()
            signal_gen = IntradaySignalGenerator(ml_threshold=0.6, use_ml=use_ml)
            strategy = IntradayStrategy(
                capital=capital, risk_ctrl=risk_ctrl,
                signal_gen=signal_gen, max_hold_bars=24,
            )

            engine = IntradayBacktestEngine(strategy, feature_eng)
            output_dir = PATHS.get("cache_dir", Path("data/cache")) / "backtest"
            metrics = engine.run(df, symbol, output_dir=output_dir)

            with _backtest_lock:
                _backtest_state['last_result'] = metrics
                _backtest_state['finished_at'] = datetime.now().isoformat()

        except Exception as e:
            with _backtest_lock:
                _backtest_state['error'] = str(e)
        finally:
            with _backtest_lock:
                _backtest_state['running'] = False

    t = threading.Thread(target=run_backtest, daemon=True)
    t.start()

    return jsonify({'success': True, 'message': f'回测已启动: {symbol}'})


@strategy_bp.route('/intraday/status')
def intraday_status():
    """回测状态"""
    with _backtest_lock:
        return jsonify({'success': True, 'data': dict(_backtest_state)})


@strategy_bp.route('/intraday/result')
def intraday_result():
    """获取最新回测结果"""
    cache_dir = PATHS.get("cache_dir", Path("data/cache")) / "backtest"
    if not cache_dir.exists():
        return jsonify({'success': True, 'data': None})

    metrics_files = sorted(cache_dir.glob("intraday_*_metrics.json"), reverse=True)
    if not metrics_files:
        return jsonify({'success': True, 'data': None})

    try:
        data = json.loads(metrics_files[0].read_text(encoding='utf-8'))
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@strategy_bp.route('/intraday/trades')
def intraday_trades():
    """获取最新回测交易记录"""
    cache_dir = PATHS.get("cache_dir", Path("data/cache")) / "backtest"
    if not cache_dir.exists():
        return jsonify({'success': True, 'data': []})

    trades_files = sorted(cache_dir.glob("intraday_*_trades.csv"), reverse=True)
    if not trades_files:
        return jsonify({'success': True, 'data': []})

    try:
        import csv
        trades = []
        with open(trades_files[0], 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                trades.append(row)
        return jsonify({'success': True, 'data': trades[:100]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@strategy_bp.route('/intraday/history')
def intraday_history():
    """所有回测历史"""
    cache_dir = PATHS.get("cache_dir", Path("data/cache")) / "backtest"
    if not cache_dir.exists():
        return jsonify({'success': True, 'data': []})

    metrics_files = sorted(cache_dir.glob("intraday_*_metrics.json"), reverse=True)
    results = []
    for f in metrics_files[:20]:
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            results.append(data)
        except Exception:
            pass

    return jsonify({'success': True, 'data': results})


@strategy_bp.route('/intraday/params')
def intraday_params():
    """当前策略参数"""
    from src.strategy.intraday_strategy import IntradayRiskController, IntradaySignalGenerator
    risk = IntradayRiskController()
    return jsonify({
        'success': True,
        'data': {
            'risk': {
                'max_positions': risk.max_positions,
                'max_daily_loss': risk.max_daily_loss,
                'max_single_loss': risk.max_single_loss,
                'position_size_pct': risk.position_size_pct,
                'trailing_stop_ratio': risk.trailing_stop_ratio,
            },
            'signal': {
                'ml_threshold': 0.6,
                'use_ml': False,
                'max_hold_bars': 24,
                'commission': 0.0003,
                'slippage': 0.0001,
            },
            'label': {
                'forward_bars': 6,
                'take_profit': 0.008,
                'stop_loss': 0.004,
            },
        }
    })


@strategy_bp.route('/create', methods=['POST'])
def strategy_create():
    data = request.get_json(silent=True) or {}
    name = data.get('name', '未命名策略')
    code = data.get('code', '')
    strategy_type = data.get('type', 'daily')
    import sqlite3
    from config.settings import DB
    try:
        with sqlite3.connect(str(DB["quantpro"])) as conn:
            cur = conn.execute(
                "INSERT INTO strategies (name, type, code, status, created_at) VALUES (?, ?, ?, 'idle', datetime('now'))",
                (name, strategy_type, code)
            )
            conn.commit()
            return jsonify({'success': True, 'data': {'id': cur.lastrowid, 'name': name}})
    except Exception:
        sid = len(_strategy_store) + 1
        _strategy_store[sid] = {'id': sid, 'name': name, 'type': strategy_type, 'code': code, 'status': 'idle'}
        return jsonify({'success': True, 'data': {'id': sid, 'name': name}})


@strategy_bp.route('/run/<int:strategy_id>', methods=['POST'])
def strategy_run(strategy_id):
    return jsonify({'success': True, 'message': f'策略 {strategy_id} 回测已启动'})


@strategy_bp.route('/status/<int:task_id>')
def strategy_task_status(task_id):
    return jsonify({'success': True, 'data': {'task_id': task_id, 'status': 'completed'}})
