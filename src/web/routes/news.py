"""
新闻 API — RSS 抓取 + DeepSeek 分析
"""

import sqlite3
from datetime import datetime

from flask import Blueprint, request, jsonify

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DB

news_bp = Blueprint('news', __name__, url_prefix='/api/news')


@news_bp.route('/latest')
def latest_news():
    """最新新闻"""
    limit = request.args.get('limit', 20, type=int)
    try:
        with sqlite3.connect(str(DB["quantpro"])) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM news_raw ORDER BY pub_date DESC LIMIT ?", (limit,)
            ).fetchall()
            data = [dict(r) for r in rows]
        return jsonify({'success': True, 'data': data, 'count': len(data)})
    except Exception:
        return jsonify({'success': True, 'data': [], 'count': 0})


@news_bp.route('/list')
def news_list():
    return latest_news()


@news_bp.route('/stock/<code>')
def stock_news(code):
    """个股相关新闻"""
    limit = request.args.get('limit', 10, type=int)
    try:
        with sqlite3.connect(str(DB["quantpro"])) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM news_raw WHERE stock_codes LIKE ? ORDER BY pub_date DESC LIMIT ?",
                (f'%{code}%', limit)
            ).fetchall()
            data = [dict(r) for r in rows]
        return jsonify({'success': True, 'data': data, 'code': code, 'count': len(data)})
    except Exception:
        return jsonify({'success': True, 'data': [], 'code': code, 'count': 0})


@news_bp.route('/trendrader')
def trendrader_news():
    """趋势新闻（兼容旧前端）"""
    return latest_news()


@news_bp.route('/trendrader/keywords')
def trendrader_keywords():
    """热门关键词"""
    try:
        with sqlite3.connect(str(DB["quantpro"])) as conn:
            rows = conn.execute(
                "SELECT stock_codes FROM news_raw WHERE pub_date >= date('now', '-3 days')"
            ).fetchall()

        freq = {}
        for row in rows:
            codes = (row[0] or '').split(',')
            for c in codes:
                c = c.strip()
                if c and len(c) == 6:
                    freq[c] = freq.get(c, 0) + 1

        top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:20]
        return jsonify({'success': True, 'data': [{'code': k, 'count': v} for k, v in top]})
    except Exception:
        return jsonify({'success': True, 'data': []})


@news_bp.route('/trendrader/stocks')
def trendrader_stocks():
    """新闻关联股票"""
    return trendrader_keywords()


@news_bp.route('/trendrader/refresh', methods=['POST'])
def trendrader_refresh():
    """刷新新闻"""
    try:
        from src.news.rss_fetcher import fetch_rss_feeds, save_raw_news
        items = fetch_rss_feeds()
        if not items:
            return jsonify({'success': True, 'message': '未获取到新闻', 'count': 0})
        saved = save_raw_news(items)
        return jsonify({'success': True, 'message': f'抓取了 {len(items)} 条，新增 {saved} 条', 'count': saved})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@news_bp.route('/trendrader/summary', methods=['POST'])
def trendrader_summary():
    """AI 新闻摘要"""
    try:
        from openai import OpenAI
        from config.settings import DEEPSEEK_API_KEY

        with sqlite3.connect(str(DB["quantpro"])) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT title, content, stock_codes FROM news_raw ORDER BY pub_date DESC LIMIT 10"
            ).fetchall()

        if not rows:
            return jsonify({'success': True, 'data': {'summary': '暂无新闻'}})

        news_text = "\n".join([
            f"- [{r['stock_codes'] or 'N/A'}] {r['title']}" for r in rows
        ])

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是市场分析师，简要总结以下新闻对 A 股的影响。"},
                {"role": "user", "content": f"今日重要新闻:\n{news_text}"},
            ]
        )
        return jsonify({'success': True, 'data': {'summary': resp.choices[0].message.content}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@news_bp.route('/analyze', methods=['POST'])
def analyze_news():
    """触发新闻因子分析 — DeepSeek LLM 提取 sentiment/catalyst/urgency 因子"""
    try:
        from src.news.analyzer import analyze_all_pending, aggregate_daily_factors
        limit = request.args.get('limit', 20, type=int)
        factor_count = analyze_all_pending(limit=limit)
        daily_count = aggregate_daily_factors()
        return jsonify({
            'success': True,
            'factor_count': factor_count,
            'daily_factor_count': daily_count,
            'message': f'分析 {factor_count} 条因子，聚合 {daily_count} 条日频因子',
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@news_bp.route('/agent-team', methods=['POST'])
def agent_team_analyze():
    """触发多 Agent 新闻分析 — 5个专业Agent + CIO综合决策"""
    try:
        from src.strategy.agent_team import AgentTeam, get_stock_news_from_db
        codes_str = request.args.get('codes', '')
        days = request.args.get('days', 3, type=int)

        if codes_str:
            stock_codes = [c.strip() for c in codes_str.split(',') if c.strip()]
        else:
            with sqlite3.connect(str(DB["market"])) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT SUBSTR(stock_codes, 1, 6) FROM news "
                    "WHERE stock_codes != '' AND published_at >= date('now', '-1 day') LIMIT 10"
                ).fetchall()
                stock_codes = [r[0] for r in rows if r[0]]

        if not stock_codes:
            return jsonify({'success': True, 'message': '无相关股票新闻', 'decisions': []})

        news_items = get_stock_news_from_db(stock_codes, days=days)
        if not news_items:
            return jsonify({'success': True, 'message': '未找到近期新闻', 'decisions': []})

        team = AgentTeam()
        decisions = team.run(news_items)

        result = []
        for d in decisions:
            result.append({
                'stock_code': d.stock_code,
                'final_score': round(d.final_score, 4),
                'action': d.final_action,
                'confidence': round(d.confidence, 4),
                'risk_summary': d.risk_summary,
                'catalyst_summary': d.catalyst_summary,
                'summary': d.summary,
                'agent_opinions': [
                    {
                        'agent': op.agent_role,
                        'score': round(op.score, 4),
                        'confidence': round(op.confidence, 4),
                        'reasoning': op.reasoning,
                        'risk_flags': op.risk_flags,
                    }
                    for op in d.agent_opinions
                ],
            })

        return jsonify({
            'success': True,
            'news_count': len(news_items),
            'decision_count': len(decisions),
            'decisions': result,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@news_bp.route('/factors/<code>')
def news_factors(code):
    """获取个股新闻因子"""
    try:
        with sqlite3.connect(str(DB["market"])) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM news_factor WHERE stock_code = ? ORDER BY pub_date DESC LIMIT 20",
                (code,)
            ).fetchall()
            factors = [dict(r) for r in rows]

        return jsonify({'success': True, 'code': code, 'factors': factors, 'count': len(factors)})
    except Exception:
        return jsonify({'success': True, 'code': code, 'factors': [], 'count': 0})


@news_bp.route('/daily-factors/<code>')
def daily_factors(code):
    """获取个股日频聚合因子"""
    try:
        with sqlite3.connect(str(DB["market"])) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM news_daily_factor WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 30",
                (code,)
            ).fetchall()
            factors = [dict(r) for r in rows]

        return jsonify({'success': True, 'code': code, 'factors': factors, 'count': len(factors)})
    except Exception:
        return jsonify({'success': True, 'code': code, 'factors': [], 'count': 0})
