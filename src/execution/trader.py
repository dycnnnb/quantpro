"""
真实交易执行器
基于 easytrader 封装，支持同花顺客户端 GUI 自动化交易
"""

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

_EASYTRADER_PATH = _PROJECT_ROOT / "交易" / "easytrader-master"
if _EASYTRADER_PATH.exists() and str(_EASYTRADER_PATH) not in sys.path:
    sys.path.insert(0, str(_EASYTRADER_PATH))

from config.settings import PATHS
from src.utils.operation_logger import log_trade, log_system

_STATE_FILE = PATHS["cache_dir"] / "trader_state.json"


class THSTrader:
    """同花顺交易执行器"""

    def __init__(self):
        self._user = None
        self._connected = False
        self._lock = threading.Lock()
        self._load_state()

    def _load_state(self):
        if _STATE_FILE.exists():
            try:
                state = json.loads(_STATE_FILE.read_text(encoding='utf-8'))
                self._connected = state.get('connected', False)
            except Exception:
                pass

    def _save_state(self):
        try:
            PATHS["cache_dir"].mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(json.dumps({
                'connected': self._connected,
                'last_update': datetime.now().isoformat(),
            }, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass

    def connect(self, user: str = '', password: str = '', exe_path: str = '',
                broker: str = 'universal_client') -> dict:
        """连接同花顺客户端

        Args:
            user: 账号
            password: 密码
            exe_path: 同花顺下单程序路径 (如 C:\\ths\\xiadan.exe)
            broker: 券商类型 (universal_client/yh_client/ht_client 等)
        """
        with self._lock:
            try:
                import easytrader
                self._user = easytrader.use(broker)

                if not exe_path:
                    return {'success': False, 'error': '需要提供 exe_path'}

                if user and password:
                    self._user.prepare(user=user, password=password, exe_path=exe_path)
                else:
                    self._user.connect(exe_path=exe_path)

                login_ok = self._wait_for_login(timeout=15)
                if not login_ok:
                    self._connected = False
                    return {
                        'success': False,
                        'error': '同花顺未登录 — 请先在客户端中手动登录模拟交易账号，然后重新连接',
                        'hint': '登录对话框可能在前台，请切换到同花顺窗口完成登录',
                    }

                self._connected = True
                self._save_state()
                log_system('trader_connect', f'broker={broker}')
                return {'success': True, 'message': f'已连接 {broker}'}
            except Exception as e:
                self._connected = False
                err_str = str(e)
                if 'SysTreeView32' in err_str or 'GetLeftMenuHandle' in err_str:
                    return {
                        'success': False,
                        'error': '同花顺未登录或登录未完成 — 请先手动登录模拟交易账号',
                        'hint': 'easytrader 无法获取交易菜单，通常是因为同花顺还停留在登录界面',
                    }
                return {'success': False, 'error': err_str}

    def _wait_for_login(self, timeout: int = 15) -> bool:
        """等待同花顺登录完成（主交易窗口出现 SysTreeView32 菜单）"""
        import pywinauto
        try:
            app = self._user._app
        except Exception:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                for w in app.windows():
                    try:
                        title = w.window_text()
                        if '网上股票交易' not in title:
                            continue
                        children = w.descendants()
                        tree_views = [c for c in children if c.class_name() == "SysTreeView32"]
                        if tree_views:
                            return True
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(1)
        return False

    def disconnect(self):
        with self._lock:
            if self._user:
                try:
                    self._user.exit()
                except Exception:
                    pass
                self._user = None
            self._connected = False
            self._save_state()
            log_system('trader_disconnect', '已断开')

    def is_connected(self) -> bool:
        return self._connected and self._user is not None

    def _check(self) -> bool:
        return self._connected and self._user is not None

    def _dismiss_captcha(self):
        """关闭同花顺验证码弹窗（如果存在）"""
        try:
            app = self._user._app
            for w in app.windows(class_name="#32770", visible_only=True):
                try:
                    title = w.window_text()
                    if '验证码' in title or '安全验证' in title:
                        w.close()
                        log_system('captcha_dismiss', f'已关闭验证码弹窗: {title}')
                except Exception:
                    pass
        except Exception:
            pass

    def get_balance(self) -> dict:
        """查询账户资金"""
        if not self._check():
            return {'success': False, 'error': '未连接交易客户端'}
        try:
            self._dismiss_captcha()
            balance = self._user.balance
            if isinstance(balance, list):
                balance = balance[0] if balance else {}
            return {'success': True, 'data': balance}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_positions(self) -> dict:
        """查询持仓"""
        if not self._check():
            return {'success': False, 'error': '未连接交易客户端'}
        try:
            self._dismiss_captcha()
            positions = self._user.position
            return {'success': True, 'data': positions}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_today_trades(self) -> dict:
        """查询今日成交"""
        if not self._check():
            return {'success': False, 'error': '未连接交易客户端'}
        try:
            trades = self._user.today_trades
            return {'success': True, 'data': trades}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_today_entrusts(self) -> dict:
        """查询今日委托"""
        if not self._check():
            return {'success': False, 'error': '未连接交易客户端'}
        try:
            entrusts = self._user.today_entrusts
            return {'success': True, 'data': entrusts}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def buy(self, security: str, price: float, amount: int) -> dict:
        """限价买入

        Args:
            security: 6 位股票代码
            price: 买入价格
            amount: 买入数量（手数 * 100）
        """
        if not self._check():
            return {'success': False, 'error': '未连接交易客户端'}
        try:
            result = self._user.buy(security=security, price=price, amount=amount)
            log_trade('buy', security, price=price, quantity=amount, result='success',
                      details=f'entrust_no={result.get("entrust_no", "")}')
            return {'success': True, 'data': result}
        except Exception as e:
            log_trade('buy', security, price=price, quantity=amount, result='failed',
                      details=str(e))
            return {'success': False, 'error': str(e)}

    def sell(self, security: str, price: float, amount: int) -> dict:
        """限价卖出"""
        if not self._check():
            return {'success': False, 'error': '未连接交易客户端'}
        try:
            result = self._user.sell(security=security, price=price, amount=amount)
            log_trade('sell', security, price=price, quantity=amount, result='success',
                      details=f'entrust_no={result.get("entrust_no", "")}')
            return {'success': True, 'data': result}
        except Exception as e:
            log_trade('sell', security, price=price, quantity=amount, result='failed',
                      details=str(e))
            return {'success': False, 'error': str(e)}

    def market_buy(self, security: str, amount: int) -> dict:
        """市价买入"""
        if not self._check():
            return {'success': False, 'error': '未连接交易客户端'}
        try:
            result = self._user.market_buy(security=security, amount=amount)
            log_trade('market_buy', security, quantity=amount, result='success')
            return {'success': True, 'data': result}
        except Exception as e:
            log_trade('market_buy', security, quantity=amount, result='failed', details=str(e))
            return {'success': False, 'error': str(e)}

    def market_sell(self, security: str, amount: int) -> dict:
        """市价卖出"""
        if not self._check():
            return {'success': False, 'error': '未连接交易客户端'}
        try:
            result = self._user.market_sell(security=security, amount=amount)
            log_trade('market_sell', security, quantity=amount, result='success')
            return {'success': True, 'data': result}
        except Exception as e:
            log_trade('market_sell', security, quantity=amount, result='failed', details=str(e))
            return {'success': False, 'error': str(e)}

    def cancel_entrust(self, entrust_no: str) -> dict:
        """撤单"""
        if not self._check():
            return {'success': False, 'error': '未连接交易客户端'}
        try:
            result = self._user.cancel_entrust(entrust_no=entrust_no)
            log_trade('cancel', entrust_no, result='success')
            return {'success': True, 'data': result}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def cancel_all(self) -> dict:
        """撤销全部委托"""
        if not self._check():
            return {'success': False, 'error': '未连接交易客户端'}
        try:
            result = self._user.cancel_all_entrusts()
            log_trade('cancel_all', '', result='success')
            return {'success': True, 'data': result}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def auto_ipo(self) -> dict:
        """自动申购新股"""
        if not self._check():
            return {'success': False, 'error': '未连接交易客户端'}
        try:
            result = self._user.auto_ipo()
            log_trade('auto_ipo', '', result='success')
            return {'success': True, 'data': result}
        except Exception as e:
            return {'success': False, 'error': str(e)}


class TradeBridge:
    """交易桥接器：将模型决策自动执行到同花顺客户端"""

    def __init__(self, trader_instance: THSTrader = None):
        self._trader = trader_instance or trader
        self._dry_run = True
        self._last_executed = []

    @property
    def is_live(self) -> bool:
        return self._trader.is_connected() and not self._dry_run

    def set_mode(self, dry_run: bool = True):
        self._dry_run = dry_run

    def execute_decision(self, decision: dict) -> dict:
        if self._dry_run or not self._trader.is_connected():
            return {'success': True, 'mode': 'dry_run', 'decision': decision}

        action = decision.get('action', '')
        code = str(decision.get('code', '')).strip()
        price = float(decision.get('price', 0))
        shares = int(decision.get('shares', 0))

        if not code or price <= 0 or shares <= 0:
            return {'success': False, 'error': f'invalid params: code={code} price={price} shares={shares}'}

        if len(code) == 6:
            pass
        elif code.startswith(('sh', 'sz', 'bj')):
            code = code[2:]
        else:
            return {'success': False, 'error': f'invalid code format: {code}'}

        try:
            if action == 'buy':
                result = self._trader.buy(security=code, price=price, amount=shares)
            elif action == 'sell':
                result = self._trader.sell(security=code, price=price, amount=shares)
            elif action == 'market_buy':
                result = self._trader.market_buy(security=code, amount=shares)
            elif action == 'market_sell':
                result = self._trader.market_sell(security=code, amount=shares)
            else:
                return {'success': False, 'error': f'unknown action: {action}'}

            self._last_executed.append({
                'time': datetime.now().isoformat(),
                'action': action, 'code': code,
                'price': price, 'shares': shares,
                'result': result,
            })

            return {'success': result.get('success', True), 'mode': 'live', 'result': result}

        except Exception as e:
            log_trade(action, code, price=price, quantity=shares, result='bridge_error', details=str(e))
            return {'success': False, 'error': str(e)}

    def execute_decisions(self, decisions: list) -> list:
        results = []
        for d in decisions:
            r = self.execute_decision(d)
            results.append(r)
            time.sleep(0.5)
        return results

    def get_execution_log(self, limit: int = 50) -> list:
        return self._last_executed[-limit:]


# 全局实例
trader = THSTrader()
bridge = TradeBridge(trader)
