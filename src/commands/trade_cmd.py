"""
交易命令 — 模拟交易
"""

import sys
import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config.settings import DB, trade_config, PATHS


def _init_trade_db():
    """初始化交易数据库（兼容旧表结构）"""
    db_path = DB["quantpro"]
    conn = sqlite3.connect(str(db_path))
    # Positions table — use existing schema if present, else create
    conn.execute('''CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT, name TEXT DEFAULT '', entry_date DATE, entry_price REAL,
        shares INTEGER, cost_amount REAL, stop_loss_price REAL,
        take_profit_price REAL, max_hold_days INTEGER DEFAULT 10,
        signal_score REAL, regime_at_entry TEXT,
        status TEXT DEFAULT 'open', current_price REAL DEFAULT 0,
        unrealized_pnl REAL DEFAULT 0, unrealized_pct REAL DEFAULT 0,
        exit_date DATE, exit_price REAL, exit_reason TEXT,
        realized_pnl REAL, realized_pct REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS trade_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT, code TEXT, action TEXT,
        price REAL, shares INTEGER, pnl REAL,
        reason TEXT, score REAL
    )''')
    conn.commit()
    conn.close()


def _load_open_positions():
    db_path = DB["quantpro"]
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT id, code, entry_price, entry_date, shares, stop_loss_price, take_profit_price "
        "FROM positions WHERE status='open'"
    ).fetchall()
    conn.close()
    return {r[1]: dict(id=r[0], code=r[1], entry_price=r[2], entry_date=r[3],
                        shares=r[4], stop_loss=r[5], take_profit=r[6]) for r in rows}


def _save_position(code, price, shares, stop_loss, take_profit):
    db_path = DB["quantpro"]
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        "INSERT INTO positions (code, entry_date, entry_price, shares, cost_amount, stop_loss_price, take_profit_price) "
        "VALUES (?,?,?,?,?,?,?)",
        (code, date.today().isoformat(), price, shares, price * shares, stop_loss, take_profit),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def _close_position_db(pos_id):
    db_path = DB["quantpro"]
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE positions SET status='closed' WHERE id=?", (pos_id,))
    conn.commit()
    conn.close()


def _log_trade(date_str, code, action, price, shares, pnl, reason, score):
    db_path = DB["quantpro"]
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO trade_log (date,code,action,price,shares,pnl,reason,score) VALUES (?,?,?,?,?,?,?,?)",
        (date_str, code, action, price, shares, pnl, reason, score),
    )
    conn.commit()
    conn.close()


