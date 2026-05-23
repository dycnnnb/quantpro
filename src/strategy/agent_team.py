"""
多 Agent 新闻分析团队 — 量化投资团队模式
6 个专业 Agent + 1 个 CIO 综合决策
"""

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from openai import OpenAI

from config.settings import DB, ai_config

# DeepSeek V4 Pro for serious news analysis
NEWS_MODEL = ai_config.pro_model

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=ai_config.api_key, base_url=ai_config.base_url)
    return _client


@dataclass
class AgentOpinion:
    agent_name: str
    agent_role: str
    stock_code: str
    score: float          # -1.0 (极度看空) ~ +1.0 (极度看多)
    confidence: float     # 0.0 ~ 1.0
    reasoning: str        # 简要推理
    risk_flags: List[str] = field(default_factory=list)


@dataclass
class TeamDecision:
    stock_code: str
    final_score: float
    final_action: str     # "strong_buy", "buy", "hold", "sell", "strong_sell"
    confidence: float
    agent_opinions: List[AgentOpinion]
    risk_summary: str
    catalyst_summary: str
    summary: str


# ── Agent 定义 ──────────────────────────────────────────────────────

MACRO_ANALYST_PROMPT = """你是一名宏观分析师，专注分析宏观经济政策、央行操作、财政政策、国际贸易对 A 股的影响。

分析以下新闻，评估对 A 股市场的宏观影响。

新闻列表：
{news_text}

对每条相关股票，输出 JSON 数组：
[{{"stock_code": "6位代码", "score": <-1~+1>, "confidence": <0~1>, "reasoning": "简要理由"}}]

规则：
- score: 宏观利好 +0.1~+0.8, 宏观利空 -0.1~-0.8, 中性附近 0
- confidence: 证据充分 0.7~1.0, 推测性 0.3~0.6
- 只输出 JSON，不要 markdown"""


SECTOR_ANALYST_PROMPT = """你是一名行业分析师，专注分析行业轮动、产业链趋势、板块景气度。

分析以下新闻，评估行业和板块层面的影响。

新闻列表：
{news_text}

对每条相关股票，输出 JSON 数组：
[{{"stock_code": "6位代码", "score": <-1~+1>, "confidence": <0~1>, "reasoning": "简要理由"}}]

规则：
- score: 行业景气向上 +0.1~+0.7, 行业下行 -0.1~-0.7
- confidence: 产业链确认 0.6~1.0, 单一信号 0.3~0.5
- 只输出 JSON，不要 markdown"""


TECHNICAL_ANALYST_PROMPT = """你是一名技术分析师，从新闻中提取技术面信号：量价异动、资金流向、主力动向。

分析以下新闻，评估技术面信号。

新闻列表：
{news_text}

对每条相关股票，输出 JSON 数组：
[{{"stock_code": "6位代码", "score": <-1~+1>, "confidence": <0~1>, "reasoning": "简要理由"}}]

规则：
- score: 资金流入/突破信号 +0.1~+0.6, 资金流出/破位信号 -0.1~-0.6
- confidence: 多信号共振 0.6~1.0, 单一信号 0.3~0.5
- 只输出 JSON，不要 markdown"""


SENTIMENT_ANALYST_PROMPT = """你是一名市场情绪分析师，分析市场情绪、散户情绪、社交媒体热度、恐慌贪婪指标。

分析以下新闻，评估市场情绪面。

新闻列表：
{news_text}

对每条相关股票，输出 JSON 数组：
[{{"stock_code": "6位代码", "score": <-1~+1>, "confidence": <0~1>, "reasoning": "简要理由"}}]

规则：
- score: 情绪乐观/热度上升 +0.1~+0.6, 恐慌/利空传闻 -0.1~-0.6
- confidence: 多源确认 0.6~1.0, 单一来源 0.3~0.5
- 只输出 JSON，不要 markdown"""


RISK_MANAGER_PROMPT = """你是一名风控经理，专注识别风险事件：财务造假、监管处罚、大股东减持、诉讼、退市风险。

分析以下新闻，识别潜在风险。

新闻列表：
{news_text}

对每条相关股票，输出 JSON 数组：
[{{"stock_code": "6位代码", "score": <-1~+1>, "confidence": <0~1>, "reasoning": "简要理由", "risk_flags": ["风险标签1","风险标签2"]}}]

规则：
- score: 高风险 -0.3~-1.0, 低风险 +0.1~+0.3（风控视角，低风险=正面）
- confidence: 实质风险 0.7~1.0, 潜在风险 0.3~0.6
- risk_flags: 使用 ["财务风险","监管风险","减持风险","诉讼风险","退市风险","流动性风险","估值风险"]
- 只输出 JSON，不要 markdown"""


