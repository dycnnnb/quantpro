"""
交易 API
"""

from flask import Blueprint, request, jsonify
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import PATHS

trade_bp = Blueprint('trade', __name__, url_prefix='/api/trade')


@trade_bp.route('/buy', methods=['POST'])
def trade_buy():
    data = request.get_json(silent=True) or {}
    code = data.get('code', '')
    price = float(data.get('price', 0))
    shares = int(data.get('shares', 0))
    if not code or price <= 0 or shares <= 0:
        return jsonify({'success': False, 'error': '参数不完整'})
    try:
        cache_file = PATHS.get("cache_dir", Path("data/cache")) / "mock_account.json"
        if not cache_file.exists():
            return jsonify({'success': False, 'error': '账户不存在'})
        state = json.loads(cache_file.read_text(encoding='utf-8'))
        cost = price * shares
        if state.get('cash', 0) < cost:
            return jsonify({'success': False, 'error': '资金不足'})
        positions = state.get('positions', {})
        if code in positions:
            pos = positions[code]
            total_shares = pos.get('shares', 0) + shares
            total_cost = pos.get('entry_price', 0) * pos.get('shares', 0) + cost
            pos['entry_price'] = round(total_cost / total_shares, 4)
            pos['shares'] = total_shares
            pos['current_price'] = price
        else:
            positions[code] = {'entry_price': price, 'shares': shares, 'current_price': price}
        state['cash'] = round(state.get('cash', 0) - cost, 2)
        state['positions'] = positions
        cache_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        return jsonify({'success': True, 'message': f'买入 {code} {shares}股@{price}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@trade_bp.route('/sell', methods=['POST'])
def trade_sell():
    data = request.get_json(silent=True) or {}
    code = data.get('code', '')
    price = float(data.get('price', 0))
    shares = int(data.get('shares', 0))
    if not code or price <= 0 or shares <= 0:
        return jsonify({'success': False, 'error': '参数不完整'})
    try:
        cache_file = PATHS.get("cache_dir", Path("data/cache")) / "mock_account.json"
        if not cache_file.exists():
            return jsonify({'success': False, 'error': '账户不存在'})
        state = json.loads(cache_file.read_text(encoding='utf-8'))
        positions = state.get('positions', {})
        if code not in positions:
            return jsonify({'success': False, 'error': f'未持有 {code}'})
        pos = positions[code]
        held_shares = pos.get('shares', 0)
        sell_shares = min(shares, held_shares)
        revenue = price * sell_shares
        state['cash'] = round(state.get('cash', 0) + revenue, 2)
        if sell_shares >= held_shares:
            del positions[code]
        else:
            pos['shares'] = held_shares - sell_shares
            pos['current_price'] = price
        state['positions'] = positions
        cache_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        return jsonify({'success': True, 'message': f'卖出 {code} {sell_shares}股@{price}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@trade_bp.route('/paper/buy', methods=['POST'])
def paper_buy():
    data = request.get_json()
    code = data.get('code')
    price = data.get('price')
    shares = data.get('shares')
    if not all([code, price, shares]):
        return jsonify({'success': False, 'error': 'Missing params'})
    return jsonify({'success': True, 'message': f'Paper buy {code}'})


@trade_bp.route('/paper/sell', methods=['POST'])
def paper_sell():
    data = request.get_json()
    code = data.get('code')
    if not code:
        return jsonify({'success': False, 'error': 'Missing code'})
    return jsonify({'success': True, 'message': f'Paper sell {code}'})
