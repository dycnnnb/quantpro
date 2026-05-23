"""
真实交易 API — 基于 easytrader 同花顺客户端
"""

from flask import Blueprint, request, jsonify

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.execution.trader import trader

real_trade_bp = Blueprint('real_trade', __name__, url_prefix='/api/real_trade')


@real_trade_bp.route('/connect', methods=['POST'])
def trade_connect():
    """连接交易客户端"""
    data = request.get_json(silent=True) or {}
    result = trader.connect(
        user=data.get('user', ''),
        password=data.get('password', ''),
        exe_path=data.get('exe_path', ''),
        broker=data.get('broker', 'universal_client'),
    )
    return jsonify(result)


@real_trade_bp.route('/disconnect', methods=['POST'])
def trade_disconnect():
    """断开连接"""
    trader.disconnect()
    return jsonify({'success': True, 'message': '已断开'})


@real_trade_bp.route('/status')
def trade_status():
    """交易连接状态"""
    return jsonify({
        'success': True,
        'data': {'connected': trader.is_connected()}
    })


@real_trade_bp.route('/balance')
def trade_balance():
    """查询账户资金"""
    return jsonify(trader.get_balance())


@real_trade_bp.route('/position')
def trade_position():
    """查询持仓"""
    return jsonify(trader.get_positions())


@real_trade_bp.route('/today_trades')
def trade_today_trades():
    """今日成交"""
    return jsonify(trader.get_today_trades())


@real_trade_bp.route('/today_entrusts')
def trade_today_entrusts():
    """今日委托"""
    return jsonify(trader.get_today_entrusts())


@real_trade_bp.route('/buy', methods=['POST'])
def trade_buy():
    """限价买入"""
    data = request.get_json(silent=True) or {}
    security = data.get('security', '').strip()
    price = data.get('price', 0)
    amount = data.get('amount', 0)

    if not security or price <= 0 or amount <= 0:
        return jsonify({'success': False, 'error': '参数无效: security/price/amount'}), 400

    return jsonify(trader.buy(security=security, price=float(price), amount=int(amount)))


@real_trade_bp.route('/sell', methods=['POST'])
def trade_sell():
    """限价卖出"""
    data = request.get_json(silent=True) or {}
    security = data.get('security', '').strip()
    price = data.get('price', 0)
    amount = data.get('amount', 0)

    if not security or price <= 0 or amount <= 0:
        return jsonify({'success': False, 'error': '参数无效: security/price/amount'}), 400

    return jsonify(trader.sell(security=security, price=float(price), amount=int(amount)))


@real_trade_bp.route('/market_buy', methods=['POST'])
def trade_market_buy():
    """市价买入"""
    data = request.get_json(silent=True) or {}
    security = data.get('security', '').strip()
    amount = data.get('amount', 0)

    if not security or amount <= 0:
        return jsonify({'success': False, 'error': '参数无效'}), 400

    return jsonify(trader.market_buy(security=security, amount=int(amount)))


@real_trade_bp.route('/market_sell', methods=['POST'])
def trade_market_sell():
    """市价卖出"""
    data = request.get_json(silent=True) or {}
    security = data.get('security', '').strip()
    amount = data.get('amount', 0)

    if not security or amount <= 0:
        return jsonify({'success': False, 'error': '参数无效'}), 400

    return jsonify(trader.market_sell(security=security, amount=int(amount)))


@real_trade_bp.route('/cancel', methods=['POST'])
def trade_cancel():
    """撤单"""
    data = request.get_json(silent=True) or {}
    entrust_no = data.get('entrust_no', '')
    if not entrust_no:
        return jsonify({'success': False, 'error': '需要 entrust_no'}), 400
    return jsonify(trader.cancel_entrust(entrust_no))


@real_trade_bp.route('/cancel_all', methods=['POST'])
def trade_cancel_all():
    """撤销全部"""
    return jsonify(trader.cancel_all())


@real_trade_bp.route('/ipo', methods=['POST'])
def trade_ipo():
    """自动申购新股"""
    return jsonify(trader.auto_ipo())
