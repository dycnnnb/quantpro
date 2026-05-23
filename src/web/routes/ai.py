"""
AI 选股/聊天/分析 API — 基于 DeepSeek
"""

import json
import re
import sqlite3

from flask import Blueprint, request, jsonify
from openai import OpenAI

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DEEPSEEK_API_KEY, DB, ai_config
from src.data.loader import DataLoader
from src.data.realtime import RealtimeQuote
from src.utils.operation_logger import log_ai

ai_bp = Blueprint('ai', __name__, url_prefix='/api/ai')
chat_bp = Blueprint('chat', __name__, url_prefix='/api/chat')

_loader = DataLoader()
_realtime = RealtimeQuote()


def _get_client() -> OpenAI:
    return OpenAI(api_key=ai_config.api_key, base_url=ai_config.base_url)


# ── AI 聊天 ─────────────────────────────────────────────────────
CHAT_SYSTEM = """你是 QuantPro 量化投资助手。你精通 A 股市场分析、技术指标、量化策略。
回答要简洁专业，适当使用数据支撑观点。如果用户问持仓或行情，尝试提供有用的分析。"""


@ai_bp.route('/chat', methods=['POST'])
def ai_chat():
    """AI 聊天（支持流式）"""
    data = request.get_json(silent=True) or {}
    message = data.get('message', '').strip()
    if not message:
        return jsonify({'success': False, 'error': '消息不能为空'}), 400

    stream = data.get('stream', False)

    try:
        client = _get_client()
        messages = [
            {"role": "system", "content": CHAT_SYSTEM},
            {"role": "user", "content": message},
        ]

        if stream:
            from flask import Response
            def generate():
                resp = client.chat.completions.create(
                    model=ai_config.chat_model, messages=messages, stream=True
                )
                for chunk in resp:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield f"data: {json.dumps({'content': chunk.choices[0].delta.content}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            log_ai('chat', f'msg={message[:50]}')
            return Response(generate(), content_type='text/event-stream')

        resp = client.chat.completions.create(
            model=ai_config.chat_model, messages=messages
        )
        reply = resp.choices[0].message.content
        log_ai('chat', f'msg={message[:50]}')
        return jsonify({'success': True, 'data': {'reply': reply}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── AI 选股 ─────────────────────────────────────────────────────
SELECT_SYSTEM = """你是量化选股分析师。根据用户给出的条件，从 A 股中筛选合适的股票。
返回 JSON 格式：
{
  "stocks": [
    {"code": "600519", "name": "贵州茅台", "score": 0.85, "reason": "技术面突破MA20，RSI处于合理区间"}
  ],
  "summary": "整体市场分析摘要"
}
只返回有效 JSON。"""


@ai_bp.route('/select', methods=['GET', 'POST'])
def ai_select():
    """AI 选股"""
    if request.method == 'GET':
        # 默认选股：基于简单的技术因子
        try:
            symbols = _loader.get_daily_symbols(min_days=60)[:50]
            if not symbols:
                return jsonify({'success': True, 'data': [], 'message': '无可用股票数据'})

            # 简单因子打分
            scores = {}
            for code in symbols:
                try:
                    df = _loader.load_daily(code)
                    if df.empty or len(df) < 20:
                        continue
                    close = df['close']
                    ma20 = close.rolling(20).mean().iloc[-1]
                    ma5 = close.rolling(5).mean().iloc[-1]
                    rsi = _calc_rsi(close)
                    score = 0.0
                    if close.iloc[-1] > ma20:
                        score += 0.3
                    if ma5 > ma20:
                        score += 0.2
                    if 30 < rsi < 70:
                        score += 0.2
                    vol = df['volume'].iloc[-1]
                    vol_ma = df['volume'].rolling(20).mean().iloc[-1]
                    if vol > vol_ma * 1.2:
                        score += 0.15
                    pct = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] if len(close) >= 5 else 0
                    if -0.05 < pct < 0.05:
                        score += 0.15
                    scores[code] = round(score, 3)
                except Exception:
                    pass

            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
            data = [{'code': code, 'score': score} for code, score in ranked]
            log_ai('select_simple', f'found={len(data)}')
            return jsonify({'success': True, 'data': data})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    # POST: AI 深度选股
    data = request.get_json(silent=True) or {}
    prompt = data.get('prompt', '筛选近期有突破迹象的 A 股')

    try:
        client = _get_client()
        # 获取一些候选股票的基本信息
        symbols = _loader.get_daily_symbols(min_days=60)[:30]
        stock_info = []
        for code in symbols[:20]:
            try:
                df = _loader.load_daily(code)
                if df.empty or len(df) < 5:
                    continue
                close = df['close']
                pct = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100
                stock_info.append(f"{code}: 近5日{pct:+.1f}%")
            except Exception:
                pass

        user_msg = f"筛选条件: {prompt}\n\n候选股票近5日涨跌幅:\n" + "\n".join(stock_info)

        resp = client.chat.completions.create(
            model=ai_config.chat_model,
            messages=[
                {"role": "system", "content": SELECT_SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        )
        reply = resp.choices[0].message.content
        match = re.search(r'\{.*\}', reply, re.DOTALL)
        if match:
            result = json.loads(match.group())
            log_ai('select_ai', f'prompt={prompt[:50]}')
            return jsonify({'success': True, 'data': result.get('stocks', []),
                            'summary': result.get('summary', '')})
        return jsonify({'success': True, 'data': [], 'summary': reply})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── AI 分析个股 ─────────────────────────────────────────────────
ANALYZE_SYSTEM = """你是专业的量化分析师。分析给定股票的技术面和基本面，给出投资建议。
返回简洁的分析报告，包含：趋势判断、支撑/压力位、风险提示、操作建议。"""


@ai_bp.route('/analyze', methods=['POST'])
def ai_analyze():
    """AI 分析个股"""
    data = request.get_json(silent=True) or {}
    code = data.get('code', '').strip()
    if not code:
        return jsonify({'success': False, 'error': '需要股票代码'}), 400

    try:
        df = _loader.load_daily(code)
        if df.empty:
            return jsonify({'success': False, 'error': f'{code} 无数据'})

        close = df['close']
        # 技术指标摘要
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None
        rsi = _calc_rsi(close)
        vol = df['volume']
        vol_ratio = vol.iloc[-1] / vol.rolling(20).mean().iloc[-1] if vol.rolling(20).mean().iloc[-1] > 0 else 1
        high_20 = df['high'].rolling(20).max().iloc[-1]
        low_20 = df['low'].rolling(20).min().iloc[-1]
        pct_5d = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100 if len(close) >= 5 else 0

        info = f"""股票 {code} 近期数据:
- 当前价: {close.iloc[-1]:.2f}
- 5日涨跌: {pct_5d:+.1f}%
- MA5: {ma5:.2f}, MA20: {ma20:.2f}, MA60: {f'{ma60:.2f}' if ma60 is not None else 'N/A'}
- RSI(14): {rsi:.1f}
- 量比: {vol_ratio:.2f}
- 20日高/低: {high_20:.2f} / {low_20:.2f}
- 20日振幅: {(high_20 - low_20) / low_20 * 100:.1f}%"""

        # 实时价格
        rt = _realtime.get_price(code)
        if rt:
            info += f"\n- 实时价格: {rt}"

        client = _get_client()
        resp = client.chat.completions.create(
            model=ai_config.chat_model,
            messages=[
                {"role": "system", "content": ANALYZE_SYSTEM},
                {"role": "user", "content": info},
            ]
        )
        reply = resp.choices[0].message.content
        log_ai('analyze', f'code={code}')
        return jsonify({'success': True, 'data': {'code': code, 'analysis': reply}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── AI 交易信号 ─────────────────────────────────────────────────
SIGNAL_SYSTEM = """你是量化交易信号生成器。根据股票数据生成交易信号。

返回 JSON:
{
  "signal": "buy" | "sell" | "hold",
  "confidence": <0.0-1.0>,
  "reason": "信号原因",
  "target_price": <目标价>,
  "stop_loss": <止损价>
}
只返回有效 JSON。"""


@ai_bp.route('/trade_signal', methods=['POST'])
def ai_trade_signal():
    """生成交易信号"""
    data = request.get_json(silent=True) or {}
    code = data.get('code', '').strip()
    if not code:
        return jsonify({'success': False, 'error': '需要股票代码'}), 400

    try:
        df = _loader.load_daily(code)
        if df.empty or len(df) < 20:
            return jsonify({'success': False, 'error': '数据不足'})

        close = df['close']
        info = f"""股票 {code} 数据摘要:
当前价: {close.iloc[-1]:.2f}
近5日: {(close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100:+.1f}%
近20日: {(close.iloc[-1] - close.iloc[-20]) / close.iloc[-20] * 100:+.1f}%
MA5: {close.rolling(5).mean().iloc[-1]:.2f}
MA20: {close.rolling(20).mean().iloc[-1]:.2f}
RSI: {_calc_rsi(close):.1f}
20日高: {df['high'].rolling(20).max().iloc[-1]:.2f}
20日低: {df['low'].rolling(20).min().iloc[-1]:.2f}"""

        client = _get_client()
        resp = client.chat.completions.create(
            model=ai_config.chat_model,
            messages=[
                {"role": "system", "content": SIGNAL_SYSTEM},
                {"role": "user", "content": info},
            ]
        )
        reply = resp.choices[0].message.content
        match = re.search(r'\{.*\}', reply, re.DOTALL)
        if match:
            signal = json.loads(match.group())
            log_ai('trade_signal', f'code={code} signal={signal.get("signal")}')
            return jsonify({'success': True, 'data': signal})
        return jsonify({'success': True, 'data': {'signal': 'hold', 'confidence': 0, 'reason': reply}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 市场概览 ────────────────────────────────────────────────────
@ai_bp.route('/market_overview', methods=['POST'])
def ai_market_overview():
    """AI 市场概览"""
    try:
        # 获取大盘数据
        indices = {'000001': '上证', '399001': '深证', '399006': '创业板'}
        idx_info = []
        for code, name in indices.items():
            price = _realtime.get_price(code)
            if price:
                idx_info.append(f"{name}: {price}")

        # 获取市场涨跌统计
        symbols = _loader.get_daily_symbols(min_days=5)[:100]
        up, down = 0, 0
        for code in symbols:
            try:
                df = _loader.load_daily(code)
                if not df.empty and len(df) >= 2:
                    if df['close'].iloc[-1] > df['close'].iloc[-2]:
                        up += 1
                    else:
                        down += 1
            except Exception:
                pass

        info = f"大盘指数:\n" + "\n".join(idx_info) + f"\n\n市场统计: 上涨{up}家, 下跌{down}家"

        client = _get_client()
        resp = client.chat.completions.create(
            model=ai_config.chat_model,
            messages=[
                {"role": "system", "content": "你是市场分析师，简要分析当前 A 股市场状态。"},
                {"role": "user", "content": info},
            ]
        )
        log_ai('market_overview', '')
        return jsonify({'success': True, 'data': {'overview': resp.choices[0].message.content}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 辅助函数 ────────────────────────────────────────────────────
def _calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-10)
    rsi = 100 - 100 / (1 + rs)
    return float(rsi.iloc[-1]) if not rsi.empty else 50


# ── AI 流式聊天（独立端点） ─────────────────────────────────────
@ai_bp.route('/chat/stream', methods=['POST'])
def ai_chat_stream():
    """AI 流式聊天（SSE）— 支持单条 message 或 messages 数组"""
    data = request.get_json(silent=True) or {}

    # 支持两种格式: {message: "..."} 或 {messages: [{role, content}, ...]}
    message = data.get('message', '').strip()
    history = data.get('messages', [])

    if not message and history:
        # 从 history 数组中提取最后一条用户消息作为当前消息
        user_msgs = [m for m in history if m.get('role') == 'user']
        if user_msgs:
            message = user_msgs[-1].get('content', '')

    if not message:
        return jsonify({'success': False, 'error': '消息不能为空'}), 400

    try:
        from flask import Response
        client = _get_client()

        # 构建消息列表：系统提示 + 历史上下文
        messages = [{"role": "system", "content": CHAT_SYSTEM}]
        if history:
            for m in history:
                role = m.get('role', 'user')
                if role in ('user', 'assistant'):
                    messages.append({"role": role, "content": m.get('content', '')})
        else:
            messages.append({"role": "user", "content": message})

        def generate():
            resp = client.chat.completions.create(
                model=ai_config.chat_model, messages=messages, stream=True
            )
            for chunk in resp:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield f"data: {json.dumps({'content': chunk.choices[0].delta.content}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        log_ai('chat_stream', f'msg={message[:50]}')
        return Response(generate(), content_type='text/event-stream')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── AI 状态 ─────────────────────────────────────────────────────
@ai_bp.route('/status')
def ai_status():
    """AI 服务状态"""
    return jsonify({
        'success': True,
        'data': {
            'api_configured': bool(DEEPSEEK_API_KEY),
            'model': ai_config.chat_model,
            'status': 'ok' if DEEPSEEK_API_KEY else 'no_api_key',
        }
    })


# ── AI 用户上下文 ───────────────────────────────────────────────
@ai_bp.route('/user_context')
def ai_user_context():
    """获取用户上下文（持仓、偏好等）"""
    try:
        cache_file = PATHS.get("cache_dir", Path("data/cache")) / "mock_account.json"
        positions = []
        if cache_file.exists():
            state = json.loads(cache_file.read_text(encoding='utf-8'))
            positions = [{'code': c, 'shares': p.get('shares', 0)} for c, p in state.get('positions', {}).items()]
        settings_file = PATHS.get("cache_dir", Path("data/cache")) / "settings.json"
        preference = '均衡配置'
        if settings_file.exists():
            try:
                s = json.loads(settings_file.read_text(encoding='utf-8'))
                preference = s.get('investment_preference', '均衡配置')
            except Exception:
                pass
        return jsonify({'success': True, 'data': {'positions': positions, '偏好': preference}})
    except Exception:
        return jsonify({'success': True, 'data': {'positions': [], '偏好': '均衡配置'}})


# ── AI 综合分析 ─────────────────────────────────────────────────
@ai_bp.route('/comprehensive_analysis', methods=['POST'])
def ai_comprehensive_analysis():
    """综合分析"""
    data = request.get_json(silent=True) or {}
    code = data.get('code', '000001')
    try:
        df = _loader.load_daily(code)
        if df.empty:
            return jsonify({'success': True, 'data': {'analysis': f'{code} 暂无数据'}})
        close = df['close']
        info = f"股票{code} 当前价:{close.iloc[-1]:.2f} MA5:{close.rolling(5).mean().iloc[-1]:.2f} MA20:{close.rolling(20).mean().iloc[-1]:.2f} RSI:{_calc_rsi(close):.1f}"
        client = _get_client()
        resp = client.chat.completions.create(
            model=ai_config.chat_model,
            messages=[
                {"role": "system", "content": "你是量化分析师，综合分析股票的技术面、基本面和市场环境。"},
                {"role": "user", "content": info},
            ]
        )
        return jsonify({'success': True, 'data': {'analysis': resp.choices[0].message.content}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── AI 持仓分析 ─────────────────────────────────────────────────
@ai_bp.route('/position_analysis', methods=['POST'])
def ai_position_analysis():
    """持仓分析"""
    try:
        cache_file = PATHS.get("cache_dir", Path("data/cache")) / "mock_account.json"
        if not cache_file.exists():
            return jsonify({'success': True, 'data': {'analysis': '暂无持仓'}})
        state = json.loads(cache_file.read_text(encoding='utf-8'))
        positions = state.get('positions', {})
        if not positions:
            return jsonify({'success': True, 'data': {'analysis': '暂无持仓'}})

        pos_info = []
        for code, p in positions.items():
            pos_info.append(f"{code}: 持仓{p.get('shares',0)}股 成本{p.get('entry_price',0):.2f}")

        client = _get_client()
        resp = client.chat.completions.create(
            model=ai_config.chat_model,
            messages=[
                {"role": "system", "content": "你是投资顾问，分析以下持仓的健康状况。"},
                {"role": "user", "content": "当前持仓:\n" + "\n".join(pos_info)},
            ]
        )
        return jsonify({'success': True, 'data': {'analysis': resp.choices[0].message.content}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── AI 风险评估 ─────────────────────────────────────────────────
@ai_bp.route('/risk_assessment', methods=['POST'])
def ai_risk_assessment():
    """风险评估"""
    data = request.get_json(silent=True) or {}
    code = data.get('code', '000001')
    try:
        df = _loader.load_daily(code)
        if df.empty:
            return jsonify({'success': True, 'data': {'risk_level': '未知', 'analysis': '无数据'}})
        close = df['close']
        vol = close.pct_change().rolling(20).std().iloc[-1] * 100
        max_dd = ((close - close.cummax()) / close.cummax()).min() * 100
        risk_level = '高' if vol > 3 else ('中' if vol > 1.5 else '低')
        return jsonify({'success': True, 'data': {
            'risk_level': risk_level,
            'volatility': round(vol, 2),
            'max_drawdown': round(max_dd, 2),
            'analysis': f'20日波动率{vol:.1f}%，历史最大回撤{max_dd:.1f}%，风险等级：{risk_level}',
        }})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── AI 选股 ─────────────────────────────────────────────────────
@ai_bp.route('/pick', methods=['POST'])
def ai_pick():
    """AI 选股"""
    data = request.get_json(silent=True) or {}
    prompt = data.get('prompt', '筛选优质A股')
    try:
        symbols = _loader.get_daily_symbols(min_days=60)[:20]
        stock_info = []
        for code in symbols[:15]:
            try:
                df = _loader.load_daily(code)
                if df.empty or len(df) < 5:
                    continue
                close = df['close']
                pct = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100
                stock_info.append(f"{code}: 近5日{pct:+.1f}%")
            except Exception:
                pass

        client = _get_client()
        resp = client.chat.completions.create(
            model=ai_config.chat_model,
            messages=[
                {"role": "system", "content": SELECT_SYSTEM},
                {"role": "user", "content": f"筛选条件: {prompt}\n候选股票:\n" + "\n".join(stock_info)},
            ]
        )
        reply = resp.choices[0].message.content
        match = re.search(r'\{.*\}', reply, re.DOTALL)
        if match:
            result = json.loads(match.group())
            return jsonify({'success': True, 'data': result.get('stocks', []), 'summary': result.get('summary', '')})
        return jsonify({'success': True, 'data': [], 'summary': reply})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── AI 选股 V2 ──────────────────────────────────────────────────
@ai_bp.route('/select_stocks_v2', methods=['POST'])
def ai_select_stocks_v2():
    """AI 选股 V2（增强版）"""
    return ai_select()


# ── AI 每日摘要 ─────────────────────────────────────────────────
@ai_bp.route('/daily_summary', methods=['POST'])
def ai_daily_summary():
    """每日新闻摘要"""
    try:
        import sqlite3
        from config.settings import DB
        with sqlite3.connect(str(DB["quantpro"])) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT title, stock_codes FROM news_raw ORDER BY pub_date DESC LIMIT 10"
            ).fetchall()

        if not rows:
            return jsonify({'success': True, 'data': {'summary': '暂无新闻'}})

        news_text = "\n".join([f"- [{r['stock_codes'] or 'N/A'}] {r['title']}" for r in rows])
        client = _get_client()
        resp = client.chat.completions.create(
            model=ai_config.chat_model,
            messages=[
                {"role": "system", "content": "你是市场分析师，总结今日重要新闻对A股的影响。"},
                {"role": "user", "content": f"今日新闻:\n{news_text}"},
            ]
        )
        return jsonify({'success': True, 'data': {'summary': resp.choices[0].message.content}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 聊天会话管理 ─────────────────────────────────────────────────
def _get_db():
    """获取数据库连接"""
    return sqlite3.connect(str(DB["market"]))


@chat_bp.route('/sessions', methods=['GET'])
def get_sessions():
    """获取会话列表"""
    try:
        with _get_db() as conn:
            conn.row_factory = sqlite3.Row
            sessions = conn.execute(
                "SELECT * FROM chat_sessions ORDER BY updated_at DESC"
            ).fetchall()
            return jsonify({
                'success': True,
                'data': [dict(s) for s in sessions]
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@chat_bp.route('/sessions', methods=['POST'])
def create_session():
    """创建新会话"""
    data = request.get_json(silent=True) or {}
    title = data.get('title', '新对话')
    try:
        with _get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO chat_sessions (title) VALUES (?)",
                (title,)
            )
            session_id = cursor.lastrowid
            conn.commit()
            return jsonify({
                'success': True,
                'data': {'id': session_id, 'title': title}
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@chat_bp.route('/sessions/<int:session_id>', methods=['GET'])
def get_session(session_id):
    """获取单个会话"""
    try:
        with _get_db() as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ?",
                (session_id,)
            ).fetchone()
            if not session:
                return jsonify({'success': False, 'error': '会话不存在'}), 404
            return jsonify({'success': True, 'data': dict(session)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@chat_bp.route('/sessions/<int:session_id>', methods=['DELETE'])
def delete_session(session_id):
    """删除会话"""
    try:
        with _get_db() as conn:
            conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            conn.commit()
            return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@chat_bp.route('/sessions/<int:session_id>/messages', methods=['GET'])
def get_messages(session_id):
    """获取会话消息列表"""
    try:
        with _get_db() as conn:
            conn.row_factory = sqlite3.Row
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at",
                (session_id,)
            ).fetchall()
            return jsonify({
                'success': True,
                'data': [dict(m) for m in messages]
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@chat_bp.route('/sessions/<int:session_id>/messages', methods=['POST'])
def send_message(session_id):
    """发送消息并获取AI回复"""
    data = request.get_json(silent=True) or {}
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'success': False, 'error': '消息不能为空'}), 400

    try:
        with _get_db() as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not session:
                return jsonify({'success': False, 'error': '会话不存在'}), 404

            # 保存用户消息
            conn.execute(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (?, 'user', ?)",
                (session_id, content)
            )
            conn.commit()

            # 获取历史消息
            messages = conn.execute(
                "SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY created_at",
                (session_id,)
            ).fetchall()

            # 调用AI生成回复
            client = _get_client()
            chat_messages = [{"role": "system", "content": CHAT_SYSTEM}]
            for msg in messages:
                chat_messages.append({"role": msg['role'], "content": msg['content']})

            resp = client.chat.completions.create(
                model=ai_config.chat_model,
                messages=chat_messages
            )
            reply = resp.choices[0].message.content

            # 保存AI回复
            conn.execute(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (?, 'assistant', ?)",
                (session_id, reply)
            )
            # 更新会话时间
            conn.execute(
                "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,)
            )
            conn.commit()

            log_ai('chat_session', f'session={session_id} msg={content[:50]}')
            return jsonify({
                'success': True,
                'data': {'reply': reply}
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
