"""
新闻因子分析 — 使用 DeepSeek LLM 提取数值因子
"""

import json
import re
import sqlite3
import time
from pathlib import Path

from openai import OpenAI

from config.settings import DB, DEEPSEEK_API_KEY, news_config, ai_config

SYSTEM_PROMPT = """你是一名量化新闻分析师。为每条新闻提取数值因子。

输出 JSON 数组，每条新闻一个对象：
{
  "id": "新闻ID",
  "stock_code": "6位股票代码",
  "sentiment_score": <-1.0到+1.0>,
  "industry_heat": <0.0到1.0>,
  "catalyst_score": <0.0到1.0>,
  "urgency_score": <0.0到1.0>,
  "impact_duration": <1,3,5,10,20>
}

规则：
- sentiment_score: -1=极度看空, 0=中性, +1=极度看多
- industry_heat: 0=无关注, 1=市场极度关注
- catalyst_score: 0=无催化剂, 1=重大催化剂（政策变化、业绩超预期、并购等）
- urgency_score: 0=缓慢发酵, 1=立即影响市场
- impact_duration: 预计影响股价的天数
- stock_code: 如果新闻未提及具体股票，使用 "000000"

只返回有效 JSON，不要 markdown。"""

_POSITIVE_KW = ['利好', '增长', '上涨', '突破', '新高', '盈利', '获批', '中标',
                '涨停', '反弹', '复苏', '超预期', '增持', '回购', '分红', '大涨',
                '强势', '领涨', '翻红', '拉升', '放量', '景气', '订单', '签约']
_NEGATIVE_KW = ['利空', '下跌', '亏损', '违规', '处罚', '退市', '暴跌', '跌停',
                '风险', '减持', '质押', '诉讼', '警示', '退回', '下滑', '大跌',
                '破位', '跳水', '闪崩', '爆雷', '违约', '停产', '召回']
_URGENCY_KW = ['紧急', '突发', '刚刚', '重磅', '急速', '立即', '紧急通知', '速看']
_CATALYST_KW = ['政策', '央行', '国务院', '证监会', '发改委', '并购', '重组',
                '业绩超预期', '中标', '获批', '新药', '突破', '首发', '首发上市']


def _keyword_analyze(items: list[dict]) -> list[dict]:
    """关键词情感分析 fallback（当 LLM 不可用时使用）"""
    factors = []
    for item in items:
        text = f"{item.get('title', '')} {item.get('content', '')}"
        pos = sum(1 for kw in _POSITIVE_KW if kw in text)
        neg = sum(1 for kw in _NEGATIVE_KW if kw in text)
        total_kw = pos + neg
        if total_kw > 0:
            sentiment = (pos - neg) / total_kw
        else:
            sentiment = 0.0

        urgency = min(1.0, sum(1 for kw in _URGENCY_KW if kw in text) / 3.0)
        catalyst = min(1.0, sum(1 for kw in _CATALYST_KW if kw in text) / 3.0)
        heat = min(1.0, total_kw / 5.0)

        codes_str = item.get("stock_codes", "") or ""
        codes = [c.strip() for c in codes_str.split(",") if c.strip() and len(c.strip()) == 6]
        if not codes:
            codes = ["000000"]

        for code in codes:
            factors.append({
                "news_id": item["id"],
                "stock_code": code,
                "pub_date": (item.get("pub_date", "") or "")[:10],
                "source": item.get("source", ""),
                "sentiment_score": round(sentiment, 2),
                "industry_heat": round(heat, 2),
                "catalyst_score": round(catalyst, 2),
                "urgency_score": round(urgency, 2),
                "impact_duration": 3 if catalyst > 0.3 else 1,
            })
    return factors


def _get_client() -> OpenAI:
    return OpenAI(api_key=ai_config.api_key, base_url=ai_config.base_url)


def _parse_llm_response(text: str) -> list[dict]:
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return []


def _build_batch_prompt(items: list[dict]) -> str:
    lines = []
    for item in items:
        lines.append(f"[{item['id']}] 股票:{item['stock_codes'] or '000000'} "
                     f"标题:{item['title']} "
                     f"内容:{(item.get('content') or '')[:300]}")
    return "\n".join(lines)