def cmd_trade_run(args):
    """每日模拟交易"""
    from src.data.loader import DataLoader
    from src.strategy.position import PositionManager
    from src.strategy.risk import RiskController
    from src.strategy.regime import RegimeDetector

    _init_trade_db()
    dry_run = args.dry_run

    print("=" * 60)
    mode = "DRY-RUN" if dry_run else "LIVE PAPER"
    print(f"Paper Trading [{mode}]")
    print("=" * 60)

    # Load positions
    open_pos = _load_open_positions()
    print(f"Open positions: {len(open_pos)}")

    # Load data
    loader = DataLoader()
    symbols = loader.get_daily_symbols(min_days=100)[:100]
    if not symbols:
        print("No stocks available")
        return

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")

    # Compute scores
    import pandas as pd
    all_scores = {}
    price_map = {}

    for code in symbols:
        try:
            df = loader.load_daily(code, start, end)
            if df.empty or len(df) < 30:
                continue

            close = df['close']
            low = df['low']

            # Factor scoring
            reversal = -close.pct_change(5).iloc[-1]
            low_10 = low.rolling(10, min_periods=3).min()
            dist_low = ((close - low_10) / (close + 1e-8)).iloc[-1]
            ma3 = close.rolling(3).mean()
            ma10 = close.rolling(10).mean()
            trend = ((ma3 - ma10) / (ma10 + 1e-8)).iloc[-1]
            vol_shrink = -(df['volume'] / (df['volume'].rolling(10).mean() + 1e-8)).iloc[-1]

            score = (reversal + dist_low + trend + vol_shrink) / 4
            all_scores[code] = score
            price_map[code] = float(close.iloc[-1])

            # Regime detection
            if code == symbols[0]:
                rd = RegimeDetector(close)
                regime_info = rd.get_info()
        except Exception:
            pass

    if not all_scores:
        print("No scores computed")
        return

    score_series = pd.Series(all_scores).sort_values(ascending=False)
    regime = regime_info.get('regime', 'neutral')
    scale = regime_info.get('position_scale', 0.5)
    print(f"Market regime: {regime}, position scale: {scale}")
    print(f"Scored {len(score_series)} stocks")

    # Check exits
    risk = RiskController()
    to_close = []
    for code, pos_info in open_pos.items():
        price = price_map.get(code)
        if price is None:
            continue
        from datetime import datetime as dt
        should_close, reason = False, ""
        if price <= pos_info['stop_loss']:
            should_close, reason = True, "stop_loss"
        elif price >= pos_info['take_profit']:
            should_close, reason = True, "take_profit"
        elif price / pos_info['entry_price'] - 1 > 0.15:
            should_close, reason = True, "take_profit_15pct"

        if should_close:
            to_close.append((code, price, reason, pos_info))

    # Execute sells
    for code, exit_price, reason, pos_info in to_close:
        pnl = (exit_price - pos_info['entry_price']) * pos_info['shares']
        if not dry_run:
            _close_position_db(pos_info['id'])
            _log_trade(str(date.today()), code, "SELL", exit_price,
                       pos_info['shares'], pnl, reason, 0)
        print(f"  SELL {code} @ {exit_price:.2f} PnL={pnl:+,.0f} [{reason}]")

    # Execute buys
    held_codes = set(open_pos.keys()) - {c for c, _, _, _ in to_close}
    n_slots = trade_config.max_positions - len(held_codes)
    if n_slots > 0 and scale > 0:
        for code, score in score_series.head(n_slots + len(held_codes)).items():
            if code in held_codes or score < 0.5:
                continue
            price = price_map.get(code)
            if price is None:
                continue

            per_stock = trade_config.total_capital * scale / trade_config.max_positions
            shares = int(per_stock / price / 100) * 100
            if shares <= 0:
                continue

            stop_loss = price * (1 + trade_config.stop_loss_pct)
            take_profit = price * (1 + trade_config.take_profit_pct)

            if not dry_run:
                _save_position(code, price, shares, stop_loss, take_profit)
                _log_trade(str(date.today()), code, "BUY", price, shares, 0, "score_top", score)
            print(f"  BUY  {code} @ {price:.2f} x{shares} score={score:.3f}")

    print(f"\nDone. {'(dry-run)' if dry_run else ''}")


def cmd_trade_status(args):
    """查看持仓状态"""
    _init_trade_db()
    open_pos = _load_open_positions()
    if not open_pos:
        print("No open positions")
        return

    print(f"Open positions: {len(open_pos)}")
    total_cost = 0
    for code, p in open_pos.items():
        cost = p['entry_price'] * p['shares']
        total_cost += cost
        entry_date = p.get('entry_date', 'N/A')
        print(f"  {code}: {p['shares']} shares @ {p['entry_price']:.2f} (cost={cost:,.0f}, date={entry_date})")
    print(f"Total cost: {total_cost:,.0f}")


def cmd_trade_history(args):
    """查看交易历史"""
    db_path = DB["quantpro"]
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT date, code, action, price, shares, pnl, reason FROM trade_log ORDER BY id DESC LIMIT ?",
        (args.limit,)
    ).fetchall()
    conn.close()

    if not rows:
        print("No trade history")
        return

    print(f"Last {len(rows)} trades:")
    for r in rows:
        print(f"  {r[0]} {r[2]:4s} {r[1]} @ {r[3]:.2f} x{r[4]} PnL={r[5]:+,.0f} [{r[6]}]")
