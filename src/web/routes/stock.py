"""
股票数据 API
"""

import sqlite3
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from src.data.loader import DataLoader
from src.data.realtime import RealtimeQuote

stock_bp = Blueprint('stock', __name__, url_prefix='/api/stock')
etf_bp = Blueprint('etf', __name__, url_prefix='/api/etf')
fund_bp = Blueprint('fund', __name__, url_prefix='/api/fund')
loader = DataLoader()
_realtime = RealtimeQuote()


def _get_db():
    """获取数据库连接"""
    from config.settings import DB
    return sqlite3.connect(str(DB["market"]))


@stock_bp.route('/list')
def stock_list():
    """股票列表 — 返回对象数组，支持分页和过滤"""
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 30, type=int)
    market = request.args.get('market', '').strip()
    keyword = request.args.get('filter', '').strip()
    # 'all' 不是搜索关键词，忽略它
    if keyword.lower() == 'all':
        keyword = ''
    min_days = request.args.get('min_days', 100, type=int)

    limit = min(limit, 100)
    offset = (page - 1) * limit

    try:
        with _get_db() as conn:
            conn.row_factory = sqlite3.Row

            # 1) 找到数据最完整的日期（用 COUNT 索引扫描，快）
            latest_date = conn.execute("""
                SELECT date FROM stock_kline
                GROUP BY date ORDER BY COUNT(*) DESC LIMIT 1
            """).fetchone()
            if not latest_date:
                return jsonify({'success': True, 'data': [], 'count': 0, 'total': 0,
                                'page': page, 'total_pages': 0})
            latest_date = latest_date[0]

            # 2) 前一个交易日（用于涨跌幅）
            prev_date = conn.execute(
                "SELECT MAX(date) FROM stock_kline WHERE date < ?", (latest_date,)
            ).fetchone()[0]

            # 3) 先拿当日所有股票行情（单表扫描，用 idx_kline_date 索引）
            market_filter = ""
            if market == 'sh':
                market_filter = "AND (code LIKE '6%' OR code LIKE '9%')"
            elif market == 'sz':
                market_filter = "AND (code LIKE '0%' OR code LIKE '3%' OR code LIKE '2%')"

            current_rows = conn.execute(f"""
                SELECT code, close as price, open, high, low, volume, amount
                FROM stock_kline
                WHERE date = ? {market_filter}
                ORDER BY code
            """, (latest_date,)).fetchall()

            # 按 code 建索引
            current_map = {}
            for r in current_rows:
                code = r[0]
                # 关键字过滤
                if keyword and keyword.lower() not in code.lower():
                    continue
                current_map[code] = {
                    'code': code,
                    'price': r[1] or 0,
                    'open': r[2] or 0,
                    'high': r[3] or 0,
                    'low': r[4] or 0,
                    'volume': r[5] or 0,
                    'amount': r[6] or 0,
                }

            # 4) 过滤掉数据天数不够的股票（批量查询每个 code 的行数）
            valid_codes = []
            code_list = list(current_map.keys())
            if code_list and min_days > 0:
                # 分批查询，避免 IN 子句过大
                for i in range(0, len(code_list), 500):
                    batch = code_list[i:i+500]
                    placeholders = ','.join('?' * len(batch))
                    cnt_rows = conn.execute(f"""
                        SELECT code, COUNT(*) as cnt
                        FROM stock_kline
                        WHERE code IN ({placeholders})
                        GROUP BY code HAVING cnt >= ?
                    """, batch + [min_days]).fetchall()
                    valid_codes.extend(r[0] for r in cnt_rows)
            else:
                valid_codes = code_list

            # 关键字过滤（如果 stock_info 表有数据，按名称过滤）
            if keyword and valid_codes:
                try:
                    name_rows = conn.execute(
                        f"SELECT code, name FROM stock_info WHERE name LIKE ?",
                        (f'%{keyword}%',)
                    ).fetchall()
                    name_match_codes = {r[0] for r in name_rows}
                    valid_codes = [c for c in valid_codes
                                   if c in name_match_codes or keyword.lower() in c.lower()]
                except Exception:
                    pass

            total = len(valid_codes)

            # 5) 分页
            paged_codes = valid_codes[offset:offset + limit]

            # 6) 批量查前一天收盘价（利用 idx_kline_code_date 索引）
            prev_close_map = {}
            if paged_codes and prev_date:
                for i in range(0, len(paged_codes), 500):
                    batch = paged_codes[i:i+500]
                    placeholders = ','.join('?' * len(batch))
                    prev_rows = conn.execute(f"""
                        SELECT code, close FROM stock_kline
                        WHERE date = ? AND code IN ({placeholders})
                    """, [prev_date] + batch).fetchall()
                    for r in prev_rows:
                        prev_close_map[r[0]] = r[1]

            # 7) 批量查 stock_info（名称 + 行业）
            name_map = {}
            if paged_codes:
                for i in range(0, len(paged_codes), 500):
                    batch = paged_codes[i:i+500]
                    placeholders = ','.join('?' * len(batch))
                    info_rows = conn.execute(f"""
                        SELECT code, name, industry FROM stock_info
                        WHERE code IN ({placeholders})
                    """, batch).fetchall()
                    for r in info_rows:
                        name_map[r[0]] = {'name': r[1], 'industry': r[2] or ''}

            # 8) 组装结果
            data = []
            for code in paged_codes:
                d = current_map[code]
                price = d['price']
                prev_close = prev_close_map.get(code) or price
                change = price - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0
                info = name_map.get(code, {})

                data.append({
                    'code': code,
                    'name': info.get('name') or code,
                    'market': 'sh' if code.startswith('6') or code.startswith('9') else 'sz',
                    'industry': info.get('industry', ''),
                    'price': round(price, 2),
                    'open': round(d['open'], 2),
                    'high': round(d['high'], 2),
                    'low': round(d['low'], 2),
                    'volume': d['volume'] or 0,
                    'amount': round(d['amount'], 2),
                    'change': round(change, 2),
                    'change_pct': round(change_pct, 2),
                    'trade_date': latest_date,
                })

            total_pages = (total + limit - 1) // limit

            return jsonify({
                'success': True,
                'data': data,
                'count': len(data),
                'total': total,
                'page': page,
                'total_pages': total_pages,
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e), 'data': [], 'count': 0, 'total': 0, 'page': 1, 'total_pages': 0})


