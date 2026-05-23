"""
模型训练 API — 滚动训练触发/状态/报告/实时日志
"""

import io
import sys
import json
import threading
import traceback
import importlib.util
from pathlib import Path
from datetime import datetime

from flask import Blueprint, jsonify, request

from config.settings import DB, PATHS

train_bp = Blueprint("train_bp", __name__, url_prefix="/api/train")

MODEL_DIR = Path(PATHS["model_dir"])
_train_status = {
    "running": False,
    "started_at": None,
    "config": None,
    "log": [],
    "error": None,
}
_train_lock = threading.Lock()


def _load_rolling_train():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "rolling_train.py"
    spec = importlib.util.spec_from_file_location("rolling_train", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.rolling_train


class _LogCapture(io.StringIO):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self._buffer = ""

    def write(self, text):
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._callback(line)
        return len(text)

    def flush(self):
        pass


@train_bp.route("/start", methods=["POST"])
def start_training():
    with _train_lock:
        if _train_status["running"]:
            return jsonify({"success": False, "error": "训练正在进行中"}), 409

    data = request.get_json(silent=True) or {}
    use_gpu = data.get("gpu", True)
    use_alpha158 = data.get("alpha158", True)
    mode = data.get("mode", "classification")
    train_days = data.get("train_days", 500)
    valid_days = data.get("valid_days", 60)
    step_days = data.get("step_days", 60)
    forward_window = data.get("forward", 10)
    top_pct = data.get("top_pct", 0.15)
    freq = data.get("freq", "daily")

    config = {
        "gpu": use_gpu,
        "alpha158": use_alpha158,
        "mode": mode,
        "train_days": train_days,
        "valid_days": valid_days,
        "step_days": step_days,
        "forward": forward_window,
        "top_pct": top_pct,
        "freq": freq,
    }

    def _append_log(*args, **kwargs):
        text = " ".join(str(a) for a in args)
        if not text.strip():
            text = ""
        with _train_lock:
            _train_status["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
        print(text, flush=True)

    def _run():
        with _train_lock:
            _train_status["running"] = True
            _train_status["started_at"] = datetime.now().isoformat()
            _train_status["config"] = config
            _train_status["log"] = []
            _train_status["error"] = None

        try:
            _append_log("正在加载训练模块...")
            rolling_train_fn = _load_rolling_train()
            _append_log("训练模块加载成功，开始训练...")

            rolling_train_fn(
                use_gpu=use_gpu,
                train_days=train_days,
                valid_days=valid_days,
                step_days=step_days,
                forward_window=forward_window,
                top_pct=top_pct,
                mode=mode,
                use_alpha158=use_alpha158,
                log_fn=_append_log,
                freq=freq,
            )
            _append_log("✅ 训练完成!")
        except Exception as e:
            err_msg = f"❌ 训练失败: {str(e)}"
            _append_log(err_msg)
            tb = traceback.format_exc()
            for line in tb.strip().split("\n"):
                _append_log(line)
            with _train_lock:
                _train_status["error"] = str(e)
        finally:
            with _train_lock:
                _train_status["running"] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return jsonify({"success": True, "config": config})


@train_bp.route("/status", methods=["GET"])
def training_status():
    with _train_lock:
        return jsonify({
            "success": True,
            "running": _train_status["running"],
            "started_at": _train_status["started_at"],
            "config": _train_status["config"],
            "error": _train_status["error"],
            "log_count": len(_train_status["log"]),
        })


@train_bp.route("/logs", methods=["GET"])
def training_logs():
    after = request.args.get("after", 0, type=int)
    with _train_lock:
        logs = _train_status["log"][after:]
        return jsonify({
            "success": True,
            "running": _train_status["running"],
            "error": _train_status["error"],
            "logs": logs,
            "total": len(_train_status["log"]),
        })


@train_bp.route("/reports", methods=["GET"])
def list_reports():
    if not MODEL_DIR.exists():
        return jsonify({"success": True, "reports": []})

    reports = []
    for f in sorted(MODEL_DIR.glob("rolling_report_*.json"), reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                r = json.load(fh)
            reports.append({
                "file": f.name,
                "timestamp": r.get("timestamp", ""),
                "mode": r.get("mode", ""),
                "alpha158": r.get("alpha158", False),
                "gpu": r.get("gpu", False),
                "n_features": r.get("n_features", 0),
                "best_config": r.get("best_config", ""),
                "best_score": r.get("best_score", 0),
                "n_folds": len(r.get("fold_results", [])),
            })
        except Exception:
            continue

    return jsonify({"success": True, "reports": reports})


@train_bp.route("/report/<filename>", methods=["GET"])
def get_report(filename):
    path = MODEL_DIR / filename
    if not path.exists():
        return jsonify({"success": False, "error": "报告不存在"}), 404

    with open(path, "r", encoding="utf-8") as f:
        report = json.load(f)

    return jsonify({"success": True, "report": report})


@train_bp.route("/models", methods=["GET"])
def list_models():
    if not MODEL_DIR.exists():
        return jsonify({"success": True, "models": []})

    models = []
    for f in sorted(MODEL_DIR.glob("*.pkl"), reverse=True):
        models.append({
            "file": f.name,
            "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })

    return jsonify({"success": True, "models": models})


@train_bp.route("/factors", methods=["GET"])
def list_factors():
    from src.features.qlib_alpha import Alpha158Builder

    builder = Alpha158Builder()
    windows = builder.DEFAULT_WINDOWS

    base_factors = [
        ("KMID", "收盘价在当日价格区间位置"),
        ("KLEN", "日内振幅比"),
        ("ROC", "N日收益率"),
        ("MA", "N日均线偏离度"),
        ("STD", "N日波动率"),
        ("VROC", "N日量变化率"),
        ("VMA", "N日均量比"),
        ("VSTD", "N日量波动率"),
        ("WVMA", "加权成交量波动率"),
        ("VSUMP", "N日正向量能累计"),
        ("CORR", "N日价量相关性"),
        ("CORD", "滞后价量相关性"),
        ("CNTP", "N日上涨天数占比"),
        ("CNTN", "N日下跌天数占比"),
        ("CNTD", "涨跌天数差"),
        ("SUMP", "N日正向收益累计"),
        ("SUMN", "N日负向收益累计"),
        ("SUMD", "正负收益差"),
        ("IMAX", "N日内最高价位置比"),
        ("IMIN", "N日内最低价位置比"),
        ("IMXD", "高低价位置差"),
        ("BETA", "N日Beta系数"),
    ]

    alpha158_factors = []
    for name, desc in base_factors:
        for w in windows:
            alpha158_factors.append({
                "name": f"{name}_{w}",
                "category": name,
                "window": w,
                "description": desc,
            })

    custom_factors = [
        {"name": "price_position", "category": "custom", "window": 60, "description": "60日价格位置"},
        {"name": "trend_strength", "category": "custom", "window": 60, "description": "MA5/MA60趋势强度"},
        {"name": "reversal", "category": "custom", "window": 20, "description": "20日反转因子"},
        {"name": "dist_low", "category": "custom", "window": 20, "description": "距20日低点距离"},
        {"name": "volatility", "category": "custom", "window": 20, "description": "20日波动率"},
        {"name": "volume_ratio", "category": "custom", "window": 20, "description": "成交量比率"},
        {"name": "momentum_5", "category": "custom", "window": 5, "description": "5日动量"},
        {"name": "momentum_20", "category": "custom", "window": 20, "description": "20日动量"},
        {"name": "momentum_60", "category": "custom", "window": 60, "description": "60日动量"},
        {"name": "vwap_dev", "category": "custom", "window": 20, "description": "VWAP偏离"},
        {"name": "range_ratio", "category": "custom", "window": 20, "description": "振幅比"},
        {"name": "vol_shrink", "category": "custom", "window": 60, "description": "缩量因子"},
        {"name": "turnover_proxy", "category": "custom", "window": 10, "description": "换手代理"},
        {"name": "skewness", "category": "custom", "window": 20, "description": "偏度"},
        {"name": "kurtosis", "category": "custom", "window": 20, "description": "峰度"},
    ]

    return jsonify({
        "success": True,
        "alpha158_count": len(alpha158_factors),
        "custom_count": len(custom_factors),
        "total_count": len(alpha158_factors) + len(custom_factors) + 5,
        "alpha158": alpha158_factors,
        "custom": custom_factors,
        "raw_ohlcv": [
            {"name": "OPEN", "description": "开盘价/收盘价"},
            {"name": "HIGH", "description": "最高价/收盘价"},
            {"name": "LOW", "description": "最低价/收盘价"},
            {"name": "CLOSE", "description": "收盘价标准化(=1)"},
            {"name": "VOLUME", "description": "成交量/120日均量"},
        ],
    })
