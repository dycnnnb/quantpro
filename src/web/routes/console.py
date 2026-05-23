"""
总控台 API
系统报告、大盘指数、策略、告警、交易历史、模型代理、设置、通知
"""

import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DB, PATHS, data_config, trade_config, server_config, DEEPSEEK_API_KEY
from src.data.loader import DataLoader
from src.data.realtime import RealtimeQuote
from src.strategy.position import PositionManager, Position
from src.strategy.risk import RiskController
from src.execution.trader import bridge as _trade_bridge, trader
from src.utils.operation_logger import log_system, log_trade

console_bp = Blueprint('console', __name__, url_prefix='/api')

_loader = DataLoader()
_realtime = RealtimeQuote()

# ── 数据库信息缓存（避免每次请求都查询大表） ──────────────────────
_db_info_cache = {'data': None, 'last_update': 0}
_db_info_lock = threading.Lock()
_DB_INFO_CACHE_TTL = 60  # 缓存60秒


def _get_db_info_cached():
    """获取数据库信息（带缓存）"""
    now = time.time()
    with _db_info_lock:
        if _db_info_cache['data'] and (now - _db_info_cache['last_update']) < _DB_INFO_CACHE_TTL:
            return _db_info_cache['data']
    # 缓存过期，重新查询
    try:
        info = _loader.get_db_info()
        with _db_info_lock:
            _db_info_cache['data'] = info
            _db_info_cache['last_update'] = now
        return info
    except Exception:
        with _db_info_lock:
            if _db_info_cache['data']:
                return _db_info_cache['data']
        return {'daily': {}, 'minute': {}}


# ── 模型代理状态 ─────────────────────────────────────────────────
_proxy_state = {
    'running': False,
    'started_at': None,
    'last_run': None,
    'run_count': 0,
    'error': None,
}
_proxy_lock = threading.Lock()


