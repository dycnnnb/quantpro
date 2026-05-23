from __future__ import annotations

import argparse
import json
import logging
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import label_binarize

warnings.filterwarnings("ignore")

from lightgbm import LGBMClassifier

from config.settings import PATHS, DB
from src.data.loader import DataLoader
from src.features.cs_features import (
    ALL_FEATURES, build_features, zscore_cross_section,
)

CONFIG: Dict = {
    "start_date": "2020-01-01",
    "end_date": "2024-12-31",
    "label_forward_days": 5,
    "label_buy_pct": 0.15,
    "label_sell_pct": 0.15,
    "min_list_days": 60,
    "filter_st": True,
    "filter_limit_up": True,
    "limit_threshold": 0.095,
    "train_days": 500,
    "valid_days": 60,
    "step_days": 30,
    "min_train_samples": 50_000,
    "lgbm_params": {
        "objective": "multiclass",
        "num_class": 3,
        "n_estimators": 500,
        "learning_rate": 0.05,
        "num_leaves": 63,
        "max_depth": -1,
        "min_child_samples": 50,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "lambda_l1": 0.1,
        "lambda_l2": 0.1,
        "class_weight": "balanced",
        "verbose": -1,
        "n_jobs": -1,
        "random_state": 42,
    },
    "early_stopping_rounds": 50,
    "feature_cols": ALL_FEATURES,
    "zscore_clip": 3.0,
    "model_name_prefix": "cs_lgbm",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class DataPreparer:

    def __init__(self, cfg: Dict):
        self.cfg = cfg
        self.dl = DataLoader()

    def load_and_prepare(self) -> pd.DataFrame:
        logger.info("加载全 A 股日线数据 ...")
        symbols = self.dl.get_daily_symbols(min_days=self.cfg["min_list_days"])
        logger.info("有效标的数: %d", len(symbols))

        raw = self.dl.load_multi_daily(
            symbols,
            self.cfg["start_date"],
            self._shift_date(self.cfg["end_date"], self.cfg["label_forward_days"] + 5),
        )
        logger.info("原始数据: %d 行", len(raw))

        raw = raw.reset_index()
        if "symbol" in raw.columns and "code" not in raw.columns:
            raw = raw.rename(columns={"symbol": "code"})
        if "date" in raw.index.names and "date" in raw.columns:
            raw = raw.drop(columns=["date"])

        logger.info("构建特征 ...")
        df = build_features(raw)

        logger.info("构建标签 ...")
        df = self._build_labels(df)

        logger.info("过滤样本 ...")
        df = self._filter_samples(df)

        logger.info("截面标准化 ...")
        df = zscore_cross_section(
            df,
            feature_cols=self.cfg["feature_cols"],
            clip=self.cfg["zscore_clip"],
        )

        df = df.dropna(subset=[c for c in self.cfg["feature_cols"] + ["label"] if c in df.columns])
        if "date" not in df.columns:
            df = df.reset_index()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["date", "code"]).reset_index(drop=True)

        logger.info("有效样本: %d 行，日期范围: %s ~ %s",
                    len(df), df["date"].min().date(), df["date"].max().date())
        return df

    def _build_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        n = self.cfg["label_forward_days"]
        buy = self.cfg["label_buy_pct"]
        sell = self.cfg["label_sell_pct"]

        df = df.sort_values(["code", "date"])

        df["forward_ret"] = df.groupby("code")["close"].transform(
            lambda s: s.shift(-n).div(s) - 1
        )

        def _label_group(g: pd.DataFrame) -> pd.Series:
            ret = g["forward_ret"]
            q_low = ret.quantile(sell)
            q_hi = ret.quantile(1 - buy)
            label = pd.Series(0, index=g.index, dtype=int)
            label[ret >= q_hi] = 1
            label[ret <= q_low] = -1
            return label

        df["label"] = df.groupby("date", group_keys=False).apply(_label_group)
        return df

    def _filter_samples(self, df: pd.DataFrame) -> pd.DataFrame:
        before = len(df)

        if self.cfg["filter_limit_up"]:
            thr = self.cfg["limit_threshold"]
            if "pct_chg" in df.columns:
                pct = df["pct_chg"].abs() / 100.0
            elif "close" in df.columns:
                pct = df.groupby("code")["close"].pct_change().abs()
            else:
                pct = pd.Series(0, index=df.index)
            df = df[pct < thr]

        if "forward_ret" in df.columns:
            q01 = df["forward_ret"].quantile(0.001)
            q99 = df["forward_ret"].quantile(0.999)
            df = df[(df["forward_ret"] >= q01) & (df["forward_ret"] <= q99)]

        logger.info("过滤后: %d 行（过滤 %d 行）", len(df), before - len(df))
        return df

    @staticmethod
    def _shift_date(date_str: str, days: int) -> str:
        d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)
        return d.strftime("%Y-%m-%d")