def analyze_news_batch(items: list[dict], client: OpenAI = None) -> list[dict]:
    """批量分析新闻，返回因子列表"""
    if not items:
        return []

    client = client or _get_client()
    prompt = _build_batch_prompt(items)

    try:
        resp = client.chat.completions.create(
            model=ai_config.pro_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        text = resp.choices[0].message.content.strip()
        factors = _parse_llm_response(text)

        if not factors:
            print(f"  [WARN] LLM 返回无法解析为 JSON (raw: {text[:200]})")
            return []

        id_map = {item["id"]: item for item in items}
        result = []
        unmatched = []
        for f in factors:
            news_id = f.get("id", "")
            if news_id in id_map:
                item = id_map[news_id]
                pub_date = item["pub_date"][:10]
                result.append({
                    "news_id": news_id,
                    "stock_code": f.get("stock_code", "000000"),
                    "pub_date": pub_date,
                    "source": item.get("source", ""),
                    "sentiment_score": float(f.get("sentiment_score", 0)),
                    "industry_heat": float(f.get("industry_heat", 0)),
                    "catalyst_score": float(f.get("catalyst_score", 0)),
                    "urgency_score": float(f.get("urgency_score", 0)),
                    "impact_duration": int(f.get("impact_duration", 1)),
                })
            else:
                unmatched.append(news_id)

        if unmatched:
            print(f"  [WARN] {len(unmatched)} 个因子ID无法匹配 (expected: {list(id_map.keys())[:3]}..., got: {unmatched[:3]})")
        return result
    except Exception as e:
        print(f"  ❌ LLM 分析失败: {e}")
        return []


def analyze_all_pending(batch_size: int = None, limit: int = 0,
                        db_path: Path = None) -> int:
    """分析所有未处理的新闻（同时从 market.news 和 quantpro.news_raw 读取）"""
    batch_size = batch_size or news_config.analyze_batch_size
    db_path = db_path or DB["market"]
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS news_factor (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        news_id TEXT NOT NULL,
        stock_code TEXT NOT NULL,
        pub_date TEXT NOT NULL,
        source TEXT,
        sentiment_score REAL,
        industry_heat REAL,
        catalyst_score REAL,
        urgency_score REAL,
        impact_duration INTEGER,
        analyzed_at TEXT DEFAULT (datetime('now')),
        UNIQUE(news_id, stock_code)
    )''')
    conn.commit()

    pending = []

    query = '''SELECT n.id, n.title, n.content, n.published_at, n.source, n.stock_codes
               FROM news n
               LEFT JOIN news_factor nf ON n.id = nf.news_id AND nf.stock_code != '000000'
               WHERE nf.id IS NULL'''
    try:
        c.execute(query + (' LIMIT ?' if limit else ''), (limit,) if limit else ())
        pending.extend(c.fetchall())
    except Exception as e:
        print(f"  [WARN] market.news 查询失败: {e}")

    analyzed_ids = set(
        row[0] for row in c.execute("SELECT DISTINCT news_id FROM news_factor").fetchall()
    )

    quantpro_path = DB.get("quantpro")
    if quantpro_path and Path(quantpro_path).exists():
        try:
            qp_conn = sqlite3.connect(str(quantpro_path))
            qp_c = qp_conn.cursor()
            qp_query = '''SELECT n.id, n.title, n.content, n.pub_date, n.source, n.stock_codes
                          FROM news_raw n'''
            qp_c.execute(qp_query)
            all_raw = qp_c.fetchall()
            qp_conn.close()

            for row in all_raw:
                if row[0] not in analyzed_ids:
                    pending.append(row)
                    if limit and len(pending) >= limit:
                        break
        except Exception as e:
            print(f"  [WARN] quantpro.news_raw 查询失败: {e}")
    if not pending:
        print("没有待分析的新闻")
        conn.close()
        return 0

    print(f"待分析: {len(pending)} 条新闻")
    conn.close()

    items = []
    for row in pending:
        items.append({
            "id": row[0],
            "title": row[1],
            "content": row[2],
            "pub_date": row[3] or "",
            "source": row[4],
            "stock_codes": row[5],
        })

    client = _get_client()
    total = 0
    llm_failed = False

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        print(f"  分析 {i+1}-{min(i+batch_size, len(items))}/{len(items)}...")

        factors = analyze_news_batch(batch, client)
        if factors:
            _save_factors(factors, db_path)
            total += len(factors)
        else:
            llm_failed = True

        time.sleep(news_config.analyze_rate_limit_seconds)

    if llm_failed and total == 0:
        print("  LLM 分析全部失败，使用关键词情感分析 fallback...")
        factors = _keyword_analyze(items)
        if factors:
            _save_factors(factors, db_path)
            total = len(factors)

    print(f"分析完成: {total} 条因子")
    return total


def _save_factors(factors: list[dict], db_path: Path):
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    for f in factors:
        try:
            c.execute('''INSERT OR IGNORE INTO news_factor
                (news_id, stock_code, pub_date, source, sentiment_score,
                 industry_heat, catalyst_score, urgency_score, impact_duration)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (f["news_id"], f["stock_code"], f["pub_date"], f["source"],
                 f["sentiment_score"], f["industry_heat"], f["catalyst_score"],
                 f["urgency_score"], f["impact_duration"]))
        except Exception:
            pass
    conn.commit()
    conn.close()


