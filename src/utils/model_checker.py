"""
模型可用性检测 — 验证截面模型是否可用

检查项:
  1. 模型文件是否存在
  2. 模型文件是否可加载（joblib）
  3. 模型日期是否过期（超过 N 天未更新）
  4. 选股结果是否过期
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import PATHS


def check_model_availability() -> dict:
    model_dir = PATHS.get("model_dir", Path("data/models"))
    if isinstance(model_dir, str):
        model_dir = Path(model_dir)

    model_files = sorted(model_dir.glob("cs_model_*.pkl"), reverse=True) if model_dir.exists() else []
    all_model_files = sorted(model_dir.glob("*.pkl"), reverse=True) if model_dir.exists() else []

    if not model_files:
        return {
            "available": False,
            "ready": False,
            "reason": "无截面模型文件，请先运行: python main.py train cs",
            "model_count": len(all_model_files),
            "latest_model": None,
            "model_age_days": None,
            "stale": True,
        }

    latest = model_files[0]
    name_parts = latest.stem.replace("cs_model_", "").split("_")
    model_date_str = name_parts[0] if name_parts else ""

    model_age_days = None
    stale = False
    if model_date_str:
        try:
            model_date = datetime.strptime(model_date_str, "%Y-%m-%d")
            model_age_days = (datetime.now() - model_date).days
            stale = model_age_days > 30
        except ValueError:
            pass

    loadable = False
    load_error = None
    try:
        import joblib
        test_model = joblib.load(latest)
        if hasattr(test_model, "predict") or hasattr(test_model, "predict_proba"):
            loadable = True
        else:
            load_error = "模型缺少 predict 方法"
    except Exception as e:
        load_error = str(e)

    picks_stale = False
    picks_date = None
    picks_file = PATHS.get("cache_dir", Path("data/cache")) / "daily_picks.json"
    if isinstance(picks_file, str):
        picks_file = Path(picks_file)
    if picks_file.exists():
        try:
            picks_data = json.loads(picks_file.read_text(encoding="utf-8"))
            picks_date = picks_data.get("date", "")
            if picks_date:
                today_str = datetime.now().strftime("%Y-%m-%d")
                picks_stale = picks_date != today_str
        except Exception:
            picks_stale = True

    ready = loadable and not stale
    reasons = []
    if not loadable:
        reasons.append(f"模型加载失败: {load_error}")
    if stale:
        reasons.append(f"模型已过期 {model_age_days} 天，建议重新训练")
    if picks_stale:
        reasons.append(f"选股数据过期（{picks_date}）")

    return {
        "available": loadable,
        "ready": ready,
        "reason": "; ".join(reasons) if reasons else "模型就绪",
        "model_count": len(all_model_files),
        "latest_model": latest.name,
        "model_date": model_date_str,
        "model_age_days": model_age_days,
        "stale": stale,
        "loadable": loadable,
        "load_error": load_error,
        "picks_stale": picks_stale,
        "picks_date": picks_date,
    }