class Evaluator:

    @staticmethod
    def rank_ic(
        df: pd.DataFrame,
        score_col: str = "buy_prob",
        ret_col: str = "forward_ret",
        date_col: str = "date",
    ) -> Tuple[float, float]:
        ic_series = (
            df.groupby(date_col)
            .apply(lambda g: spearmanr(g[score_col], g[ret_col])[0])
            .dropna()
        )
        mean_ic = float(ic_series.mean())
        icir = float(mean_ic / (ic_series.std(ddof=1) + 1e-9))
        return mean_ic, icir

    @staticmethod
    def auc_score(y_true: np.ndarray, proba: np.ndarray) -> float:
        classes = [-1, 0, 1]
        y_bin = label_binarize(y_true, classes=classes)
        try:
            return float(roc_auc_score(y_bin, proba, multi_class="ovr", average="macro"))
        except ValueError:
            return float("nan")

    @staticmethod
    def long_short_return(
        df: pd.DataFrame,
        score_col: str = "buy_prob",
        ret_col: str = "forward_ret",
        date_col: str = "date",
        top_pct: float = 0.2,
    ) -> float:
        def _ls(g: pd.DataFrame) -> float:
            n = max(1, int(len(g) * top_pct))
            s = g.sort_values(score_col, ascending=False)
            long = s.iloc[:n][ret_col].mean()
            short = s.iloc[-n:][ret_col].mean()
            return long - short

        ls = df.groupby(date_col).apply(_ls).dropna()
        return float(ls.mean())