def aggregate_daily_factors(db_path: Path = None) -> int:
    """聚合 news_factor 到 news_daily_factor"""
    db_path = db_path or DB["market"]
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS news_daily_factor (
        stock_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        sentiment_avg REAL,
        sentiment_std REAL,
        sentiment_max REAL,
        sentiment_min REAL,
        news_count INTEGER,
        industry_heat_avg REAL,
        catalyst_avg REAL,
        catalyst_max REAL,
        urgency_avg REAL,
        news_momentum REAL,
        sentiment_momentum REAL,
        positive_ratio REAL,
        source_diversity REAL,
        PRIMARY KEY (stock_code, trade_date)
    )''')

    # 获取所有 (stock_code, pub_date) 组合
    groups = c.execute('''SELECT DISTINCT stock_code, pub_date FROM news_factor''').fetchall()
    if not groups:
        print("✅ 没有需要聚合的因子")
        conn.close()
        return 0

    count = 0
    for stock_code, pub_date in groups:
        rows = c.execute('''SELECT sentiment_score, industry_heat, catalyst_score,
                            urgency_score, source FROM news_factor
                            WHERE stock_code = ? AND pub_date = ?''',
                         (stock_code, pub_date)).fetchall()

        if not rows:
            continue

        sentiments = [r[0] for r in rows]
        heats = [r[1] for r in rows]
        catalysts = [r[2] for r in rows]
        urgencies = [r[3] for r in rows]
        sources = [r[4] for r in rows]

        import numpy as np
        sentiment_avg = float(np.mean(sentiments))
        sentiment_std = float(np.std(sentiments)) if len(sentiments) > 1 else 0.0
        sentiment_max = float(np.max(sentiments))
        sentiment_min = float(np.min(sentiments))
        news_count = len(rows)
        industry_heat_avg = float(np.mean(heats))
        catalyst_avg = float(np.mean(catalysts))
        catalyst_max = float(np.max(catalysts))
        urgency_avg = float(np.mean(urgencies))
        positive_ratio = sum(1 for s in sentiments if s > 0.1) / news_count
        source_diversity = len(set(s for s in sources if s)) / max(len(set(s for s in sources if s)), 1)

        # 计算 momentum（需要历史数据）
        news_momentum = _calc_news_momentum(conn, stock_code, pub_date)
        sentiment_momentum = _calc_sentiment_momentum(conn, stock_code, pub_date)

        c.execute('''INSERT OR REPLACE INTO news_daily_factor
            (stock_code, trade_date, sentiment_avg, sentiment_std,
             sentiment_max, sentiment_min, news_count, industry_heat_avg,
             catalyst_avg, catalyst_max, urgency_avg, news_momentum,
             sentiment_momentum, positive_ratio, source_diversity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (stock_code, pub_date, sentiment_avg, sentiment_std,
             sentiment_max, sentiment_min, news_count, industry_heat_avg,
             catalyst_avg, catalyst_max, urgency_avg, news_momentum,
             sentiment_momentum, positive_ratio, source_diversity))
        count += 1

    conn.commit()
    conn.close()
    print(f"✅ 聚合完成: {count} 条日频因子")
    return count


def _calc_news_momentum(conn, stock_code: str, pub_date: str) -> float:
    """计算新闻数量动量: 今日数量 / 7日平均"""
    row = conn.execute('''SELECT AVG(cnt) FROM (
        SELECT COUNT(*) as cnt FROM news_factor
        WHERE stock_code = ? AND pub_date < ? AND pub_date >= date(?, '-7 days')
        GROUP BY pub_date
    )''', (stock_code, pub_date, pub_date)).fetchone()

    avg_7d = row[0] if row and row[0] else 0
    today = conn.execute('''SELECT COUNT(*) FROM news_factor
        WHERE stock_code = ? AND pub_date = ?''',
        (stock_code, pub_date)).fetchone()[0]

    if avg_7d > 0:
        return today / avg_7d
    return 1.0 if today > 0 else 0.0


def _calc_sentiment_momentum(conn, stock_code: str, pub_date: str) -> float:
    """计算情绪动量: 今日情绪 / 3日平均情绪"""
    row = conn.execute('''SELECT AVG(sentiment_score) FROM news_factor
        WHERE stock_code = ? AND pub_date < ? AND pub_date >= date(?, '-3 days')''',
        (stock_code, pub_date, pub_date)).fetchone()

    avg_3d = row[0] if row and row[0] else 0
    today = conn.execute('''SELECT AVG(sentiment_score) FROM news_factor
        WHERE stock_code = ? AND pub_date = ?''',
        (stock_code, pub_date)).fetchone()[0]

    if today is not None and avg_3d != 0:
        return today - avg_3d
    return 0.0
