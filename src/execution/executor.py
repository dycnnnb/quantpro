"""
交易执行桥接层
策略决策 → 模拟盘(PositionManager) / 实盘(THSTrader)
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config.settings import PATHS
from src.utils.operation_logger import log_trade, log_system

_EXECUTOR_STATE_FILE = PATHS["cache_dir"] / "executor_state.json"
_lock = threading.Lock()


class TradeExecutor:
    """
    统一交易执行器，桥接策略决策与实际执行。

    mode:
      - 'paper':  模拟盘，仅更新 PositionManager
      - 'real':   实盘，通过 THSTrader 执行真实交易
      - 'both':   同时更新模拟盘和实盘
    """

    def __init__(self, mode: str = 'paper'):
        self.mode = mode
        self._real_trader = None
        self._dry_run = False
        self._load_state()

    def _load_state(self):
        if _EXECUTOR_STATE_FILE.exists():
            try:
                state = json.loads(_EXECUTOR_STATE_FILE.read_text(encoding='utf-8'))
                self.mode = state.get('mode', self.mode)
                self._dry_run = state.get('dry_run', False)
            except Exception:
                pass

    def _save_state(self):
        try:
            PATHS["cache_dir"].mkdir(parents=True, exist_ok=True)
            _EXECUTOR_STATE_FILE.write_text(json.dumps({
                'mode': self.mode,
                'dry_run': self._dry_run,
                'updated': datetime.now().isoformat(),
            }, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass

    def set_mode(self, mode: str, dry_run: bool = False) -> dict:
        if mode not in ('paper', 'real', 'both'):
            return {'success': False, 'error': f'无效模式: {mode}'}
        self.mode = mode
        self._dry_run = dry_run
        self._save_state()
        log_system('executor_mode', f'mode={mode} dry_run={dry_run}')
        return {'success': True, 'mode': mode, 'dry_run': dry_run}

    def get_mode(self) -> dict:
        return {
            'mode': self.mode,
            'dry_run': self._dry_run,
            'real_connected': self._check_real_connection(),
        }

    def _get_real_trader(self):
        if self._real_trader is None:
            from src.execution.trader import trader
            self._real_trader = trader
        return self._real_trader

    def _check_real_connection(self) -> bool:
        try:
            return self._get_real_trader().is_connected()
        except Exception:
            return False

    def execute_buy(
        self,
        code: str,
        price: float,
        shares: int,
        reason: str = '',
        paper_mgr=None,
        stop_loss: float = 0.0,
    ) -> dict:
        """
        执行买入决策。

        Args:
            code: 股票代码
            price: 买入价格
            shares: 买入数量
            reason: 决策原因
            paper_mgr: PositionManager 实例（模拟盘）
            stop_loss: 止损价

        Returns:
            {'success': bool, 'paper': dict, 'real': dict}
        """
        result = {'success': False, 'paper': None, 'real': None}

        if self.mode in ('paper', 'both') and paper_mgr is not None:
            try:
                pos = paper_mgr.open_position(code, price, shares, stop_loss=stop_loss)
                if pos:
                    result['paper'] = {
                        'success': True, 'code': code,
                        'price': price, 'shares': shares,
                    }
                    log_trade('paper_buy', code, price=price, quantity=shares, result='success', details=reason)
                else:
                    result['paper'] = {'success': False, 'code': code, 'reason': '开仓失败'}
            except Exception as e:
                result['paper'] = {'success': False, 'code': code, 'error': str(e)}

        if self.mode in ('real', 'both') and not self._dry_run:
            try:
                trader = self._get_real_trader()
                if trader.is_connected():
                    real_result = trader.buy(security=code, price=price, amount=shares)
                    result['real'] = real_result
                    if real_result.get('success'):
                        log_trade('real_buy', code, price=price, quantity=shares, result='success', details=reason)
                    else:
                        log_trade('real_buy', code, price=price, quantity=shares, result='failed',
                                  details=real_result.get('error', ''))
                else:
                    result['real'] = {'success': False, 'error': '实盘未连接'}
            except Exception as e:
                result['real'] = {'success': False, 'error': str(e)}
        elif self.mode in ('real', 'both') and self._dry_run:
            result['real'] = {'success': True, 'dry_run': True, 'code': code,
                              'price': price, 'shares': shares}
            log_trade('dry_run_buy', code, price=price, quantity=shares, result='dry_run', details=reason)

        result['success'] = (
            (result.get('paper', {}).get('success', False)) or
            (result.get('real', {}).get('success', False))
        )
        return result

    def execute_sell(
        self,
        code: str,
        price: float,
        shares: int,
        reason: str = '',
        paper_mgr=None,
    ) -> dict:
        """
        执行卖出决策。

        Returns:
            {'success': bool, 'paper': dict, 'real': dict, 'pnl': float}
        """
        result = {'success': False, 'paper': None, 'real': None, 'pnl': 0.0}

        if self.mode in ('paper', 'both') and paper_mgr is not None:
            try:
                pnl = paper_mgr.close_position(code, price, reason=reason)
                result['paper'] = {
                    'success': True, 'code': code,
                    'price': price, 'shares': shares,
                }
                result['pnl'] = pnl or 0.0
                log_trade('paper_sell', code, price=price, quantity=shares, result='success',
                          details=f'{reason} pnl={pnl:.2f}' if pnl else reason)
            except Exception as e:
                result['paper'] = {'success': False, 'code': code, 'error': str(e)}

        if self.mode in ('real', 'both') and not self._dry_run:
            try:
                trader = self._get_real_trader()
                if trader.is_connected():
                    real_result = trader.sell(security=code, price=price, amount=shares)
                    result['real'] = real_result
                    if real_result.get('success'):
                        log_trade('real_sell', code, price=price, quantity=shares, result='success', details=reason)
                    else:
                        log_trade('real_sell', code, price=price, quantity=shares, result='failed',
                                  details=real_result.get('error', ''))
                else:
                    result['real'] = {'success': False, 'error': '实盘未连接'}
            except Exception as e:
                result['real'] = {'success': False, 'error': str(e)}
        elif self.mode in ('real', 'both') and self._dry_run:
            result['real'] = {'success': True, 'dry_run': True, 'code': code,
                              'price': price, 'shares': shares}
            log_trade('dry_run_sell', code, price=price, quantity=shares, result='dry_run', details=reason)

        result['success'] = (
            (result.get('paper', {}).get('success', False)) or
            (result.get('real', {}).get('success', False))
        )
        return result


executor = TradeExecutor()
