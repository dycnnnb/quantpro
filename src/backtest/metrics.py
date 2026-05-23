"""
绩效指标计算
"""

import numpy as np
import pandas as pd


def calc_sharpe(returns: pd.Series, risk_free: float = 0.0, periods_per_year: int = 252) -> float:
    excess = returns - risk_free / periods_per_year
    return float(excess.mean() / (excess.std() + 1e-8) * np.sqrt(periods_per_year))


def calc_max_drawdown(equity: pd.Series) -> float:
    roll_max = equity.expanding().max()
    dd = (equity - roll_max) / roll_max
    return float(dd.min())


def calc_calmar(total_return: float, max_drawdown: float, years: float = 1.0) -> float:
    if max_drawdown == 0:
        return float('inf')
    return float(total_return / abs(max_drawdown) / years)


def calc_sortino(returns: pd.Series, periods_per_year: int = 252) -> float:
    downside = returns[returns < 0]
    if len(downside) == 0:
        return float('inf')
    downside_std = downside.std()
    return float(returns.mean() / (downside_std + 1e-8) * np.sqrt(periods_per_year))


def calc_win_rate(trades: pd.DataFrame) -> float:
    if 'net_pnl' not in trades.columns or len(trades) == 0:
        return 0.0
    return float((trades['net_pnl'] > 0).mean())


def calc_profit_factor(trades: pd.DataFrame) -> float:
    if 'net_pnl' not in trades.columns or len(trades) == 0:
        return 0.0
    wins = trades.loc[trades['net_pnl'] > 0, 'net_pnl'].sum()
    losses = trades.loc[trades['net_pnl'] < 0, 'net_pnl'].sum()
    if losses == 0:
        return float('inf')
    return float(abs(wins / losses))


def full_report(equity: pd.Series, trades: pd.DataFrame, initial_capital: float) -> dict:
    total_ret = equity.iloc[-1] / initial_capital - 1
    max_dd = calc_max_drawdown(equity)
    ret_s = equity.pct_change().dropna()

    return {
        'total_return': total_ret,
        'sharpe': calc_sharpe(ret_s),
        'sortino': calc_sortino(ret_s),
        'max_drawdown': max_dd,
        'calmar': calc_calmar(total_ret, max_dd),
        'win_rate': calc_win_rate(trades),
        'profit_factor': calc_profit_factor(trades),
        'total_trades': len(trades),
    }
