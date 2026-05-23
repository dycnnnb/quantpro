"""
回测 API
"""

import json
import threading
from pathlib import Path
from flask import Blueprint, request, jsonify
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import PATHS

backtest_bp = Blueprint('backtest', __name__, url_prefix='/api/backtest')


@backtest_bp.route('/run', methods=['POST'])
def run_backtest():
    """触发回测 — 复用日线回测逻辑"""
    data = request.get_json(silent=True) or {}
    data.setdefault('symbol', '000001')
    data.setdefault('start', '2024-01-01')
    data.setdefault('end', '2026-12-31')
    data.setdefault('capital', 100000)

    _daily_state = backtest_bp._daily_state

    with _daily_state['lock']:
        if _daily_state['running']:
            return jsonify({'success': False, 'error': '回测正在运行中'})

    symbol = data['symbol']
    start = data['start']
    end = data['end']
    capital = float(data['capital'])

    def _run():
        try:
            with _daily_state['lock']:
                _daily_state['running'] = True
                _daily_state['error'] = None

            from src.data.loader import DataLoader
            from src.backtest.engine import SingleStockBacktest, BacktestConfig
            import pandas as pd

            loader = DataLoader()
            df = loader.load_daily(symbol, start, end)
            if df.empty:
                raise ValueError(f"无法加载数据: {symbol}")

            signals = pd.DataFrame(index=df.index)
            close = df['close']
            ma5 = close.rolling(5).mean()
            ma20 = close.rolling(20).mean()
            signals['signal'] = 2
            signals.loc[ma5 > ma20, 'signal'] = 1
            signals['buy_prob'] = 0.6

            config = BacktestConfig(initial_capital=capital)
            bt = SingleStockBacktest(config)
            report, trades, equity = bt.run(df, signals)

            if report:
                report_dir = PATHS.get("cache_dir", Path("data/cache")) / "backtest"
                report_dir.mkdir(parents=True, exist_ok=True)
                from datetime import datetime as _dt
                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                report_file = report_dir / f"daily_{symbol}_{ts}_metrics.json"
                with open(report_file, 'w', encoding='utf-8') as f:
                    json.dump(report, f, ensure_ascii=False, indent=2, default=str)
                cache_file = PATHS.get("cache_dir", Path("data/cache")) / "daily_backtest.json"
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(report, f, ensure_ascii=False, indent=2, default=str)

            with _daily_state['lock']:
                _daily_state['last_result'] = report
        except Exception as e:
            with _daily_state['lock']:
                _daily_state['error'] = str(e)
        finally:
            with _daily_state['lock']:
                _daily_state['running'] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return jsonify({'success': True, 'message': f'回测已启动: {symbol}'})


@backtest_bp.route('/history')
def backtest_history():
    """回测历史"""
    report_dir = PATHS.get("cache_dir", Path("data/cache")) / "backtest"
    if not report_dir.exists():
        return jsonify({'success': True, 'data': []})
    try:
        files = sorted(report_dir.glob("*_metrics.json"), reverse=True)
        results = []
        for f in files[:20]:
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                results.append(data)
            except Exception:
                pass
        return jsonify({'success': True, 'data': results})
    except Exception:
        return jsonify({'success': True, 'data': []})


@backtest_bp.route('/daily')
def backtest_daily():
    """日线回测结果"""
    cache_file = PATHS.get("cache_dir", Path("data/cache")) / "daily_backtest.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding='utf-8'))
            return jsonify({'success': True, 'data': data})
        except Exception:
            pass
    return jsonify({'success': True, 'data': None})


@backtest_bp.route('/daily', methods=['POST'])
def run_daily_backtest():
    """触发日线回测（异步）"""
    import threading

    data = request.get_json(silent=True) or {}
    symbol = data.get('symbol', '000001')
    start = data.get('start', '2024-01-01')
    end = data.get('end', '2026-12-31')
    capital = float(data.get('capital', 100000))

    _daily_state = backtest_bp._daily_state

    with _daily_state['lock']:
        if _daily_state['running']:
            return jsonify({'success': False, 'error': '回测正在运行中'})

    def _run():
        try:
            with _daily_state['lock']:
                _daily_state['running'] = True
                _daily_state['error'] = None

            from src.data.loader import DataLoader
            from src.features.daily import DailyFeatureBuilder
            from src.backtest.engine import SingleStockBacktest, BacktestConfig

            loader = DataLoader()
            df = loader.load_daily(symbol, start, end)
            if df.empty:
                raise ValueError(f"无法加载数据: {symbol}")

            import pandas as pd
            signals = pd.DataFrame(index=df.index)
            try:
                import joblib as _jl
                model_files = sorted(PATHS["model_dir"].glob("cs_model_*.pkl"), reverse=True)
                if model_files:
                    ml_model = _jl.load(model_files[0])
                    from src.features.minute import MinuteFeatureBuilder
                    from src.features.cross_sectional import cross_sectional_normalize
                    fb = MinuteFeatureBuilder()
                    feat_df = fb.compute(df)
                    if feat_df is not None and not feat_df.empty:
                        feat_cols = [c for c in feat_df.columns if c not in ('code', 'date', 'time')]
                        latest_feat = feat_df[feat_cols].fillna(0).replace([float('inf'), float('-inf')], 0)
                        preds = ml_model.predict(latest_feat)
                        proba = ml_model.predict_proba(latest_feat) if hasattr(ml_model, 'predict_proba') else None
                        signals['signal'] = 2
                        signals.loc[preds == 1, 'signal'] = 1
                        signals.loc[preds == 0, 'signal'] = 0
                        if proba is not None:
                            signals['buy_prob'] = proba[:, 1] if proba.shape[1] > 1 else 0.5
                        else:
                            signals['buy_prob'] = 0.6
                    else:
                        raise ValueError("feature build empty")
                else:
                    raise ValueError("no model")
            except Exception:
                close = df['close']
                ma5 = close.rolling(5).mean()
                ma20 = close.rolling(20).mean()
                signals['signal'] = 2
                signals.loc[ma5 > ma20, 'signal'] = 1
                signals['buy_prob'] = 0.6

            config = BacktestConfig(initial_capital=capital)
            bt = SingleStockBacktest(config)
            report, trades, equity = bt.run(df, signals)

            if report:
                cache_file = PATHS.get("cache_dir", Path("data/cache")) / "daily_backtest.json"
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(report, f, ensure_ascii=False, indent=2, default=str)

            with _daily_state['lock']:
                _daily_state['last_result'] = report
        except Exception as e:
            with _daily_state['lock']:
                _daily_state['error'] = str(e)
        finally:
            with _daily_state['lock']:
                _daily_state['running'] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return jsonify({'success': True, 'message': f'日线回测已启动: {symbol}'})


backtest_bp._daily_state = {'running': False, 'last_result': None, 'error': None, 'lock': threading.Lock()}


@backtest_bp.route('/result/<int:backtest_id>')
def backtest_result(backtest_id):
    """获取指定回测结果"""
    report_dir = PATHS.get("cache_dir", Path("data/cache")) / "backtest"
    if not report_dir.exists():
        return jsonify({'success': False, 'error': 'No results'})
    try:
        files = list(report_dir.glob("*_metrics.json"))
        if backtest_id < len(files):
            data = json.loads(files[backtest_id].read_text(encoding='utf-8'))
            return jsonify({'success': True, 'data': data})
    except Exception:
        pass
    return jsonify({'success': False, 'error': 'Not found'})