class RollingTrainer:

    def __init__(self, cfg: Dict, full_df: pd.DataFrame):
        self.cfg = cfg
        self.df = full_df
        self.dates = sorted(full_df["date"].unique())
        self.eval = Evaluator()
        self.results: List[Dict] = []
        self.all_val: List[pd.DataFrame] = []

    def run(self) -> ThreeClassModel:
        train_d = self.cfg["train_days"]
        valid_d = self.cfg["valid_days"]
        step_d = self.cfg["step_days"]
        feat = self.cfg["feature_cols"]
        n_dates = len(self.dates)

        last_model = None
        cursor = train_d

        while cursor + valid_d <= n_dates:
            train_start = self.dates[max(0, cursor - train_d)]
            train_end = self.dates[cursor - 1]
            valid_start = self.dates[cursor]
            valid_end = self.dates[min(cursor + valid_d - 1, n_dates - 1)]

            train_df = self.df[
                (self.df["date"] >= train_start) &
                (self.df["date"] <= train_end)
            ]
            valid_df = self.df[
                (self.df["date"] >= valid_start) &
                (self.df["date"] <= valid_end)
            ]

            if len(train_df) < self.cfg["min_train_samples"]:
                logger.info(
                    "训练样本不足 (%d)，跳过: %s ~ %s",
                    len(train_df), train_start.date(), train_end.date(),
                )
                cursor += step_d
                continue

            logger.info(
                "训练轮次: train=%s~%s (%d)  valid=%s~%s (%d)",
                train_start.date(), train_end.date(), len(train_df),
                valid_start.date(), valid_end.date(), len(valid_df),
            )

            X_train = train_df[feat].values
            y_train = train_df["label"].values
            X_valid = valid_df[feat].values
            y_valid = valid_df["label"].values

            label_map = {-1: 0, 0: 1, 1: 2}
            y_train_m = np.vectorize(label_map.get)(y_train)
            y_valid_m = np.vectorize(label_map.get)(y_valid)

            model = LGBMClassifier(**self.cfg["lgbm_params"])
            model.fit(
                X_train, y_train_m,
                eval_set=[(X_valid, y_valid_m)],
            )

            proba = model.predict_proba(X_valid)
            buy_prob = proba[:, 2]

            val_pred = valid_df.copy()
            val_pred["buy_prob"] = buy_prob
            val_pred["pred_label"] = np.argmax(proba, axis=1) - 1

            ic, icir = self.eval.rank_ic(val_pred)
            auc = self.eval.auc_score(y_valid_m, proba)
            ls_ret = self.eval.long_short_return(val_pred)

            round_result = {
                "train_start": str(train_start.date()),
                "train_end": str(train_end.date()),
                "valid_start": str(valid_start.date()),
                "valid_end": str(valid_end.date()),
                "train_n": int(len(train_df)),
                "valid_n": int(len(valid_df)),
                "rank_ic": round(ic, 4),
                "icir": round(icir, 4),
                "auc": round(auc, 4),
                "ls_daily_ret": round(ls_ret, 6),
            }
            self.results.append(round_result)
            self.all_val.append(val_pred)

            logger.info(
                "  IC=%.4f  ICIR=%.4f  AUC=%.4f  LS=%.4f",
                ic, icir, auc, ls_ret,
            )

            last_model = model
            cursor += step_d

        if last_model is None:
            raise RuntimeError("没有完成任何一轮训练，检查数据量和窗口参数。")

        return last_model

    def summary(self) -> Dict:
        if not self.results:
            return {}
        metrics_df = pd.DataFrame(self.results)
        return {
            "rounds": len(self.results),
            "mean_ic": round(float(metrics_df["rank_ic"].mean()), 4),
            "mean_icir": round(float(metrics_df["icir"].mean()), 4),
            "mean_auc": round(float(metrics_df["auc"].mean()), 4),
            "mean_ls_ret": round(float(metrics_df["ls_daily_ret"].mean()), 6),
            "ic_stability": round(float((metrics_df["rank_ic"] > 0).mean()), 4),
            "rounds_detail": self.results,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="截面 LightGBM 滚动训练")
    parser.add_argument("--start", type=str, default=CONFIG["start_date"])
    parser.add_argument("--end", type=str, default=CONFIG["end_date"])
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = CONFIG.copy()
    cfg["start_date"] = args.start
    cfg["end_date"] = args.end

    logger.info("=" * 60)
    logger.info("截面 LightGBM 三分类滚动训练")
    logger.info("特征数: %d  标的范围: 全 A 股", len(cfg["feature_cols"]))
    logger.info("=" * 60)

    preparer = DataPreparer(cfg)
    full_df = preparer.load_and_prepare()

    trainer = RollingTrainer(cfg, full_df)
    last_model = trainer.run()
    summary = trainer.summary()

    feat_imp = {}
    if hasattr(last_model, "feature_importances_"):
        imp_arr = last_model.feature_importances_
        feat_imp = dict(zip(cfg["feature_cols"], imp_arr.tolist()))
        feat_imp = dict(
            sorted(feat_imp.items(), key=lambda x: x[1], reverse=True)
        )

    today = datetime.now().strftime("%Y%m%d")
    model_dir = Path(PATHS["model_dir"])
    model_dir.mkdir(parents=True, exist_ok=True)

    model_path = model_dir / f"{cfg['model_name_prefix']}_{today}.pkl"
    joblib.dump(last_model, model_path)
    logger.info("模型保存: %s", model_path)

    report = {
        "train_date": today,
        "config": {k: v for k, v in cfg.items() if k != "lgbm_params"},
        "lgbm_params": cfg["lgbm_params"],
        "training_summary": summary,
        "feature_importance": feat_imp,
    }
    report_path = model_dir / f"{cfg['model_name_prefix']}_{today}_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info("报告保存: %s", report_path)

    logger.info("=" * 60)
    logger.info("训练完成  轮次=%d", summary.get("rounds", 0))
    logger.info("  平均 RankIC : %.4f", summary.get("mean_ic", 0))
    logger.info("  平均 ICIR   : %.4f", summary.get("mean_icir", 0))
    logger.info("  平均 AUC    : %.4f", summary.get("mean_auc", 0))
    logger.info("  IC>0 稳定性 : %.2f%%", summary.get("ic_stability", 0) * 100)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