@stock_bp.route('/search')
def stock_search():
    """搜索股票"""
    keyword = request.args.get('keyword', '').strip()
    if not keyword:
        return jsonify({'success': True, 'data': []})
    try:
        symbols = loader.get_daily_symbols(min_days=100)
        name_map = _get_stock_names()
        results = []
        for s in symbols:
            name = name_map.get(s, '')
            if keyword in s or keyword in name:
                results.append({'code': s, 'name': name})
            if len(results) >= 20:
                break
        return jsonify({'success': True, 'data': results})
    except Exception:
        return jsonify({'success': True, 'data': []})


@stock_bp.route('/detail/<code>')
def stock_detail(code):
    """股票详情（汇总信息）"""
    period = request.args.get('period', 'day')
    try:
        if period == '5m':
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date_dt = datetime.now() - timedelta(days=30)
            start_date = start_date_dt.strftime('%Y-%m-%d')
            df = loader.load_minute(code, start_date, end_date, freq='5min')
            if df.empty:
                return jsonify({'success': False, 'error': 'No 5min data'})

            name_map = _get_stock_names()
            market = '深交所' if code.startswith('0') or code.startswith('3') else '上交所'

            kline = []
            for idx, row in df.tail(240).iterrows():
                kline.append({
                    'date': idx.strftime('%Y-%m-%d %H:%M'),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume']),
                })

            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            close = float(latest['close'])
            prev_close = float(prev['close'])
            change = close - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0

            data = {
                'code': code,
                'name': name_map.get(code, code),
                'market': market,
                'industry': '',
                'close': close,
                'open': float(latest['open']),
                'high': float(latest['high']),
                'low': float(latest['low']),
                'volume': float(latest['volume']),
                'change': round(change, 2),
                'change_pct': round(change_pct, 2),
                'kline': kline,
                'data_range': f"{df.index[0]} ~ {df.index[-1]}" if len(df) > 0 else '',
            }
            return jsonify({'success': True, 'data': data})

        df = loader.load_daily(code, '2020-01-01', datetime.now().strftime('%Y-%m-%d'))
        if df.empty:
            return jsonify({'success': False, 'error': 'No data'})

        latest = df.iloc[-1] if len(df) > 0 else None
        prev = df.iloc[-2] if len(df) > 1 else None

        close = float(latest['close']) if latest is not None else 0
        prev_close = float(prev['close']) if prev is not None else close
        change = close - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0

        name_map = _get_stock_names()
        market = '深交所' if code.startswith('0') or code.startswith('3') else '上交所'

        kline_df = df.tail(120).reset_index()
        kline_df['date'] = kline_df['date'].dt.strftime('%Y-%m-%d')

        data = {
            'code': code,
            'name': name_map.get(code, code),
            'market': market,
            'industry': '',
            'close': close,
            'open': float(latest['open']) if latest is not None else 0,
            'high': float(latest['high']) if latest is not None else 0,
            'low': float(latest['low']) if latest is not None else 0,
            'volume': float(latest['volume']) if latest is not None else 0,
            'change': round(change, 2),
            'change_pct': round(change_pct, 2),
            'kline': kline_df.to_dict(orient='records'),
            'data_range': f"{df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}" if len(df) > 0 else '',
        }
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 基金数据 API ─────────────────────────────────────────────────
@fund_bp.route('/list')
def fund_list():
    limit = request.args.get('limit', 50, type=int)
    try:
        with _get_db() as conn:
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT code, name FROM stock_info WHERE code LIKE '50%' OR code LIKE '16%' LIMIT ?",
                    (limit,)
                ).fetchall()
                data = [{'code': r['code'], 'name': r['name'], 'type': '基金'} for r in rows]
            except Exception:
                data = []
        return jsonify({'success': True, 'data': data, 'count': len(data)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@fund_bp.route('/detail/<code>')
def fund_detail(code):
    try:
        name_map = _get_stock_names()
        name = name_map.get(code, code)
        df = loader.load_daily(code, '2020-01-01', datetime.now().strftime('%Y-%m-%d'))
        nav_history = []
        if not df.empty:
            for idx, row in df.tail(120).iterrows():
                nav_history.append({
                    'date': idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx),
                    'nav': float(row.get('close', 0)),
                })
        return jsonify({
            'success': True,
            'data': {
                'code': code, 'name': name, 'type': '基金',
                'nav': nav_history[-1]['nav'] if nav_history else 0,
                'nav_history': nav_history,
                'holdings': [], 'industry': [],
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@stock_bp.route('/company_desc/<code>')
def stock_company_desc(code):
    """公司简介"""
    name = request.args.get('name', '')
    name_map = _get_stock_names()
    stock_name = name or name_map.get(code, code)

    company_intro = ''
    main_business = ''
    try:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT industry, area FROM stock_info WHERE code = ? LIMIT 1",
                (code,)
            ).fetchone()
            if row:
                industry = row[0] or ''
                area = row[1] or ''
                if industry or area:
                    company_intro = f'{stock_name}（{code}）{"，位于" + area if area else ""}{"，所属行业：" + industry if industry else ""}。'
                    main_business = f'所属行业：{industry}' if industry else ''
    except Exception:
        pass

    if not company_intro:
        company_intro = f'{stock_name}（{code}）是一家A股上市公司，详细信息请参考公司年报。'
    if not main_business:
        main_business = '具体业务信息请参考公司年报。'

    data = {
        'analysis': {
            'company_intro': company_intro,
            'main_business': main_business,
        },
        'latest_news': [],
    }
    return jsonify({'success': True, 'data': data})


def _get_stock_names():
    """获取股票名称映射（同时支持带/不带市场前缀的code）"""
    try:
        with _get_db() as conn:
            rows = conn.execute("SELECT code, name FROM stock_info").fetchall()
            m = {}
            for r in rows:
                if r[0] and r[1]:
                    m[r[0]] = r[1]
                    prefix = 'sh' if r[0].startswith('6') or r[0].startswith('9') else 'sz'
                    m[prefix + r[0]] = r[1]
            return m
    except Exception:
        return {}


@stock_bp.route('/daily/<code>')
def stock_daily(code):
    start = request.args.get('start', '2020-01-01')
    end = request.args.get('end', datetime.now().strftime('%Y-%m-%d'))
    df = loader.load_daily(code, start, end)
    if df.empty:
        return jsonify({'success': False, 'error': 'No data'})
    result_df = df.reset_index()
    result_df['date'] = result_df['date'].dt.strftime('%Y-%m-%d')
    return jsonify({
        'success': True,
        'data': result_df.to_dict(orient='records'),
        'count': len(df),
    })


@stock_bp.route('/realtime/<code>')
def stock_realtime(code):
    """单只股票实时行情"""
    quote = _realtime.get_quote(code)
    bare = code.split(".")[-1] if "." in code else code
    if bare not in quote:
        return jsonify({'success': False, 'error': 'No realtime data'})
    return jsonify({'success': True, 'data': quote[bare]})


@stock_bp.route('/realtime')
def stock_realtime_batch():
    """批量实时行情 codes=600519,000001"""
    codes_str = request.args.get('codes', '')
    if not codes_str:
        return jsonify({'success': False, 'error': 'Missing codes param'})
    codes = [c.strip() for c in codes_str.split(',') if c.strip()]
    if not codes:
        return jsonify({'success': False, 'error': 'Empty codes'})
    df = _realtime.get_snapshot(codes)
    if df.empty:
        return jsonify({'success': False, 'error': 'No realtime data'})
    return jsonify({
        'success': True,
        'data': df.reset_index().to_dict(orient='records'),
        'count': len(df),
    })


@stock_bp.route('/info')
def stock_info():
    info = loader.get_db_info()
    return jsonify({'success': True, 'data': info})


@stock_bp.route('/top10')
def stock_top10():
    from config.settings import DB, PATHS
    result = {"watching": [], "trading": []}

    try:
        with _get_db() as conn:
            conn.row_factory = sqlite3.Row
            latest_date = conn.execute(
                "SELECT date FROM stock_kline GROUP BY date ORDER BY COUNT(*) DESC LIMIT 1"
            ).fetchone()
            if not latest_date:
                return jsonify({"success": True, "data": result})
            latest_date = latest_date[0]
            prev_date = conn.execute(
                "SELECT MAX(date) FROM stock_kline WHERE date < ?", (latest_date,)
            ).fetchone()[0]

            rows = conn.execute("""
                SELECT k.code, i.name,
                       k.close AS price, k.volume,
                       p.close AS prev_close
                FROM stock_kline k
                LEFT JOIN stock_info i ON k.code = i.code
                LEFT JOIN stock_kline p ON k.code = p.code AND p.date = ?
                WHERE k.date = ?
                ORDER BY (k.close - p.close) / MAX(p.close, 0.01) DESC
                LIMIT 10
            """, (prev_date, latest_date)).fetchall()

            for r in rows:
                prev_c = r["prev_close"] or r["price"]
                chg = r["price"] - prev_c if prev_c else 0
                chg_pct = (chg / prev_c * 100) if prev_c else 0
                result["watching"].append({
                    "code": r["code"],
                    "name": r["name"] or r["code"],
                    "price": round(r["price"], 2),
                    "change_pct": round(chg_pct, 2),
                    "volume": r["volume"],
                })
    except Exception:
        pass

    try:
        cache_file = PATHS.get("cache_dir", Path("data/cache")) / "mock_account.json"
        if cache_file.exists():
            import json
            state = json.loads(cache_file.read_text(encoding="utf-8"))
            positions = state.get("positions", {})
            for code, pos in positions.items():
                name = pos.get("name", code)
                entry = pos.get("entry_price", 0)
                cur = pos.get("current_price", entry)
                shares = pos.get("shares", 0)
                pnl_pct = ((cur - entry) / entry * 100) if entry else 0
                result["trading"].append({
                    "code": code,
                    "name": name,
                    "price": round(cur, 2),
                    "entry_price": round(entry, 2),
                    "shares": shares,
                    "pnl_pct": round(pnl_pct, 2),
                })
    except Exception:
        pass

    return jsonify({"success": True, "data": result})


# ── ETF 数据 API ─────────────────────────────────────────────────

@etf_bp.route('/list')
def etf_list():
    """获取ETF列表"""
    limit = request.args.get('limit', 50, type=int)
    try:
        # 从stock_info表中获取ETF数据（代码以510、513、159等开头）
        with _get_db() as conn:
            conn.row_factory = sqlite3.Row
            # 先检查是否有ETF标记字段
            try:
                rows = conn.execute(
                    "SELECT code, name FROM stock_info WHERE code LIKE '510%' OR code LIKE '513%' OR code LIKE '159%' OR code LIKE '588%' LIMIT ?",
                    (limit,)
                ).fetchall()
            except Exception:
                # 如果没有stock_info表或字段，返回常见ETF
                rows = []

            if not rows:
                return jsonify({'success': True, 'data': [], 'count': 0, 'message': '暂无ETF数据，请先更新数据'})

            return jsonify({
                'success': True,
                'data': [dict(r) for r in rows],
                'count': len(rows)
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@etf_bp.route('/detail/<code>')
def etf_detail(code):
    """获取ETF详情"""
    try:
        # 获取ETF基本信息
        with _get_db() as conn:
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT * FROM stock_info WHERE code = ?", (code,)
                ).fetchone()
            except Exception:
                row = None

            name = row['name'] if row else code

        # 获取K线数据
        df = loader.load_daily(code, '2020-01-01', datetime.now().strftime('%Y-%m-%d'))
        if df.empty:
            return jsonify({'success': False, 'error': 'No data'})

        latest = df.iloc[-1] if len(df) > 0 else None
        prev = df.iloc[-2] if len(df) > 1 else None

        close = float(latest['close']) if latest is not None else 0
        prev_close = float(prev['close']) if prev is not None else close
        change = close - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0

        kline_df = df.tail(120).reset_index()
        kline_df['date'] = kline_df['date'].dt.strftime('%Y-%m-%d')

        data = {
            'code': code,
            'name': name,
            'close': close,
            'open': float(latest['open']) if latest is not None else 0,
            'high': float(latest['high']) if latest is not None else 0,
            'low': float(latest['low']) if latest is not None else 0,
            'volume': float(latest['volume']) if latest is not None else 0,
            'change': round(change, 2),
            'change_pct': round(change_pct, 2),
            'kline': kline_df.to_dict(orient='records'),
        }
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
