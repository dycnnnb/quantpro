"""
回测引擎 — 单股票 + 截面选股
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass


@dataclass
class BacktestConfig:
    initial_capital: float = 100_000
    commission_rate: float = 0.0003
    slippage: float = 0.001
    stamp_duty: float = 0.001
    stop_loss: float = 0.03
    take_profit: float = 0.999
    max_hold_bars: int = 24
    min_confidence: float = 0.55
    top_k: int = 5
    capital_per_stock: float = 0.18


class SingleStockBacktest:
    """单股票回测"""

    def __init__(self, config: BacktestConfig = None):
        self.cfg = config or BacktestConfig()
        self.trades = []
        self.equity = []

    def run(self, price_df: pd.DataFrame, signals_df: pd.DataFrame) -> tuple:
        cfg = self.cfg
        cash = cfg.initial_capital
        pos = None

        price_df = price_df.copy()
        price_df['_d'] = price_df.index.date

        for i, (idx, row) in enumerate(price_df.iterrows()):
            if idx not in signals_df.index:
                continue

            sig = signals_df.loc[idx]
            price = row['close']

            self.equity.append({
                'time': idx,
                'equity': cash + (pos['shares'] * price if pos else 0),
            })

            if pos is not None:
                bars_held = i - pos['bar']
                pnl_pct = price / pos['entry'] - 1
                cross_day = row['_d'] != pos['date']

                reason = None
                if cross_day:
                    reason = "intraday_close"
                elif pnl_pct <= -cfg.stop_loss:
                    reason = f"stop_loss({pnl_pct*100:.1f}%)"
                elif bars_held >= cfg.max_hold_bars:
                    reason = f"timeout({bars_held}bars)"

                if reason:
                    cash, pos = self._close(pos, price, cash, reason, idx)

            if pos is None and sig.get('signal', 2) == 1:
                high_conf = sig.get('buy_prob', 0) >= cfg.min_confidence
                if high_conf:
                    entry = price * (1 + cfg.slippage)
                    shares = int(cash * 0.95 / entry / 100) * 100
                    if shares >= 100:
                        cost = max(shares * entry * cfg.commission_rate, 5)
                        cash -= shares * entry + cost
                        pos = {
                            'bar': i, 'time': idx, 'date': row['_d'],
                            'entry': entry, 'shares': shares, 'cost': cost,
                            'confidence': sig.get('buy_prob', 0),
                        }

        if pos is not None:
            cash, _ = self._close(pos, price_df.iloc[-1]['close'], cash, "end", price_df.index[-1])

        return self._report(cfg.initial_capital, price_df)

    def _close(self, pos, price, cash, reason, ts):
        sell = price * (1 - self.cfg.slippage)
        val = pos['shares'] * sell
        comm = max(val * self.cfg.commission_rate, 5)
        stamp = val * self.cfg.stamp_duty
        gross = (sell - pos['entry']) * pos['shares']
        net = gross - comm - stamp - pos['cost']
        ret = net / (pos['entry'] * pos['shares'])
        cash += val - comm - stamp

        self.trades.append({
            'entry_time': pos['time'], 'exit_time': ts,
            'entry': pos['entry'], 'exit': sell,
            'shares': pos['shares'], 'net_pnl': net,
            'return_pct': ret, 'reason': reason,
        })
        return cash, None

    def _report(self, initial, price_df):
        if not self.trades:
            return {}, pd.DataFrame(), pd.DataFrame()

        t = pd.DataFrame(self.trades)
        eq = pd.DataFrame(self.equity)
        eq_s = eq['equity']

        wins = t[t['net_pnl'] > 0]
        loses = t[t['net_pnl'] <= 0]
        total_ret = eq_s.iloc[-1] / initial - 1
        max_dd = ((eq_s - eq_s.expanding().max()) / eq_s.expanding().max()).min()
        ret_s = eq_s.pct_change().dropna()
        sharpe = ret_s.mean() / (ret_s.std() + 1e-8) * np.sqrt(252 * 48)
        hold_ret = price_df['close'].iloc[-1] / price_df['close'].iloc[0] - 1

        report = {
            'total_trades': len(t),
            'win_rate': len(wins) / len(t),
            'profit_factor': abs(wins['net_pnl'].sum() / loses['net_pnl'].sum()) if len(loses) > 0 else float('inf'),
            'total_return': total_ret, 'benchmark': hold_ret,
            'alpha': total_ret - hold_ret, 'max_drawdown': max_dd, 'sharpe': sharpe,
        }

        print(f"Trades: {report['total_trades']}, WinRate: {report['win_rate']*100:.1f}%, "
              f"Return: {report['total_return']*100:+.2f}%, Sharpe: {report['sharpe']:.2f}")

        return report, t, eq


class CrossSectionalBacktest:
    """截面选股回测"""

    def __init__(self, config: BacktestConfig = None):
        self.cfg = config or BacktestConfig()
        self.trades = []
        self.equity = []

    def run(self, multi_price_df: pd.DataFrame, scores_df: pd.DataFrame) -> tuple:
        cfg = self.cfg
        cash = cfg.initial_capital
        positions = {}

        datetimes = multi_price_df.index.get_level_values('datetime').unique().sort_values()
        prev_date = None

        for bar_idx, dt in enumerate(datetimes):
            cur_date = dt.date()

            try:
                cur_prices = multi_price_df.loc[dt, 'close']
                if isinstance(cur_prices, float):
                    continue
            except KeyError:
                continue

            total_val = cash + sum(
                positions[c]['shares'] * cur_prices.get(c, positions[c]['entry'])
                for c in positions
            )
            self.equity.append({'time': dt, 'equity': total_val})

            is_last_bar = self._is_last_bar(dt, datetimes)

            # Stop loss check
            for code in list(positions.keys()):
                price = cur_prices.get(code)
                if price is None:
                    continue
                pnl_p = price / positions[code]['entry'] - 1
                if pnl_p <= -cfg.stop_loss:
                    cash = self._close_pos(positions.pop(code), code, price, cash, dt, "stop_loss")

            # Intraday close
            if is_last_bar and positions:
                for code in list(positions.keys()):
                    price = cur_prices.get(code, positions[code]['entry'])
                    cash = self._close_pos(positions.pop(code), code, price, cash, dt, "intraday_close")

            if is_last_bar:
                prev_date = cur_date
                continue

            # Rebalance
            if bar_idx % cfg.max_hold_bars == 0:
                for code in list(positions.keys()):
                    price = cur_prices.get(code, positions[code]['entry'])
                    cash = self._close_pos(positions.pop(code), code, price, cash, dt, "rebalance")

                if dt in scores_df.index.get_level_values('datetime'):
                    try:
                        dt_scores = scores_df.loc[dt, 'buy_score']
                        if isinstance(dt_scores, pd.Series):
                            high_conf = dt_scores[dt_scores >= cfg.min_confidence]
                            top_codes = high_conf.nlargest(cfg.top_k).index.tolist()
                            for code in top_codes:
                                price = cur_prices.get(code)
                                if price is None or price <= 0:
                                    continue
                                entry = price * (1 + cfg.slippage)
                                trade_val = cash * cfg.capital_per_stock
                                shares = int(trade_val / entry / 100) * 100
                                if shares < 100:
                                    continue
                                cost = max(shares * entry * cfg.commission_rate, 5)
                                if cash < shares * entry + cost:
                                    continue
                                cash -= shares * entry + cost
                                positions[code] = {
                                    'entry': entry, 'shares': shares,
                                    'cost': cost, 'time': dt, 'date': cur_date,
                                    'score': float(dt_scores.get(code, 0)),
                                }
                    except (KeyError, TypeError):
                        pass

            prev_date = cur_date

        # Close remaining
        if positions:
            last_dt = datetimes[-1]
            try:
                last_prices = multi_price_df.loc[last_dt, 'close']
            except KeyError:
                last_prices = pd.Series()
            if not isinstance(last_prices, pd.Series):
                last_prices = pd.Series()
            for code, pos in list(positions.items()):
                price = last_prices.get(code, pos['entry'])
                cash = self._close_pos(pos, code, price, cash, last_dt, "end")

        return self._report(cfg.initial_capital)

    def _is_last_bar(self, dt, datetimes):
        future = datetimes[datetimes > dt]
        return len(future) == 0 or future[0].date() != dt.date()

    def _close_pos(self, pos, code, price, cash, ts, reason):
        cfg = self.cfg
        sell = price * (1 - cfg.slippage)
        val = pos['shares'] * sell
        comm = max(val * cfg.commission_rate, 5)
        stamp = val * cfg.stamp_duty
        gross = (sell - pos['entry']) * pos['shares']
        net = gross - comm - stamp - pos['cost']
        ret = net / (pos['entry'] * pos['shares'])
        cash += val - comm - stamp

        self.trades.append({
            'code': code, 'entry': pos['time'], 'exit': ts,
            'net_pnl': net, 'ret': ret, 'reason': reason,
        })
        return cash

    def _report(self, initial):
        if not self.trades:
            return {}, pd.DataFrame(), pd.DataFrame()

        t = pd.DataFrame(self.trades)
        eq = pd.DataFrame(self.equity)
        eq_s = eq['equity']

        wins = t[t['net_pnl'] > 0]
        loses = t[t['net_pnl'] <= 0]
        pf = abs(wins['net_pnl'].sum() / loses['net_pnl'].sum()) if len(loses) > 0 else 999
        max_dd = ((eq_s - eq_s.expanding().max()) / eq_s.expanding().max()).min()
        ret_s = eq_s.pct_change().dropna()
        sharpe = ret_s.mean() / (ret_s.std() + 1e-8) * np.sqrt(252 * 48)

        report = {
            'total_trades': len(t), 'win_rate': len(wins) / len(t),
            'profit_factor': pf, 'total_return': eq_s.iloc[-1] / initial - 1,
            'max_drawdown': max_dd, 'sharpe': sharpe,
        }

        print(f"CS Trades: {report['total_trades']}, WinRate: {report['win_rate']*100:.1f}%, "
              f"Return: {report['total_return']*100:+.2f}%, Sharpe: {report['sharpe']:.2f}")

        return report, t, eq