CIO_PROMPT = """你是首席投资官(CIO)，负责综合各分析师意见做出最终投资决策。

各分析师意见：
{agent_views}

请综合评估，对每只股票给出最终决策。

输出 JSON 数组：
[{{"stock_code": "6位代码", "final_score": <-1~+1>, "action": "strong_buy/buy/hold/sell/strong_sell", "confidence": <0~1>, "risk_summary": "风险总结", "catalyst_summary": "催化剂总结", "summary": "综合建议"}}]

规则：
- final_score 综合各分析师加权：宏观(15%) + 行业(25%) + 技术(20%) + 情绪(15%) + 风控(25%，风控权重高因安全第一)
- action: final_score>0.5 strong_buy, 0.2~0.5 buy, -0.2~0.2 hold, -0.5~-0.2 sell, <-0.5 strong_sell
- confidence: 取各分析师共识度，分歧大则降低 confidence
- 风控一票否决：如果风控 score < -0.5，强制降级为 sell 或 hold
- 只输出 JSON，不要 markdown"""


# ── Agent Team ──────────────────────────────────────────────────────

class AgentTeam:
    """多 Agent 新闻分析团队"""

    AGENTS = [
        ("macro_analyst", "宏观分析师", MACRO_ANALYST_PROMPT, 0.15),
        ("sector_analyst", "行业分析师", SECTOR_ANALYST_PROMPT, 0.25),
        ("technical_analyst", "技术分析师", TECHNICAL_ANALYST_PROMPT, 0.20),
        ("sentiment_analyst", "情绪分析师", SENTIMENT_ANALYST_PROMPT, 0.15),
        ("risk_manager", "风控经理", RISK_MANAGER_PROMPT, 0.25),
    ]

    def __init__(self):
        self.client = _get_client()

    def _call_llm(self, prompt: str, temperature: float = 0.1) -> str:
        """调用 DeepSeek V4 Pro"""
        resp = self.client.chat.completions.create(
            model=NEWS_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=2000,
        )
        return resp.choices[0].message.content.strip()

    def _parse_json(self, text: str) -> list:
        """从 LLM 响应中提取 JSON 数组"""
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return []

    def _format_news(self, news_items: list) -> str:
        """格式化新闻为分析文本"""
        lines = []
        for i, item in enumerate(news_items, 1):
            title = item.get("title", "")
            content = (item.get("content") or "")[:500]
            codes = item.get("stock_codes") or "000000"
            source = item.get("source", "")
            lines.append(f"[{i}] 股票:{codes} | 来源:{source}\n标题:{title}\n内容:{content}")
        return "\n\n".join(lines)

    def analyze_news(self, news_items: list) -> List[AgentOpinion]:
        """让所有 Agent 分析新闻，返回所有意见"""
        if not news_items:
            return []

        news_text = self._format_news(news_items)
        all_opinions = []

        for agent_name, agent_role, prompt_template, weight in self.AGENTS:
            print(f"  [Agent] {agent_role} 分析中...")
            prompt = prompt_template.format(news_text=news_text)

            try:
                response = self._call_llm(prompt)
                raw_opinions = self._parse_json(response)

                for op in raw_opinions:
                    opinion = AgentOpinion(
                        agent_name=agent_name,
                        agent_role=agent_role,
                        stock_code=op.get("stock_code", "000000"),
                        score=float(op.get("score", 0)),
                        confidence=float(op.get("confidence", 0.5)),
                        reasoning=op.get("reasoning", ""),
                        risk_flags=op.get("risk_flags", []),
                    )
                    all_opinions.append(opinion)
                print(f"    -> {len(raw_opinions)} 条意见")
            except Exception as e:
                print(f"    [FAIL] {agent_role}: {e}")

            time.sleep(0.5)  # rate limit

        return all_opinions

    def _aggregate_opinions(self, opinions: List[AgentOpinion]) -> Dict[str, List[AgentOpinion]]:
        """按股票代码聚合意见"""
        grouped = {}
        for op in opinions:
            if op.stock_code not in grouped:
                grouped[op.stock_code] = []
            grouped[op.stock_code].append(op)
        return grouped

    def _get_weight(self, agent_name: str) -> float:
        """获取 agent 权重"""
        for name, _, _, weight in self.AGENTS:
            if name == agent_name:
                return weight
        return 0.0

    def make_decisions(self, opinions: List[AgentOpinion]) -> List[TeamDecision]:
        """CIO 综合各 Agent 意见，做出最终决策"""
        if not opinions:
            return []

        grouped = self._aggregate_opinions(opinions)

        # Build CIO prompt with agent views
        agent_views = []
        for code, ops in grouped.items():
            views = []
            for op in ops:
                views.append(f"  {op.agent_role}: score={op.score:+.2f} conf={op.confidence:.2f} - {op.reasoning}")
                if op.risk_flags:
                    views.append(f"    风险标签: {', '.join(op.risk_flags)}")
            agent_views.append(f"股票 {code}:\n" + "\n".join(views))

        cio_prompt = CIO_PROMPT.format(agent_views="\n\n".join(agent_views))

        print(f"  [Agent] CIO 综合决策中...")
        try:
            response = self._call_llm(cio_prompt, temperature=0.05)
            raw_decisions = self._parse_json(response)
        except Exception as e:
            print(f"    [FAIL] CIO: {e}")
            raw_decisions = []

        # Parse CIO decisions
        decisions = []
        for dec in raw_decisions:
            code = dec.get("stock_code", "")
            agent_ops = grouped.get(code, [])

            decision = TeamDecision(
                stock_code=code,
                final_score=float(dec.get("final_score", 0)),
                final_action=dec.get("action", "hold"),
                confidence=float(dec.get("confidence", 0.5)),
                agent_opinions=agent_ops,
                risk_summary=dec.get("risk_summary", ""),
                catalyst_summary=dec.get("catalyst_summary", ""),
                summary=dec.get("summary", ""),
            )
            decisions.append(decision)

        # For stocks not in CIO output, create default hold decisions
        for code, ops in grouped.items():
            if not any(d.stock_code == code for d in decisions):
                # Weighted average score
                total_w = sum(self._get_weight(op.agent_name) * op.confidence for op in ops)
                weighted_score = sum(op.score * self._get_weight(op.agent_name) * op.confidence for op in ops) / max(total_w, 1e-8)
                decisions.append(TeamDecision(
                    stock_code=code,
                    final_score=weighted_score,
                    final_action="hold",
                    confidence=0.3,
                    agent_opinions=ops,
                    risk_summary="",
                    catalyst_summary="",
                    summary="CIO 未评估，默认持有",
                ))

        return decisions

    def run(self, news_items: list) -> List[TeamDecision]:
        """完整流程：Agent 分析 → CIO 决策"""
        print(f"\n{'='*60}")
        print(f"  多 Agent 新闻分析团队 — {len(news_items)} 条新闻")
        print(f"{'='*60}")

        opinions = self.analyze_news(news_items)
        print(f"\n  共 {len(opinions)} 条 Agent 意见")

        decisions = self.make_decisions(opinions)
        print(f"  共 {len(decisions)} 条最终决策")

        for d in decisions:
            emoji = {"strong_buy": "++", "buy": "+", "hold": "=", "sell": "-", "strong_sell": "--"}
            print(f"  {d.stock_code}: {d.final_score:+.3f} [{emoji.get(d.final_action, '?')}] conf={d.confidence:.2f} | {d.summary[:60]}")

        return decisions


# ── 便捷函数 ────────────────────────────────────────────────────────

def analyze_news_for_stocks(news_items: list) -> List[TeamDecision]:
    """一步到位：分析新闻并返回团队决策"""
    team = AgentTeam()
    return team.run(news_items)


def get_stock_news_from_db(stock_codes: list, days: int = 3,
                           db_path: str = None) -> list:
    """从数据库获取指定股票的近期新闻"""
    db_path = db_path or str(DB["market"])
    conn = sqlite3.connect(db_path)

    items = []
    for code in stock_codes:
        rows = conn.execute('''SELECT id, title, content, published_at, source, stock_codes
                               FROM news
                               WHERE stock_codes LIKE ? AND published_at >= date('now', ?)
                               ORDER BY published_at DESC LIMIT 10''',
                            (f'%{code}%', f'-{days} days')).fetchall()
        for r in rows:
            items.append({
                "id": r[0], "title": r[1], "content": r[2],
                "pub_date": r[3], "source": r[4], "stock_codes": r[5],
            })

    conn.close()
    # Deduplicate
    seen = set()
    unique = []
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)
    return unique
