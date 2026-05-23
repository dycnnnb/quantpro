"""
每日选股流水线
模型打分 → 新闻 Agent 分析 → 综合 → Top 20 + 换手率控制
"""

import json
import joblib
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config.settings import DB, PATHS, DEEPSEEK_API_KEY
from src.data.loader import DataLoader
from src.strategy.agent_team import AgentTeam, TeamDecision, get_stock_news_from_db


# ── 配置 ────────────────────────────────────────────────────────────
TOP_N = 20              # 最终选股数量
MAX_NEW_PICKS = 3       # 每日最多新增股票（极低换手）
MIN_HOLD_DAYS = 5       # 持仓最少天数（防止频繁交易）
MODEL_SCORE_WEIGHT = 0.6   # 模型打分权重
NEWS_SCORE_WEIGHT = 0.4    # 新闻打分权重
SCORE_THRESHOLD = 0.3      # 最低综合得分
SCORE_DROP_THRESHOLD = -0.15  # 跌幅超过此值才考虑替换


class DailyPickPipeline:
    """每日选股流水线"""

    def __init__(self, model_score_weight=MODEL_SCORE_WEIGHT, news_score_weight=NEWS_SCORE_WEIGHT):
        self.loader = DataLoader()
        self.today = datetime.now().strftime('%Y-%m-%d')
        self.picks_file = PATHS["cache_dir"] / "daily_picks.json"
        self.model = None
        self.model_score_weight = model_score_weight
        self.news_score_weight = news_score_weight

    def _load_model(self):
        """加载截面模型"""
        model_dir = PATHS["model_dir"]
        # Find latest cs_model
        models = sorted(model_dir.glob("cs_model_*.pkl"), reverse=True)
        if not models:
            raise FileNotFoundError("No cross-sectional model found. Run: python main.py train cs")

        print(f"Loading model: {models[0].name}")
        self.model = joblib.load(models[0])
        return self.model

    def _load_yesterday_picks(self) -> Dict[str, dict]:
        """加载昨日选股结果"""
        if self.picks_file.exists():
            try:
                data = json.loads(self.picks_file.read_text(encoding='utf-8'))
                if data.get('date') == self.today:
                    return {}  # 今天已经选过了
                return {p['code']: p for p in data.get('picks', [])}
            except Exception:
                pass
        return {}

    def _save_picks(self, picks: list, model_scores: dict, news_scores: dict):
        """保存选股结果"""
        data = {
            'date': self.today,
            'timestamp': datetime.now().isoformat(),
            'picks': picks,
            'model_scores': model_scores,
            'news_scores': news_scores,
        }
        self.picks_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    def _get_model_scores(self) -> Dict[str, float]:
        """用截面模型对所有股票打分"""
        print("\n--- Step 1: 模型打分 ---")

        if self.model is None:
            self._load_model()

        # Get stocks with enough minute data
        symbols = self.loader.get_available_symbols(min_bars=1000)
        if not symbols:
            print("No symbols with enough minute data")
            return {}

        print(f"Stocks with minute data: {len(symbols)}")

        # Load recent minute data
        start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        end = datetime.now().strftime('%Y-%m-%d')

        multi_df = self.loader.load_multi_minute(symbols, start, end, freq="5min")
        if multi_df.empty:
            print("No minute data loaded")
            return {}

        print(f"Minute data: {len(multi_df):,} rows, {multi_df.index.get_level_values('code').nunique()} stocks")

        # Build features
        from src.features.cross_sectional import build_cross_sectional_features
        X_all = build_cross_sectional_features(multi_df)

        # Get latest datetime for each stock
        latest_dt = X_all.index.get_level_values('datetime').max()
        print(f"Latest datetime: {latest_dt}")

        # Predict scores
        scores_df = self.model.predict(X_all)

        # Extract latest scores per stock
        model_scores = {}
        for code in X_all.index.get_level_values('code').unique():
            try:
                code_scores = scores_df.xs(code, level='code')
                if not code_scores.empty:
                    latest_score = code_scores['buy_score'].iloc[-1]
                    model_scores[code] = float(latest_score)
            except Exception:
                pass

        print(f"Model scores: {len(model_scores)} stocks")
        # Show top 10
        sorted_scores = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
        print("Top 10 by model score:")
        for code, score in sorted_scores[:10]:
            print(f"  {code}: {score:.4f}")

        return model_scores

    def _get_news_scores(self, stock_codes: list) -> Dict[str, float]:
        """用 Agent 团队分析新闻，返回新闻打分"""
        print(f"\n--- Step 2: 新闻 Agent 分析 ({len(stock_codes)} stocks) ---")

        if not DEEPSEEK_API_KEY:
            print("No DeepSeek API key, skipping news analysis")
            return {}

        # Get recent news for these stocks
        news_items = get_stock_news_from_db(stock_codes, days=3)
        if not news_items:
            print("No recent news found")
            return {}

        print(f"Found {len(news_items)} news articles")

        # Run agent team
        team = AgentTeam()
        decisions = team.run(news_items)

        # Convert decisions to scores
        news_scores = {}
        for dec in decisions:
            news_scores[dec.stock_code] = dec.final_score

        print(f"News scores: {len(news_scores)} stocks")
        return news_scores

    def _combine_scores(self, model_scores: Dict[str, float],
                        news_scores: Dict[str, float]) -> List[dict]:
        """综合模型和新闻打分"""
        print(f"\n--- Step 3: 综合打分 ---")

        all_codes = set(model_scores.keys()) | set(news_scores.keys())
        combined = []

        for code in all_codes:
            m_score = model_scores.get(code, 0.0)
            n_score = news_scores.get(code, 0.0)

            # Weighted combination
            final = m_score * self.model_score_weight + n_score * self.news_score_weight

            combined.append({
                'code': code,
                'model_score': m_score,
                'news_score': n_score,
                'final_score': final,
            })

        # Sort by final score
        combined.sort(key=lambda x: x['final_score'], reverse=True)

        print(f"Combined: {len(combined)} stocks")
        print("Top 20 by combined score:")
        for i, s in enumerate(combined[:20]):
            print(f"  {i+1:2d}. {s['code']}: {s['final_score']:+.4f} (model={s['model_score']:+.4f}, news={s['news_score']:+.4f})")

        return combined

    def _apply_turnover_control(self, combined: List[dict],
                                 yesterday_picks: Dict[str, dict]) -> List[dict]:
        """换手率控制：极低换手策略 — 默认保留所有持仓，只替换大幅下跌的"""
        print(f"\n--- Step 4: 换手率控制 ---")

        if not yesterday_picks:
            print("No yesterday picks, using all new picks")
            return combined[:TOP_N]

        yesterday_codes = set(yesterday_picks.keys())
        today_map = {s['code']: s for s in combined}

        # 策略：保留所有昨日持仓，除非分数大幅下跌
        keep = []
        force_drop = []
        for code in yesterday_codes:
            if code in today_map:
                y_score = yesterday_picks[code].get('final_score', 0)
                t_score = today_map[code].get('final_score', 0)
                drop = t_score - y_score
                if drop < SCORE_DROP_THRESHOLD:
                    # 分数大幅下跌，标记为可替换
                    force_drop.append((code, y_score, t_score, drop))
                else:
                    keep.append(today_map[code])
            else:
                # 今日不在候选中，但仍保留（不轻易丢弃）
                keep.append(yesterday_picks[code])

        # 如果有被替换的仓位，用最高分的新股补入
        n_vacant = len(force_drop)
        n_new = min(MAX_NEW_PICKS, n_vacant)

        new_picks = []
        if n_new > 0:
            kept_codes = {s['code'] for s in keep}
            for s in combined:
                if s['code'] not in yesterday_codes and s['code'] not in kept_codes:
                    if len(new_picks) < n_new:
                        new_picks.append(s)

        final = keep + new_picks

        # 确保不超过 TOP_N
        final = final[:TOP_N]

        # Report
        new_codes = {s['code'] for s in final} - yesterday_codes
        dropped_codes = {code for code, _, _, _ in force_drop}
        turnover = len(new_codes) / max(len(yesterday_codes), 1)

        print(f"  Yesterday:    {len(yesterday_codes)} stocks")
        print(f"  Retained:     {len(keep)} stocks")
        print(f"  Force-dropped: {len(dropped_codes)} (score drop > {SCORE_DROP_THRESHOLD})")
        print(f"  New entries:  {len(new_codes)} stocks")
        print(f"  Turnover:     {turnover:.1%}")

        if dropped_codes:
            print(f"  Dropped: {', '.join(sorted(dropped_codes)[:10])}")
        if new_codes:
            print(f"  Added:   {', '.join(sorted(new_codes)[:10])}")

        return final

    def run(self) -> dict:
        """执行完整选股流水线"""
        print(f"\n{'='*60}")
        print(f"  每日选股流水线 — {self.today}")
        print(f"{'='*60}")

        start_time = time.time()

        # Load yesterday's picks
        yesterday_picks = self._load_yesterday_picks()
        if yesterday_picks:
            print(f"Yesterday picks: {len(yesterday_picks)} stocks")

        # Step 1: Model scoring
        model_scores = self._get_model_scores()
        if not model_scores:
            return {'success': False, 'error': 'No model scores'}

        # Step 2: Get top candidates for news analysis
        sorted_by_model = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
        top_candidates = [code for code, _ in sorted_by_model[:30]]  # Top 30 for news

        # Step 3: News agent analysis
        news_scores = self._get_news_scores(top_candidates)

        # Step 4: Combine scores
        combined = self._combine_scores(model_scores, news_scores)

        # Step 5: Turnover control
        final_picks = self._apply_turnover_control(combined, yesterday_picks)

        # Save results
        self._save_picks(final_picks, model_scores, news_scores)

        elapsed = time.time() - start_time

        # Summary
        print(f"\n{'='*60}")
        print(f"  最终选股结果 — Top {len(final_picks)}")
        print(f"{'='*60}")
        for i, s in enumerate(final_picks):
            print(f"  {i+1:2d}. {s['code']}: {s['final_score']:+.4f}")

        print(f"\n  耗时: {elapsed:.1f}s")
        print(f"  保存: {self.picks_file}")

        return {
            'success': True,
            'date': self.today,
            'picks': final_picks,
            'model_scores': model_scores,
            'news_scores': news_scores,
            'elapsed': elapsed,
        }


# ── CLI 入口 ────────────────────────────────────────────────────────

def run_daily_pick():
    """运行每日选股"""
    pipeline = DailyPickPipeline()
    return pipeline.run()


if __name__ == '__main__':
    run_daily_pick()