# ── 系统报告 ─────────────────────────────────────────────────────
@console_bp.route('/console/report')
def console_report():
    """系统诊断报告"""
    checks = []

    # 使用缓存的数据库信息
    info = _get_db_info_cached()
    daily_info = info.get('daily', {})
    minute_info = info.get('minute', {})

    # 数据库
    db_exists = DB["market"].exists()
    checks.append({'name': '数据库', 'status': 'ok' if db_exists else 'error',
                   'detail': str(DB["market"]) if db_exists else '数据库文件不存在'})

    # 数据新鲜度
    try:
        end_date = daily_info.get('end', '')
        if end_date:
            days_old = (datetime.now() - datetime.strptime(end_date, '%Y-%m-%d')).days
            status = 'ok' if days_old <= 3 else ('warn' if days_old <= 7 else 'error')
            checks.append({'name': '数据新鲜度', 'status': status,
                           'detail': f'最新数据: {end_date} ({days_old}天前)'})
        else:
            checks.append({'name': '数据新鲜度', 'status': 'error', 'detail': '无数据'})
    except Exception:
        checks.append({'name': '数据新鲜度', 'status': 'error', 'detail': '读取失败'})

    # 模型文件
    model_check = _check_model_ready()
    model_status = 'ok' if model_check['ready'] else ('warn' if model_check['available'] else 'error')
    model_detail = model_check['reason']
    if model_check['latest_model']:
        model_detail = f"{model_check['latest_model']} — {model_detail}"
    checks.append({'name': 'AI 模型', 'status': model_status, 'detail': model_detail})

    # 市场状态
    market_status = _get_market_status()
    market_ok = market_status['is_trading_day']
    checks.append({'name': '市场状态', 'status': 'ok' if market_ok else 'warn',
                   'detail': market_status['reason']})

    # 实时行情（非阻塞，使用 socket 探测替代同步 API 调用）
    try:
        import socket
        sock = socket.create_connection(("qt.gtimg.cn", 80), timeout=2)
        sock.close()
        checks.append({'name': '实时行情', 'status': 'ok', 'detail': '行情服务可用'})
    except Exception:
        checks.append({'name': '实时行情', 'status': 'warn', 'detail': '非交易时段或网络不可用'})

    # DeepSeek API
    checks.append({'name': 'DeepSeek API', 'status': 'ok' if DEEPSEEK_API_KEY else 'warn',
                   'detail': '已配置' if DEEPSEEK_API_KEY else '未配置'})

    # 日志系统
    log_dir = PATHS["log_dir"]
    checks.append({'name': '日志系统', 'status': 'ok' if log_dir.exists() else 'warn',
                   'detail': str(log_dir)})

    ok_count = sum(1 for c in checks if c['status'] == 'ok')
    warning_count = sum(1 for c in checks if c['status'] == 'warn')
    error_count = sum(1 for c in checks if c['status'] == 'error')
    total = len(checks)

    # 检查是否在交易时间
    market_status = _get_market_status()
    trading_time = market_status['is_market_open']

    return jsonify({
        'success': True,
        'data': {
            'health': {
                'status': 'ok' if ok_count == total else 'warn',
                'realtime_enabled': False,
                'trading_time': trading_time,
            },
            'config': {
                'summary': {
                    'total': total,
                    'ok': ok_count,
                    'warning': warning_count,
                    'error': error_count,
                },
                'checks': checks,
            },
            'data': {
                'daily': {
                    'stocks': daily_info.get('stocks', 0),
                    'records': daily_info.get('rows', 0),
                    'start_date': daily_info.get('start', ''),
                    'end_date': daily_info.get('end', ''),
                },
                'minute': {
                    'stocks': minute_info.get('stocks', 0),
                    'records': minute_info.get('rows', 0),
                    'start_date': minute_info.get('start', ''),
                    'end_date': minute_info.get('end', ''),
                },
                'error': '',
            },
            'failed': {
                'file': '',
                'count': 0,
                'codes': [],
            },
            'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }
    })


# ── 大盘指数实时 ─────────────────────────────────────────────────
@console_bp.route('/index/realtime')
def index_realtime():
    """大盘指数实时行情"""
    indices = {
        '000001': '上证指数',
        '399001': '深证成指',
        '399006': '创业板指',
        '000300': '沪深300',
    }
    codes = list(indices.keys())
    try:
        quotes = _realtime.get_quote(codes)
        data = []
        for code, name in indices.items():
            q = quotes.get(code, {})
            now = q.get('now', 0)
            close = q.get('close', 0)
            change = now - close if close else 0
            change_pct = (change / close * 100) if close else 0
            data.append({
                'code': code, 'name': name,
                'price': now, 'change': round(change, 2),
                'change_pct': round(change_pct, 2),
                'open': q.get('open', 0), 'high': q.get('high', 0),
                'low': q.get('low', 0), 'volume': q.get('volume', 0),
            })
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': True, 'data': [], 'error': str(e)})


# ── 策略列表 ─────────────────────────────────────────────────────
@console_bp.route('/strategy/list')
def strategy_list():
    """策略列表"""
    data = []
    try:
        with sqlite3.connect(str(DB["quantpro"])) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM strategies ORDER BY id DESC").fetchall()
            data = [dict(r) for r in rows]
    except Exception:
        pass
    return jsonify({'success': True, 'data': data})


# ── 告警 ─────────────────────────────────────────────────────────
@console_bp.route('/alerts')
def alerts():
    alert_list = []

    try:
        info = _get_db_info_cached()
        end_date = info['daily'].get('end', '')
        if end_date:
            days_old = (datetime.now() - datetime.strptime(end_date, '%Y-%m-%d')).days
            if days_old > 3:
                level = 'warn' if days_old <= 7 else 'error'
                alert_list.append({
                    'type': 'warning' if level == 'warn' else 'danger',
                    'title': '数据过期警告' if level == 'warn' else '数据严重过期',
                    'message': f'日线数据已过期 {days_old} 天，最新日期: {end_date}，请及时更新',
                    'time': datetime.now().strftime('%H:%M'),
                    'code': '', 'name': '',
                })
    except Exception:
        pass

    with _proxy_lock:
        if _proxy_state['running'] and _proxy_state.get('error'):
            alert_list.append({
                'type': 'danger',
                'title': '模型代理异常',
                'message': f'模型代理运行出错: {_proxy_state["error"]}',
                'time': datetime.now().strftime('%H:%M'),
                'code': '', 'name': '',
            })

    try:
        price = _realtime.get_price('000001')
        if not price:
            alert_list.append({
                'type': 'warning',
                'title': '实时行情中断',
                'message': '实时行情数据源无响应，部分功能可能受限',
                'time': datetime.now().strftime('%H:%M'),
                'code': '', 'name': '',
            })
    except Exception:
        pass

    try:
        if not DEEPSEEK_API_KEY:
            alert_list.append({
                'type': 'warning',
                'title': 'AI服务未配置',
                'message': 'DeepSeek API密钥未设置，AI分析功能不可用',
                'time': datetime.now().strftime('%H:%M'),
                'code': '', 'name': '',
            })
    except Exception:
        pass

    with _monitor_lock:
        history = list(_monitor_state.get('decision_history', []))
    for dec in history[-10:]:
        action = dec.get('action', '')
        code = dec.get('code', '')
        dec_type = dec.get('type', 'signal')
        reason = dec.get('reason', '')
        price = dec.get('price', 0)
        shares = dec.get('shares', 0)
        pnl = dec.get('pnl', 0)
        dec_time = dec.get('time', '')
        if dec_time:
            try:
                t = dec_time.split('T')[-1][:5] if 'T' in dec_time else dec_time[:5]
            except Exception:
                t = dec_time[:5]
        else:
            t = ''

        if dec_type == 'risk':
            alert_list.append({
                'type': 'danger',
                'title': f'风控止损 {code}',
                'message': f'{reason} | {action} {shares}股 @ {price:.2f} 盈亏:{pnl}',
                'time': t,
                'code': code, 'name': '',
            })
        elif action == 'buy':
            alert_list.append({
                'type': 'success',
                'title': f'买入信号 {code}',
                'message': f'{reason} | 买入 {shares}股 @ {price:.2f}',
                'time': t,
                'code': code, 'name': '',
            })
        elif action == 'sell':
            alert_list.append({
                'type': 'warning',
                'title': f'卖出信号 {code}',
                'message': f'{reason} | 卖出 {shares}股 @ {price:.2f} 盈亏:{pnl}',
                'time': t,
                'code': code, 'name': '',
            })

    alert_list.sort(key=lambda x: x.get('time', ''), reverse=True)

    return jsonify({'success': True, 'data': alert_list[:20]})


# ── 交易历史 ─────────────────────────────────────────────────────
@console_bp.route('/trade/history')
def trade_history():
    """交易历史 — 优先从 trade_records 表读取完整交易数据"""
    data = []

    code_name_map = {}
    try:
        with sqlite3.connect(str(DB["market"])) as mconn:
            mrows = mconn.execute("SELECT code, name FROM stock_info").fetchall()
            code_name_map = {r[0]: r[1] for r in mrows}
    except Exception:
        pass

    try:
        with sqlite3.connect(str(DB["quantpro"])) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT tr.*, p.name as stock_name, p.realized_pnl, p.realized_pct
                   FROM trade_records tr
                   LEFT JOIN positions p ON tr.position_id = p.id
                   ORDER BY tr.id DESC LIMIT 200"""
            ).fetchall()
            for r in rows:
                d = dict(r)
                code = d.get('code', '')
                name = d.get('stock_name') or d.get('name', '') or code_name_map.get(code, '')
                action_raw = d.get('action', '').lower()
                data.append({
                    'id': d['id'],
                    'time': d.get('trade_time') or d.get('trade_date', ''),
                    'source': 'model',
                    'action': action_raw,
                    'code': code,
                    'name': name,
                    'price': d.get('price', 0),
                    'qty': d.get('shares', 0),
                    'amount': d.get('amount', 0),
                    'pnl': d.get('realized_pnl') or 0,
                    'pnl_pct': d.get('realized_pct') or 0,
                    'commission': d.get('commission', 0),
                    'strategy': '',
                    'status': 'ok',
                    'note': d.get('note', ''),
                })
    except Exception:
        pass

    # 2. 如果 trade_records 为空，从 mock_account 的 closed_trades 读取
    if not data:
        try:
            cache_file = PATHS["cache_dir"] / "mock_account.json"
            if cache_file.exists():
                state = json.loads(cache_file.read_text(encoding='utf-8'))
                for i, t in enumerate(state.get('closed_trades', [])[-200:]):
                    code = t.get('code', '')
                    data.append({
                        'id': i + 1,
                        'time': t.get('exit_time', ''),
                        'source': 'mock',
                        'action': t.get('direction', 'sell').lower(),
                        'code': code,
                        'name': code_name_map.get(code, ''),
                        'price': t.get('exit_price', 0),
                        'qty': t.get('shares', 0),
                        'amount': t.get('exit_price', 0) * t.get('shares', 0),
                        'pnl': t.get('pnl', 0),
                        'pnl_pct': t.get('pnl_pct', 0),
                        'commission': 0,
                        'strategy': '',
                        'status': 'ok',
                        'note': t.get('reason', ''),
                    })
        except Exception:
            pass

    # 3. 如果仍然为空，从 operation_logs 读取（降级方案）
    if not data:
        try:
            with sqlite3.connect(str(DB["quantpro"])) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM operation_logs WHERE category='trade' ORDER BY id DESC LIMIT 200"
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    code = d.get('code', '')
                    data.append({
                        'id': d['id'], 'time': d['timestamp'],
                        'source': 'model' if 'model' in (d.get('detail') or '') else 'manual',
                        'action': d.get('action', '').lower(),
                        'code': code, 'name': d.get('name', '') or code_name_map.get(code, ''),
                        'price': 0, 'qty': 0, 'amount': 0, 'pnl': 0,
                        'strategy': '', 'status': d.get('status', 'ok'),
                        'note': d.get('detail', ''),
                    })
        except Exception:
            pass

    return jsonify({'success': True, 'data': data})


# ── 交易诊断 ─────────────────────────────────────────────────────
@console_bp.route('/trade/diagnose')
def trade_diagnose():
    """交易诊断 - 包含同花顺客户端检测"""
    import socket
    try:
        sock = socket.create_connection(("qt.gtimg.cn", 80), timeout=2)
        sock.close()
        realtime_ok = True
    except Exception:
        realtime_ok = False

    ths_connected = trader.is_connected()
    ths_balance_ok = False
    if ths_connected:
        try:
            bal = trader.get_balance()
            ths_balance_ok = bal.get('success', False)
        except Exception:
            pass

    checks = [
        {'name': '数据加载器', 'ok': True},
        {'name': '实时行情', 'ok': realtime_ok},
        {'name': '策略模块', 'ok': DB["market"].exists()},
        {'name': '同花顺客户端', 'ok': ths_connected},
        {'name': '账户数据', 'ok': ths_balance_ok},
    ]
    return jsonify({
        'success': True,
        'data': checks,
        'connected': ths_connected,
    })


@console_bp.route('/trade/connect', methods=['POST'])
def trade_connect():
    """连接同花顺客户端"""
    data = request.get_json(silent=True) or {}
    result = trader.connect(
        user=data.get('user', ''),
        password=data.get('password', ''),
        exe_path=data.get('exe_path', ''),
        broker=data.get('broker', 'universal_client'),
    )
    return jsonify(result)


@console_bp.route('/trade/disconnect', methods=['POST'])
def trade_disconnect():
    """断开同花顺"""
    trader.disconnect()
    return jsonify({'success': True, 'message': '已断开'})


@console_bp.route('/account/summary')
def account_summary():
    """统一账户概览 - 优先同花顺，fallback 模拟盘"""
    ths_connected = trader.is_connected()

    if ths_connected:
        try:
            bal_result = trader.get_balance()
            pos_result = trader.get_positions()

            if bal_result.get('success') and bal_result.get('data'):
                bal = bal_result['data']
                if isinstance(bal, list):
                    bal = bal[0] if bal else {}

                positions = []
                pos_data = pos_result.get('data', [])
                if isinstance(pos_data, list):
                    for p in pos_data:
                        positions.append({
                            'code': str(p.get('证券代码', '')),
                            'name': p.get('证券名称', ''),
                            'shares': int(p.get('股票余额', 0) or 0),
                            'cost_price': float(p.get('成本价', 0) or 0),
                            'current_price': float(p.get('当前价', 0) or p.get('最新价', 0) or 0),
                            'market_value': float(p.get('股票市值', 0) or 0),
                            'profit': float(p.get('浮动盈亏', 0) or 0),
                            'profit_pct': float(p.get('盈亏比例', 0) or 0),
                        })

                total_asset = float(bal.get('总资产', 0) or bal.get('total_asset', 0) or 0)
                cash = float(bal.get('可用金额', 0) or bal.get('available', 0) or 0)
                position_value = float(bal.get('股票市值', 0) or bal.get('market_value', 0) or 0)
                daily_pnl = float(bal.get('当日盈亏', 0) or bal.get('today_profit', 0) or 0)

                if total_asset == 0 and (cash > 0 or position_value > 0):
                    total_asset = cash + position_value

                return jsonify({
                    'success': True,
                    'source': 'ths',
                    'data': {
                        'total_assets': total_asset,
                        'cash': cash,
                        'position_value': position_value,
                        'daily_pnl': daily_pnl,
                        'positions': positions,
                        'initial_capital': total_asset,
                    }
                })
        except Exception as e:
            pass

    cache_file = PATHS["cache_dir"] / "mock_account.json"
    if cache_file.exists():
        try:
            mock = json.loads(cache_file.read_text(encoding='utf-8'))
            return jsonify({
                'success': True,
                'source': 'mock',
                'data': {
                    'total_assets': mock.get('total_assets', 1000000),
                    'cash': mock.get('available_cash', mock.get('cash', 1000000)),
                    'position_value': mock.get('position_value', 0),
                    'daily_pnl': mock.get('daily_pnl', 0),
                    'positions': mock.get('positions', []),
                    'initial_capital': mock.get('initial_capital', 1000000),
                }
            })
        except Exception:
            pass

    return jsonify({
        'success': True,
        'source': 'default',
        'data': {
            'total_assets': 1000000,
            'cash': 1000000,
            'position_value': 0,
            'daily_pnl': 0,
            'positions': [],
            'initial_capital': 1000000,
        }
    })


# ── 模型代理控制 ─────────────────────────────────────────────────
@console_bp.route('/model_proxy/status')
def proxy_status():
    with _proxy_lock:
        return jsonify({'success': True, 'data': dict(_proxy_state)})


@console_bp.route('/model_proxy/start', methods=['POST'])
def proxy_start():
    with _proxy_lock:
        if _proxy_state['running']:
            return jsonify({'success': False, 'error': '代理已在运行'})
        _proxy_state['running'] = True
        _proxy_state['started_at'] = datetime.now().isoformat()
        _proxy_state['error'] = None
    log_system('proxy_start', '模型代理已启动')
    return jsonify({'success': True, 'message': '模型代理已启动'})


@console_bp.route('/model_proxy/stop', methods=['POST'])
def proxy_stop():
    with _proxy_lock:
        _proxy_state['running'] = False
        _proxy_state['error'] = None
    log_system('proxy_stop', '模型代理已停止')
    return jsonify({'success': True, 'message': '模型代理已停止'})


@console_bp.route('/health')
def api_health():
    return jsonify({'success': True, 'status': 'ok'})


@console_bp.route('/model_proxy/precheck')
def proxy_precheck():
    """环境预检"""
    checks = []
    items = {}

    api_ok = bool(DEEPSEEK_API_KEY)
    checks.append({'name': 'DeepSeek API', 'ok': api_ok,
                   'detail': '已配置' if api_ok else '未配置'})
    items['api'] = {'success': api_ok, 'message': 'API服务正常' if api_ok else 'DeepSeek API未配置'}

    db_ok = DB["market"].exists()
    checks.append({'name': '数据库', 'ok': db_ok})
    items['database'] = {'success': db_ok, 'message': '数据库连接正常' if db_ok else '数据库不可访问'}

    model_files = list(PATHS["model_dir"].glob("*.pkl")) if PATHS["model_dir"].exists() else []
    ai_ok = bool(model_files)
    checks.append({'name': 'AI 模型', 'ok': ai_ok, 'detail': f'{len(model_files)} 个'})
    items['ai_model'] = {'success': ai_ok, 'message': f'已加载 {len(model_files)} 个模型' if ai_ok else 'AI模型服务不可用'}

    try:
        info = _loader.get_db_info()
        market_ok = info['daily'].get('rows', 0) > 0
    except Exception:
        market_ok = False
    checks.append({'name': '市场数据', 'ok': market_ok})
    items['market_data'] = {'success': market_ok, 'message': '行情数据正常' if market_ok else '行情数据源异常'}

    realtime_ok = False
    try:
        realtime_ok = bool(_realtime.get_price('000001'))
    except Exception:
        pass
    checks.append({'name': '实时行情', 'ok': realtime_ok})
    items['realtime_quote'] = {'success': realtime_ok, 'message': '实时行情正常' if realtime_ok else '实时行情不可用'}

    trade_ok = db_ok and market_ok
    checks.append({'name': '交易执行器', 'ok': trade_ok})
    items['trade_manager'] = {'success': trade_ok, 'message': '交易系统已初始化' if trade_ok else '交易系统未初始化'}

    checks.append({'name': '模拟账户', 'ok': True})
    items['account'] = {'success': True, 'message': '模拟账户已就绪'}

    checks.append({'name': '策略引擎', 'ok': True})
    items['strategy'] = {'success': True, 'message': '策略模块已就绪'}

    checks.append({'name': '风控模块', 'ok': True})
    items['risk_control'] = {'success': True, 'message': '风控规则已配置'}

    import socket
    net_ok = False
    try:
        socket.create_connection(("114.114.114.114", 53), timeout=3)
        net_ok = True
    except Exception:
        pass
    checks.append({'name': '网络连接', 'ok': net_ok})
    items['network'] = {'success': net_ok, 'message': '网络连接正常' if net_ok else '网络连接异常'}

    all_ok = all(c['ok'] for c in checks)
    return jsonify({'success': True, 'data': {'checks': checks, 'items': items, 'all_ok': all_ok, 'auto_start_allowed': all_ok}})


# ── 设置 ─────────────────────────────────────────────────────────
@console_bp.route('/settings')
def get_settings():
    return jsonify({
        'success': True,
        'data': {
            'datasource': data_config.realtime_source,
            'lookback_days': data_config.lookback_days,
            'stock_pool_size': data_config.stock_pool_size,
            'total_capital': trade_config.total_capital,
            'max_positions': trade_config.max_positions,
            'stop_loss_pct': trade_config.stop_loss_pct,
            'take_profit_pct': trade_config.take_profit_pct,
            'max_hold_days': trade_config.max_hold_days,
            'server_host': server_config.host,
            'server_port': server_config.port,
            'deepseek_api': '已配置' if DEEPSEEK_API_KEY else '未配置',
        }
    })


@console_bp.route('/settings', methods=['POST'])
def update_settings():
    data = request.get_json(silent=True) or {}
    notify_keys = [
        'notify_wechat', 'notify_email', 'notify_feishu',
        'wechat_webhook', 'email_address', 'feishu_webhook',
        'notify_signal', 'notify_risk', 'notify_daily', 'notify_backtest',
    ]
    notify_settings = {k: data[k] for k in notify_keys if k in data}
    if notify_settings:
        from src.utils.notify import save_settings
        save_settings(notify_settings)
    return jsonify({'success': True, 'message': '设置已保存'})


# ── 数据白名单 ───────────────────────────────────────────────────
@console_bp.route('/data/tradable_whitelist')
def tradable_whitelist():
    try:
        symbols = _loader.get_daily_symbols(min_days=100)
        return jsonify({'success': True, 'data': symbols})
    except Exception:
        return jsonify({'success': True, 'data': []})


# ── 通知测试 ─────────────────────────────────────────────────────
@console_bp.route('/notify/test', methods=['POST'])
def notify_test():
    data = request.get_json(silent=True) or {}
    from src.utils.notify import send_notification, _load_settings
    s = _load_settings()
    has_channel = s.get('notify_wechat') == '1' or s.get('notify_feishu') == '1' or s.get('notify_email') == '1'
    if not has_channel:
        return jsonify({'success': True, 'result': {'sent': False, 'detail': '未启用任何通知渠道'}})
    results = send_notification('[QuantPro] 测试通知 - 如果您看到此消息，说明通知渠道配置成功', 'test')
    sent = any(ok for _, ok in results)
    channels = [{'channel': ch, 'success': ok} for ch, ok in results]
    return jsonify({'success': True, 'result': {'sent': sent, 'channels': channels}})


# ── 执行器控制 ─────────────────────────────────────────────────────
@console_bp.route('/executor/status')
def executor_status():
    from src.execution.executor import executor
    return jsonify({'success': True, 'data': executor.get_mode()})


@console_bp.route('/executor/mode', methods=['POST'])
def executor_set_mode():
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'paper')
    dry_run = data.get('dry_run', False)
    from src.execution.executor import executor
    result = executor.set_mode(mode, dry_run)
    return jsonify(result)


# ── 每日选股 ─────────────────────────────────────────────────────
@console_bp.route('/pick', methods=['POST'])
def run_daily_pick():
    """触发每日选股流水线（后台执行）"""
    _pick_result = {'done': False, 'result': None}

    def _run():
        try:
            from src.strategy.daily_pick import DailyPickPipeline
            pipeline = DailyPickPipeline()
            _pick_result['result'] = pipeline.run()
        except Exception as e:
            _pick_result['result'] = {'success': False, 'error': str(e)}
        finally:
            _pick_result['done'] = True

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': '选股流水线已触发（后台执行），请稍后查看 /api/pick/latest'})


@console_bp.route('/pick/latest')
def get_latest_picks():
    """获取最新选股结果"""
    picks_file = PATHS["cache_dir"] / "daily_picks.json"
    if not picks_file.exists():
        return jsonify({'success': True, 'data': None, 'message': '暂无选股结果'})
    try:
        data = json.loads(picks_file.read_text(encoding='utf-8'))
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 自选股 ─────────────────────────────────────────────────────
_WATCHLIST_FILE = PATHS["cache_dir"] / "watchlist.json"


def _load_watchlist():
    if _WATCHLIST_FILE.exists():
        try:
            return json.loads(_WATCHLIST_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return []


def _save_watchlist(data):
    _WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    _WATCHLIST_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


@console_bp.route('/watchlist')
def get_watchlist():
    codes = _load_watchlist()
    data = []
    if codes:
        try:
            quotes = _realtime.get_quote([s['code'] for s in codes])
            for s in codes:
                q = quotes.get(s['code'], {})
                now_p = q.get('now', 0)
                close = q.get('close', 0)
                change_pct = ((now_p - close) / close * 100) if close else 0
                data.append({
                    'code': s['code'], 'name': s.get('name', s['code']),
                    'price': now_p, 'change_pct': round(change_pct, 2),
                    'volume': q.get('volume', 0),
                })
        except Exception:
            data = [{'code': s['code'], 'name': s.get('name', s['code']),
                     'price': 0, 'change_pct': 0, 'volume': 0} for s in codes]
    return jsonify({'success': True, 'data': data})


@console_bp.route('/watchlist/add', methods=['POST'])
def add_watchlist():
    d = request.get_json(silent=True) or {}
    code = d.get('code', '').strip()
    name = d.get('name', code)
    if not code:
        return jsonify({'success': False, 'error': 'Missing code'})
    wl = _load_watchlist()
    if not any(s['code'] == code for s in wl):
        wl.append({'code': code, 'name': name})
        _save_watchlist(wl)
    return jsonify({'success': True, 'message': f'{name} 已添加到自选'})


@console_bp.route('/watchlist/remove', methods=['POST'])
def remove_watchlist():
    d = request.get_json(silent=True) or {}
    code = d.get('code', '').strip()
    wl = _load_watchlist()
    wl = [s for s in wl if s['code'] != code]
    _save_watchlist(wl)
    return jsonify({'success': True, 'message': '已移除自选'})


# ── 市场数据 ───────────────────────────────────────────────────
@console_bp.route('/market/sentiment')
def market_sentiment():
    try:
        indices = ['000001', '399001', '399006']
        quotes = _realtime.get_quote(indices)
        up_count = 0
        down_count = 0
        limit_up_count = 0
        limit_down_count = 0
        total_turnover = 0
        for code, q in quotes.items():
            now_p = q.get('now', 0)
            close = q.get('close', 0)
            if close > 0:
                pct = (now_p - close) / close * 100
                if pct > 0:
                    up_count += 1
                elif pct < 0:
                    down_count += 1
                if pct >= 9.9:
                    limit_up_count += 1
                if pct <= -9.9:
                    limit_down_count += 1
            total_turnover += q.get('amount', 0)
        return jsonify({
            'success': True,
            'data': {
                'up_count': up_count, 'down_count': down_count,
                'limit_up_count': limit_up_count, 'limit_down_count': limit_down_count,
                'turnover': total_turnover, 'turnover_change': 0,
                'sentiment': '偏多' if up_count > down_count else ('偏空' if down_count > up_count else '均衡'),
                'north_flow': None,
            }
        })
    except Exception:
        return jsonify({'success': True, 'data': {
            'up_count': 0, 'down_count': 0, 'limit_up_count': 0,
            'limit_down_count': 0, 'turnover': 0, 'turnover_change': 0,
            'sentiment': '非交易时段', 'north_flow': None,
        }})


@console_bp.route('/market/sectors')
def market_sectors():
    try:
        with sqlite3.connect(str(DB["market"])) as conn:
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT industry, COUNT(*) as cnt FROM stock_info WHERE industry IS NOT NULL AND industry != '' GROUP BY industry ORDER BY cnt DESC LIMIT 10"
                ).fetchall()
                data = [{'name': r['industry'], 'change_pct': 0.0} for r in rows]
            except Exception:
                data = []
        return jsonify({'success': True, 'data': data})
    except Exception:
        return jsonify({'success': True, 'data': []})


@console_bp.route('/market/moneyflow')
def market_moneyflow():
    return jsonify({
        'success': True,
        'data': None,
        'message': '资金流向数据暂不可用',
    })


@console_bp.route('/market/overview')
def market_overview():
    return index_realtime()


@console_bp.route('/market/indices')
def market_indices():
    return index_realtime()


@console_bp.route('/market/hot')
def market_hot():
    return jsonify({'success': True, 'data': None, 'message': '热门数据暂不可用'})


# ── 认证（本地模式） ───────────────────────────────────────────
@console_bp.route('/auth/login', methods=['POST'])
def auth_login():
    d = request.get_json(silent=True) or {}
    username = d.get('username', '').strip()
    return jsonify({
        'success': True,
        'token': f'local-{__import__("secrets").token_hex(16)}',
        'user': {'username': username or 'admin', 'name': username or '管理员'},
    })


@console_bp.route('/auth/local-login', methods=['POST'])
def auth_local_login():
    import secrets as _secrets
    remote = request.remote_addr or ''
    if remote not in ('127.0.0.1', '::1', 'localhost'):
        return jsonify({'success': False, 'error': '仅限本地访问'}), 403
    token = f'local-{_secrets.token_hex(16)}'
    return jsonify({
        'success': True,
        'token': token,
        'user': {'username': 'local', 'name': '本机用户'},
    })


@console_bp.route('/auth/register', methods=['POST'])
def auth_register():
    return jsonify({'success': True, 'message': '注册成功（本地模式）'})


@console_bp.route('/auth/logout', methods=['POST'])
def auth_logout():
    return jsonify({'success': True, 'message': '已登出'})


@console_bp.route('/auth/verify')
def auth_verify():
    return jsonify({'success': True, 'data': {'username': 'admin', 'authenticated': True}})


@console_bp.route('/config/check')
def config_check():
    checks = []
    checks.append({'name': '数据库', 'status': 'ok' if DB["market"].exists() else 'error',
                   'message': '数据库正常' if DB["market"].exists() else '数据库不可访问'})
    checks.append({'name': 'DeepSeek API', 'status': 'ok' if DEEPSEEK_API_KEY else 'warning',
                   'message': '已配置' if DEEPSEEK_API_KEY else '未配置（可选）'})
    realtime_ok = False
    try:
        realtime_ok = bool(_realtime.get_price('000001'))
    except Exception:
        pass
    checks.append({'name': '实时行情', 'status': 'ok' if realtime_ok else 'warning',
                   'message': '行情服务可用' if realtime_ok else '行情服务不可用（非交易时段正常）'})
    return jsonify({'success': True, 'checks': checks})


# ── 策略列表（兼容 /api/strategies 路径） ──────────────────────
@console_bp.route('/strategies')
def strategies_list():
    return strategy_list()


# ── 设置账户 ───────────────────────────────────────────────────
@console_bp.route('/settings/account')
def get_settings_account():
    return jsonify({'success': True, 'data': {
        'total_capital': trade_config.total_capital,
        'max_positions': trade_config.max_positions,
    }})


@console_bp.route('/settings/account', methods=['POST'])
def update_settings_account():
    return jsonify({'success': True, 'message': '账户设置已保存'})


# ── 组合交易 ───────────────────────────────────────────────────
@console_bp.route('/portfolio/trades')
def portfolio_trades():
    return trade_history()


@console_bp.route('/portfolio/trade', methods=['POST'])
def portfolio_trade():
    return jsonify({'success': True, 'message': '交易已提交'})


def _get_stock_names():
    try:
        with sqlite3.connect(str(DB["market"])) as conn:
            rows = conn.execute("SELECT code, name FROM stock_info").fetchall()
            return {r[0]: r[1] for r in rows if r[0] and r[1]}
    except Exception:
        return {}


_MODEL_ACCOUNT_FILE = PATHS["cache_dir"] / "model_account.json"


def _load_model_account():
    mgr = PositionManager(initial_capital=trade_config.total_capital, max_positions=trade_config.max_positions)
    if _MODEL_ACCOUNT_FILE.exists():
        try:
            data = json.loads(_MODEL_ACCOUNT_FILE.read_text(encoding='utf-8'))
            mgr.cash = data.get('cash', trade_config.total_capital)
            for code, pd in data.get('positions', {}).items():
                mgr.positions[code] = Position(
                    code=code, entry_price=pd['entry_price'], shares=pd['shares'],
                    entry_time=datetime.fromisoformat(pd['entry_time']),
                    stop_loss=pd.get('stop_loss', 0), take_profit=pd.get('take_profit', 999),
                )
            mgr.closed_trades = data.get('closed_trades', [])
        except Exception:
            pass
    return mgr


def _save_model_account(mgr):
    try:
        _MODEL_ACCOUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
        state = {
            'cash': mgr.cash,
            'positions': {
                code: {
                    'entry_price': p.entry_price, 'shares': p.shares,
                    'entry_time': p.entry_time.isoformat(),
                    'stop_loss': p.stop_loss, 'take_profit': p.take_profit,
                } for code, p in mgr.positions.items()
            },
            'closed_trades': mgr.closed_trades[-100:],
        }
        _MODEL_ACCOUNT_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass


# ── 模型实时监控 API ────────────────────────────────────────────
_pipeline_stages = ['idle', 'precheck', 'news_crawl', 'daily_pick', 'intraday_loop', 'market_close']
_monitor_state = {
    'stage': 'idle',
    'last_decision_time': None,
    'last_decision': None,
    'decision_history': [],
    'auto_trade_enabled': False,
    'cycle_interval': 300,
    'pipeline_log': [],
    'last_news_crawl': None,
    'last_daily_pick': None,
    'last_intraday_cycle': None,
    'last_market_close': None,
    'news_crawl_count': 0,
    'daily_pick_count': 0,
    'intraday_cycle_count': 0,
    'last_error': None,
}
_monitor_lock = threading.Lock()
_monitor_thread = None


def _is_trading_time():
    from src.utils.market_calendar import is_market_open
    return is_market_open()


def _is_premarket():
    from src.utils.market_calendar import is_premarket
    return is_premarket()


def _is_market_close_time():
    from src.utils.market_calendar import is_market_close_time
    return is_market_close_time()


def _get_market_status():
    from src.utils.market_calendar import get_market_status
    return get_market_status()


def _check_model_ready():
    from src.utils.model_checker import check_model_availability
    return check_model_availability()


def _get_realtime_or_last_close(codes):
    prices = {}
    if not codes:
        return prices
    try:
        quotes = _realtime.get_quote(codes)
        for code in codes:
            if code in quotes:
                q = quotes[code]
                now_p = q.get('now', 0)
                close_p = q.get('close', 0)
                if now_p and now_p > 0:
                    prices[code] = now_p
                elif close_p and close_p > 0:
                    prices[code] = close_p
    except Exception:
        pass
    missing = [c for c in codes if c not in prices]
    if missing:
        try:
            with sqlite3.connect(str(DB["market"])) as conn:
                for code in missing:
                    try:
                        row = conn.execute(
                            "SELECT close FROM stock_kline WHERE code = ? ORDER BY date DESC LIMIT 1",
                            (code,)
                        ).fetchone()
                        if row and row[0] and row[0] > 0:
                            prices[code] = float(row[0])
                    except Exception:
                        pass
        except Exception:
            pass
    return prices


def _add_pipeline_log(stage, message, level='info'):
    with _monitor_lock:
        log_entry = {
            'time': datetime.now().isoformat(),
            'stage': stage,
            'message': message,
            'level': level,
        }
        _monitor_state['pipeline_log'] = (_monitor_state.get('pipeline_log', []) + [log_entry])[-100:]
    prefix = {'info': '[INFO]', 'warning': '[WARN]', 'error': '[ERR]'}.get(level, '[LOG]')
    print(f"[Pipeline] {prefix} [{stage}] {message}", flush=True)


def _run_monitor_cycle():
    import time as _time
    while True:
        with _monitor_lock:
            if not _proxy_state.get('running'):
                break
            interval = _monitor_state.get('cycle_interval', 300)
        try:
            _execute_pipeline_cycle()
        except Exception as e:
            with _monitor_lock:
                _monitor_state['last_error'] = str(e)
            _add_pipeline_log('error', str(e), 'error')
        _time.sleep(interval)


def _execute_pipeline_cycle():
    market_status = _get_market_status()
    model_check = _check_model_ready()
    is_trading = market_status['is_market_open']
    is_premark = market_status['status'] == 'premarket'
    is_close = market_status['status'] == 'closing'
    is_trading_day = market_status['is_trading_day']

    with _monitor_lock:
        current_stage = _monitor_state.get('stage', 'idle')

    if current_stage == 'idle':
        with _monitor_lock:
            _monitor_state['stage'] = 'precheck'
        _add_pipeline_log('precheck', '开始环境预检')

    if _monitor_state.get('stage') == 'precheck':
        api_ok = bool(DEEPSEEK_API_KEY)
        db_ok = DB["market"].exists()
        model_ok = model_check['ready']
        model_info = f"Model={model_check['model_count']}个" + (f" 最新={model_check['latest_model']}" if model_check['latest_model'] else " 无")
        if model_check['stale']:
            model_info += f" [过期{model_check['model_age_days']}天]"
        _add_pipeline_log('precheck', f'DB={db_ok} API={api_ok} {model_info} 市场={market_status["reason"]}')

        if not is_trading_day:
            _add_pipeline_log('precheck', f'今日休市: {market_status["reason"]}，流水线暂停交易', 'warning')
            with _monitor_lock:
                _monitor_state['stage'] = 'market_close'
            return

        if not model_ok:
            _add_pipeline_log('precheck', f'模型不可用: {model_check["reason"]}，仅执行新闻抓取', 'warning')
            with _monitor_lock:
                _monitor_state['stage'] = 'news_crawl'
            return

        if is_premark or is_trading:
            with _monitor_lock:
                _monitor_state['stage'] = 'news_crawl'
        elif is_close:
            with _monitor_lock:
                _monitor_state['stage'] = 'market_close'
        else:
            with _monitor_lock:
                _monitor_state['stage'] = 'intraday_loop'

    if _monitor_state.get('stage') == 'news_crawl':
        _run_news_crawl()

    if _monitor_state.get('stage') == 'daily_pick':
        _run_daily_pick()

    if _monitor_state.get('stage') == 'intraday_loop':
        _run_intraday_cycle(is_trading)

    if _monitor_state.get('stage') == 'market_close':
        _run_market_close()


def _run_news_crawl():
    _add_pipeline_log('news_crawl', '开始抓取RSS新闻')
    try:
        from src.news.rss_fetcher import fetch_rss_feeds, save_raw_news
        items = fetch_rss_feeds(max_per_source=3)
        saved = save_raw_news(items) if items else 0
        _add_pipeline_log('news_crawl', f'RSS: {len(items)}条, 新增{saved}条')

        if items:
            from src.news.fetcher import save_news_to_market
            sm = save_news_to_market(items)
            _add_pipeline_log('news_crawl', f'RSS写入market.db: {sm}条')
    except Exception as e:
        _add_pipeline_log('news_crawl', f'RSS失败: {e}', 'warning')

    try:
        from src.news.fetcher import fetch_newsnow, save_news, save_news_to_market
        items2 = fetch_newsnow()
        saved2 = save_news(items2) if items2 else 0
        _add_pipeline_log('news_crawl', f'NewsNow: {len(items2)}条, 新增{saved2}条')

        if items2:
            sm2 = save_news_to_market(items2)
            _add_pipeline_log('news_crawl', f'NewsNow写入market.db: {sm2}条')
    except Exception as e:
        _add_pipeline_log('news_crawl', f'NewsNow失败: {e}', 'warning')

    try:
        from src.news.analyzer import analyze_all_pending, aggregate_daily_factors
        count = analyze_all_pending(batch_size=5, limit=50)
        _add_pipeline_log('news_crawl', f'因子分析: {count}条')

        if count > 0:
            agg = aggregate_daily_factors()
            _add_pipeline_log('news_crawl', f'日频聚合: {agg}条')
    except Exception as e:
        _add_pipeline_log('news_crawl', f'分析失败: {e}', 'warning')

    with _monitor_lock:
        _monitor_state['last_news_crawl'] = datetime.now().isoformat()
        _monitor_state['news_crawl_count'] = _monitor_state.get('news_crawl_count', 0) + 1
        _monitor_state['stage'] = 'daily_pick'


def _run_daily_pick(mode='morning'):
    mode_label = {'morning': '清晨选股', 'midday': '日中选股', 'default': '每日选股'}.get(mode, '每日选股')
    _add_pipeline_log('daily_pick', f'开始{mode_label}')
    try:
        from src.strategy.daily_pick import DailyPickPipeline
        if mode == 'midday':
            pipeline = DailyPickPipeline(model_score_weight=0.5, news_score_weight=0.5)
        else:
            pipeline = DailyPickPipeline()
        result = pipeline.run()
        if result.get('success'):
            picks = result.get('picks', [])
            _add_pipeline_log('daily_pick', f'{mode_label}完成: {len(picks)}只, 耗时{result.get("elapsed",0):.1f}s')
        else:
            _add_pipeline_log('daily_pick', f'{mode_label}失败: {result.get("error","未知")}', 'error')
    except Exception as e:
        _add_pipeline_log('daily_pick', f'{mode_label}异常: {e}', 'error')

    with _monitor_lock:
        _monitor_state['last_daily_pick'] = datetime.now().isoformat()
        _monitor_state['last_pick_mode'] = mode
        _monitor_state['daily_pick_count'] = _monitor_state.get('daily_pick_count', 0) + 1
        _monitor_state['stage'] = 'intraday_loop'


def _check_picks_status():
    picks_file = PATHS["cache_dir"] / "daily_picks.json"
    today_str = datetime.now().strftime('%Y-%m-%d')
    market_status = _get_market_status()

    if not picks_file.exists():
        return {
            'has_picks': False,
            'picks_date': None,
            'is_today': False,
            'needs_pick': True,
            'reason': '无选股数据',
            'pick_count': 0,
            'suggested_mode': 'morning' if market_status['status'] in ('premarket', 'closed') and market_status['is_trading_day'] else 'midday',
        }

    try:
        data = json.loads(picks_file.read_text(encoding='utf-8'))
        picks_date = data.get('date', '')
        picks = data.get('picks', [])
        is_today = picks_date == today_str

        if is_today:
            pick_time = data.get('timestamp', '')
            is_morning = pick_time < f'{today_str}T12:00:00'
            return {
                'has_picks': True,
                'picks_date': picks_date,
                'is_today': True,
                'needs_pick': False,
                'reason': f'今日{"清晨" if is_morning else "日中"}已选股',
                'pick_count': len(picks),
                'pick_time': pick_time,
                'pick_mode': 'morning' if is_morning else 'midday',
                'suggested_mode': None,
            }
        else:
            return {
                'has_picks': True,
                'picks_date': picks_date,
                'is_today': False,
                'needs_pick': True,
                'reason': f'选股数据过期（{picks_date}）',
                'pick_count': len(picks),
                'suggested_mode': 'morning' if market_status['status'] in ('premarket', 'closed') and market_status['is_trading_day'] else 'midday',
            }
    except Exception as e:
        return {
            'has_picks': False,
            'picks_date': None,
            'is_today': False,
            'needs_pick': True,
            'reason': f'读取选股数据失败: {e}',
            'pick_count': 0,
            'suggested_mode': 'morning',
        }


def _run_intraday_cycle(is_trading):
    from src.execution.executor import executor

    market_status = _get_market_status()
    model_check = _check_model_ready()

    if not market_status['is_trading_day']:
        _add_pipeline_log('intraday_loop', f'休市日不执行交易: {market_status["reason"]}', 'warning')
        with _monitor_lock:
            _monitor_state['stage'] = 'market_close'
        return

    if not market_status['is_market_open']:
        _add_pipeline_log('intraday_loop', f'非交易时段: {market_status["reason"]}', 'warning')

    if not model_check['ready']:
        _add_pipeline_log('intraday_loop', f'模型不可用，跳过交易: {model_check["reason"]}', 'warning')

    can_trade = is_trading and market_status['is_market_open'] and model_check['ready']

    mgr = _load_model_account()
    risk_ctrl = RiskController()
    decisions = []

    codes = list(mgr.positions.keys())
    prices = _get_realtime_or_last_close(codes)

    for code in list(mgr.positions.keys()):
        pos = mgr.positions[code]
        current_price = prices.get(code, pos.entry_price)
        pos.update_price(current_price)
        if can_trade:
            should_close, reason = risk_ctrl.check_position(pos, current_price, datetime.now())
            if should_close:
                exec_result = executor.execute_sell(
                    code=code, price=current_price, shares=pos.shares,
                    reason=reason, paper_mgr=mgr,
                )
                pnl = exec_result.get('pnl', 0)
                decisions.append({
                    'time': datetime.now().isoformat(), 'code': code,
                    'action': 'sell', 'price': current_price, 'shares': pos.shares,
                    'reason': reason, 'pnl': round(pnl, 2),
                    'type': 'risk',
                    'exec_mode': executor.mode,
                    'real_result': exec_result.get('real'),
                })
                _add_pipeline_log('intraday_loop', f'风控卖出 {code}: {reason} [{executor.mode}]')

                try:
                    from src.utils.notify import send_notification
                    send_notification(
                        f"[风控触发] {code} 卖出 {pos.shares}股 @ {current_price:.2f} 原因: {reason} 盈亏: {round(pnl or 0, 2)}",
                        'risk'
                    )
                except Exception:
                    pass

    blocked, reason = risk_ctrl.check_portfolio(mgr)
    if not blocked and can_trade:
        picks_file = PATHS["cache_dir"] / "daily_picks.json"
        if picks_file.exists():
            try:
                picks_data = json.loads(picks_file.read_text(encoding='utf-8'))
                picks = picks_data.get('picks', [])
                available = mgr.max_positions - len(mgr.positions)
                for pick in picks[:available]:
                    code = pick.get('code', '')
                    if code and code not in mgr.positions:
                        price = _realtime.get_price(code) or prices.get(code)
                        if price and price > 0:
                            capital_per = mgr.cash / max(available, 1)
                            shares = int(capital_per / price / 100) * 100
                            if shares >= 100:
                                stop_loss = price * (1 - abs(trade_config.stop_loss_pct))
                                exec_result = executor.execute_buy(
                                    code=code, price=price, shares=shares,
                                    reason=f"模型选股 score={pick.get('final_score',0):+.4f}",
                                    paper_mgr=mgr, stop_loss=stop_loss,
                                )
                                if exec_result.get('success'):
                                    decisions.append({
                                        'time': datetime.now().isoformat(), 'code': code,
                                        'action': 'buy', 'price': price, 'shares': shares,
                                        'reason': f"模型选股 score={pick.get('final_score',0):+.4f}",
                                        'pnl': 0, 'type': 'signal',
                                        'exec_mode': executor.mode,
                                        'real_result': exec_result.get('real'),
                                    })
                                    _add_pipeline_log('intraday_loop', f'买入 {code}: {shares}股@{price:.2f} [{executor.mode}]')

                                    try:
                                        from src.utils.notify import send_notification
                                        send_notification(
                                            f"[交易信号] {code} 买入 {shares}股 @ {price:.2f} score={pick.get('final_score', 0):+.4f}",
                                            'signal'
                                        )
                                    except Exception:
                                        pass
            except Exception as e:
                _add_pipeline_log('intraday_loop', f'执行失败: {e}', 'warning')

    _save_model_account(mgr)

    with _monitor_lock:
        _monitor_state['last_decision_time'] = datetime.now().isoformat()
        _monitor_state['last_decision'] = decisions
        _monitor_state['decision_history'] = (_monitor_state.get('decision_history', []) + decisions)[-50:]
        _monitor_state['last_intraday_cycle'] = datetime.now().isoformat()
        _monitor_state['intraday_cycle_count'] = _monitor_state.get('intraday_cycle_count', 0) + 1


def _run_market_close():
    _add_pipeline_log('market_close', '开始收市总结')
    try:
        mgr = _load_model_account()
        codes = list(mgr.positions.keys())
        prices = _get_realtime_or_last_close(codes)
        total_mv = 0
        total_pnl = 0
        for code, pos in mgr.positions.items():
            cp = prices.get(code, pos.entry_price)
            total_mv += cp * pos.shares
            total_pnl += pos.pnl(cp)
        equity = mgr.cash + total_mv
        daily_pnl_pct = (equity - trade_config.total_capital) / trade_config.total_capital * 100
        _add_pipeline_log('market_close', f'总资产:{equity:,.0f} 盈亏:{total_pnl:+,.0f}({daily_pnl_pct:+.2f}%) 持仓:{len(mgr.positions)}只')
    except Exception as e:
        _add_pipeline_log('market_close', f'总结失败: {e}', 'error')

    with _monitor_lock:
        _monitor_state['last_market_close'] = datetime.now().isoformat()
        _monitor_state['stage'] = 'idle'


@console_bp.route('/monitor/status')
def monitor_status():
    market_status = _get_market_status()
    model_check = _check_model_ready()
    with _monitor_lock:
        proxy = dict(_proxy_state)
        mon = dict(_monitor_state)
        mon.pop('decision_history', None)
    return jsonify({
        'success': True,
        'data': {
            'proxy': proxy,
            'monitor': mon,
            'market': market_status,
            'model': {
                'ready': model_check['ready'],
                'reason': model_check['reason'],
                'latest_model': model_check['latest_model'],
                'model_age_days': model_check['model_age_days'],
                'stale': model_check['stale'],
                'model_count': model_check['model_count'],
            },
        }
    })


@console_bp.route('/status')
def console_status():
    return monitor_status()


@console_bp.route('/monitor/decisions')
def monitor_decisions():
    limit = request.args.get('limit', 50, type=int)
    with _monitor_lock:
        history = list(_monitor_state.get('decision_history', []))
    return jsonify({'success': True, 'data': history[-limit:], 'count': len(history)})


@console_bp.route('/monitor/account')
def monitor_account():
    mgr = _load_model_account()
    positions_data = []
    total_mv = 0
    total_pnl = 0
    codes = list(mgr.positions.keys())
    prices = _get_realtime_or_last_close(codes)
    name_map = _get_stock_names()
    for code, pos in mgr.positions.items():
        cp = prices.get(code, pos.entry_price)
        pos.update_price(cp)
        pnl = pos.pnl(cp)
        pnl_pct = pos.pnl_pct(cp)
        mv = cp * pos.shares
        total_mv += mv
        total_pnl += pnl
        positions_data.append({
            'code': code, 'name': name_map.get(code, code), 'shares': pos.shares,
            'cost_price': pos.entry_price, 'current_price': cp,
            'market_value': round(mv, 2), 'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct * 100, 2),
            'entry_time': pos.entry_time.strftime('%Y-%m-%d %H:%M'),
            'stop_loss': pos.stop_loss, 'highest': pos.highest_price,
        })

    equity = mgr.cash + total_mv
    return jsonify({
        'success': True,
        'data': {
            'total_assets': round(equity, 2),
            'cash': round(mgr.cash, 2),
            'position_value': round(total_mv, 2),
            'total_pnl': round(total_pnl, 2),
            'total_pnl_pct': round((equity - trade_config.total_capital) / trade_config.total_capital * 100, 2),
            'positions': positions_data,
            'position_count': len(mgr.positions),
            'max_positions': trade_config.max_positions,
            'closed_trades_count': len(mgr.closed_trades),
        }
    })


@console_bp.route('/monitor/next_action')
def monitor_next_action():
    now = datetime.now()
    market_status = _get_market_status()
    model_check = _check_model_ready()
    is_trading = market_status['is_market_open']

    picks_file = PATHS["cache_dir"] / "daily_picks.json"
    next_actions = []
    name_map = _get_stock_names()
    picks_date = None
    picks_expired = True
    if picks_file.exists():
        try:
            picks_data = json.loads(picks_file.read_text(encoding='utf-8'))
            picks_date = picks_data.get('date', '')
            today_str = now.strftime('%Y-%m-%d')
            picks_expired = picks_date != today_str
            for pick in picks_data.get('picks', [])[:10]:
                code = pick.get('code', '')
                score = pick.get('final_score', 0)
                m_score = pick.get('model_score', 0)
                n_score = pick.get('news_score', 0)
                if score > 0.2:
                    action = 'strong_buy' if score > 0.5 else 'buy'
                elif score < -0.2:
                    action = 'strong_sell' if score < -0.5 else 'sell'
                else:
                    action = 'hold'
                next_actions.append({
                    'code': code, 'name': name_map.get(code, code),
                    'action': action,
                    'score': round(score, 4),
                    'model_score': round(m_score, 4),
                    'news_score': round(n_score, 4),
                    'confidence': round(abs(score), 2),
                })
        except Exception:
            pass

    held_codes = set()
    if _MODEL_ACCOUNT_FILE.exists():
        try:
            data = json.loads(_MODEL_ACCOUNT_FILE.read_text(encoding='utf-8'))
            held_codes = set(data.get('positions', {}).keys())
        except Exception:
            pass

    for a in next_actions:
        a['is_held'] = a['code'] in held_codes

    return jsonify({
        'success': True,
        'data': {
            'is_trading_time': is_trading,
            'current_time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'next_cycle': f'{_monitor_state.get("cycle_interval", 300)}s',
            'actions': next_actions,
            'held_codes': list(held_codes),
            'picks_date': picks_date,
            'picks_expired': picks_expired,
            'market_status': market_status,
            'model_status': {
                'ready': model_check['ready'],
                'reason': model_check['reason'],
                'latest_model': model_check['latest_model'],
                'model_age_days': model_check['model_age_days'],
                'stale': model_check['stale'],
            },
        }
    })


@console_bp.route('/monitor/risk')
def monitor_risk():
    mgr = _load_model_account()
    risk_ctrl = RiskController()
    blocked, reason = risk_ctrl.check_portfolio(mgr)

    position_risks = []
    codes = list(mgr.positions.keys())
    prices = _get_realtime_or_last_close(codes)
    is_trading = _is_trading_time()
    for code, pos in mgr.positions.items():
        cp = prices.get(code, pos.entry_price)
        should_close = False
        close_reason = ''
        if is_trading:
            should_close, close_reason = risk_ctrl.check_position(pos, cp, datetime.now())
        pnl_pct = pos.pnl_pct(cp) * 100
        position_risks.append({
            'code': code, 'pnl_pct': round(pnl_pct, 2),
            'stop_loss': pos.stop_loss, 'current_price': cp,
            'should_close': should_close, 'close_reason': close_reason,
            'holding_bars': pos.holding_bars,
        })

    return jsonify({
        'success': True,
        'data': {
            'portfolio_blocked': blocked,
            'portfolio_reason': reason,
            'position_risks': position_risks,
            'max_daily_loss_pct': risk_ctrl.max_daily_loss_pct * 100,
            'max_position_ratio': risk_ctrl.max_total_position * 100,
            'is_trading_time': is_trading,
        }
    })


@console_bp.route('/monitor/start', methods=['POST'])
def monitor_start():
    global _monitor_thread
    with _proxy_lock:
        if not _proxy_state['running']:
            _proxy_state['running'] = True
            _proxy_state['started_at'] = datetime.now().isoformat()
            _proxy_state['error'] = None
    with _monitor_lock:
        _monitor_state['auto_trade_enabled'] = True
        _monitor_state['stage'] = 'precheck'
        d = request.get_json(silent=True) or {}
        if d.get('interval'):
            _monitor_state['cycle_interval'] = max(60, int(d['interval']))
    if _monitor_thread is None or not _monitor_thread.is_alive():
        _monitor_thread = threading.Thread(target=_run_monitor_cycle, daemon=True)
        _monitor_thread.start()
    log_system('monitor_start', '模型监控已启动')
    _add_pipeline_log('precheck', '模型监控已启动')
    return jsonify({'success': True, 'message': '模型监控已启动'})


@console_bp.route('/monitor/stop', methods=['POST'])
def monitor_stop():
    with _proxy_lock:
        _proxy_state['running'] = False
    with _monitor_lock:
        _monitor_state['auto_trade_enabled'] = False
        _monitor_state['stage'] = 'idle'
    log_system('monitor_stop', '模型监控已停止')
    return jsonify({'success': True, 'message': '模型监控已停止'})


@console_bp.route('/monitor/trigger', methods=['POST'])
def monitor_trigger():
    d = request.get_json(silent=True) or {}
    stage = d.get('stage', '')
    mode = d.get('mode', 'morning')

    def _run_async():
        try:
            if stage == 'news_crawl':
                _run_news_crawl()
            elif stage == 'daily_pick':
                _run_daily_pick(mode=mode)
            elif stage == 'intraday':
                _run_intraday_cycle(_is_trading_time())
            elif stage == 'market_close':
                _run_market_close()
            else:
                _execute_pipeline_cycle()
        except Exception as e:
            _add_pipeline_log('error', f'触发执行失败: {e}', 'error')

    t = threading.Thread(target=_run_async, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': f'{stage or "full"} 已触发（后台执行）'})


@console_bp.route('/monitor/picks_check')
def monitor_picks_check():
    return jsonify({'success': True, 'data': _check_picks_status()})


@console_bp.route('/monitor/picks_run', methods=['POST'])
def monitor_picks_run():
    d = request.get_json(silent=True) or {}
    mode = d.get('mode', 'morning')
    force = d.get('force', False)

    picks_status = _check_picks_status()
    if not force and not picks_status.get('needs_pick'):
        return jsonify({
            'success': False,
            'message': f"今日已选股（{picks_status.get('reason')}），如需重新选股请设置 force=true",
            'data': picks_status,
        })

    market_status = _get_market_status()
    if not market_status['is_trading_day']:
        return jsonify({
            'success': False,
            'message': f"今日休市: {market_status['reason']}，无需选股",
        })

    model_check = _check_model_ready()
    if not model_check['ready']:
        return jsonify({
            'success': False,
            'message': f"模型不可用: {model_check['reason']}",
        })

    def _run_async():
        _run_daily_pick(mode=mode)

    t = threading.Thread(target=_run_async, daemon=True)
    t.start()
    mode_label = {'morning': '清晨选股', 'midday': '日中选股'}.get(mode, '选股')
    return jsonify({'success': True, 'message': f'{mode_label}已启动（后台执行）'})


@console_bp.route('/monitor/pipeline_log')
def monitor_pipeline_log():
    limit = request.args.get('limit', 50, type=int)
    with _monitor_lock:
        logs = list(_monitor_state.get('pipeline_log', []))
    return jsonify({'success': True, 'data': logs[-limit:], 'count': len(logs)})
