"""
模拟交易 API
"""

import json
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import trade_config, PATHS
from src.strategy.position import PositionManager
from src.data.loader import DataLoader
from src.data.realtime import RealtimeQuote
from src.utils.operation_logger import log_trade

mock_trade_bp = Blueprint('mock_trade', __name__, url_prefix='/api/mock')

_manager = PositionManager(
    initial_capital=trade_config.total_capital,
    max_positions=trade_config.max_positions,
)
_loader = DataLoader()
_realtime = RealtimeQuote()

_STATE_FILE = PATHS["cache_dir"] / "mock_account.json"


def _load_state():
    if _STATE_FILE.exists():
        try:
            data = json.loads(_STATE_FILE.read_text(encoding='utf-8'))
            _manager.cash = data.get('cash', _manager.initial_capital)
            for code, pos_data in data.get('positions', {}).items():
                from src.strategy.position import Position
                _manager.positions[code] = Position(
                    code=code,
                    entry_price=pos_data['entry_price'],
                    shares=pos_data['shares'],
                    entry_time=datetime.fromisoformat(pos_data['entry_time']),
                    stop_loss=pos_data.get('stop_loss', 0),
                    take_profit=pos_data.get('take_profit', 999),
                )
            _manager.closed_trades = data.get('closed_trades', [])
        except Exception:
            pass
    else:
        # 文件不存在时，确保账户初始化为100万
        _manager.cash = _manager.initial_capital
        _save_state()


def _save_state():
    try:
        PATHS["cache_dir"].mkdir(parents=True, exist_ok=True)
        state = {
            'cash': _manager.cash,
            'positions': {
                code: {
                    'entry_price': p.entry_price,
                    'shares': p.shares,
                    'entry_time': p.entry_time.isoformat(),
                    'stop_loss': p.stop_loss,
                    'take_profit': p.take_profit,
                }
                for code, p in _manager.positions.items()
            },
            'closed_trades': _manager.closed_trades[-100:],
        }
        _STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass


_load_state()


@mock_trade_bp.route('/account')
def account():
    """账户总览"""
    # 获取持仓实时价格
    positions_data = []
    total_market_value = 0
    total_pnl = 0

    codes = list(_manager.positions.keys())
    prices = _realtime.get_prices(codes) if codes else {}

    for code, pos in _manager.positions.items():
        current_price = prices.get(code, pos.entry_price)
        pos.update_price(current_price)
        pnl = pos.pnl(current_price)
        pnl_pct = pos.pnl_pct(current_price)
        market_value = current_price * pos.shares
        total_market_value += market_value
        total_pnl += pnl
        positions_data.append({
            'code': code,
            'shares': pos.shares,
            'cost_price': pos.entry_price,
            'current_price': current_price,
            'market_value': round(market_value, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct * 100, 2),
            'entry_time': pos.entry_time.strftime('%Y-%m-%d %H:%M'),
        })

    total_equity = _manager.cash + total_market_value
    daily_pnl = total_equity - _manager.initial_capital

    return jsonify({
        'success': True,
        'data': {
            'total_assets': round(total_equity, 2),
            'cash': round(_manager.cash, 2),
            'position_value': round(total_market_value, 2),
            'daily_pnl': round(daily_pnl, 2),
            'daily_pnl_pct': round(daily_pnl / _manager.initial_capital * 100, 2),
            'positions': positions_data,
            'position_count': len(_manager.positions),
            'max_positions': _manager.max_positions,
        }
    })


@mock_trade_bp.route('/positions')
def positions():
    """持仓列表"""
    codes = list(_manager.positions.keys())
    prices = _realtime.get_prices(codes) if codes else {}

    data = []
    for code, pos in _manager.positions.items():
        current_price = prices.get(code, pos.entry_price)
        data.append({
            'code': code,
            'shares': pos.shares,
            'cost_price': pos.entry_price,
            'current_price': current_price,
            'pnl': round(pos.pnl(current_price), 2),
            'pnl_pct': round(pos.pnl_pct(current_price) * 100, 2),
        })
    return jsonify({'success': True, 'data': data})


@mock_trade_bp.route('/buy', methods=['POST'])
def buy():
    """模拟买入"""
    body = request.get_json(silent=True) or {}
    code = body.get('code', '').strip()
    price = body.get('price', 0)
    shares = body.get('shares', 0)

    if not code or price <= 0 or shares <= 0:
        return jsonify({'success': False, 'error': '参数无效: code/price/shares'}), 400

    shares = int(shares / 100) * 100
    if shares < 100:
        return jsonify({'success': False, 'error': '最少买入 100 股'}), 400

    pos = _manager.open_position(code, price, shares)
    if not pos:
        return jsonify({'success': False, 'error': '无法买入（持仓已满/现金不足/已持有）'}), 400

    _save_state()
    log_trade('buy', code, price=price, quantity=shares, result='success')
    return jsonify({
        'success': True,
        'data': {
            'code': code, 'price': price, 'shares': shares,
            'cash_remaining': round(_manager.cash, 2),
        }
    })


@mock_trade_bp.route('/sell', methods=['POST'])
def sell():
    """模拟卖出"""
    body = request.get_json(silent=True) or {}
    code = body.get('code', '').strip()
    price = body.get('price', 0)

    if not code:
        return jsonify({'success': False, 'error': '缺少 code'}), 400

    # 如果没传价格，取实时价
    if price <= 0:
        price = _realtime.get_price(code) or 0
    if price <= 0:
        return jsonify({'success': False, 'error': '无法获取价格'}), 400

    pnl = _manager.close_position(code, price, reason='manual_sell')
    if pnl is None:
        return jsonify({'success': False, 'error': '未持有该股票'}), 400

    _save_state()
    log_trade('sell', code, price=price, result='success', details=f'pnl={pnl:.2f}')
    return jsonify({
        'success': True,
        'data': {
            'code': code, 'price': price, 'pnl': round(pnl, 2),
            'cash_remaining': round(_manager.cash, 2),
        }
    })


@mock_trade_bp.route('/reset', methods=['POST'])
def reset():
    """重置账户"""
    _manager.cash = _manager.initial_capital
    _manager.positions.clear()
    _manager.closed_trades.clear()
    _manager.daily_pnl = 0
    _manager.daily_trades = 0
    _save_state()
    log_trade('reset', '', details=f'capital={_manager.initial_capital}')
    return jsonify({'success': True, 'message': '账户已重置'})
