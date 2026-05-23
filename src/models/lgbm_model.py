"""
LightGBM 模型 — 三分类 + 截面
"""

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.model_selection import TimeSeriesSplit

from src.models.base import BaseModel


class ThreeClassModel(BaseModel):
    """单股票三分类模型 (buy/sell/hold)"""

    def __init__(self, confidence_threshold: float = 0.50, long_only: bool = True):
        self.confidence_threshold = confidence_threshold
        self.long_only = long_only
        self.model = LGBMClassifier(
            n_estimators=500, learning_rate=0.03, max_depth=4,
            num_leaves=15, min_child_samples=80, subsample=0.7,
            colsample_bytree=0.7, reg_alpha=1.0, reg_lambda=2.0,
            class_weight={0: 0.5, 1: 3.0, 2: 1.0},
            random_state=42, verbose=-1,
        )

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "ThreeClassModel":
        mask = y.notna()
        common = X.index[X.index.isin(y.index)]
        mask = mask.loc[common]
        X_c = X.loc[common].copy()
        y_c = y.loc[common].copy()
        y_c = y_c[y_c.notna()].astype(int)
        X_c = X_c.loc[y_c.index]

        print(f"Training samples: {len(X_c):,}")

        tscv = TimeSeriesSplit(n_splits=5)
        scores = []
        for fold, (tr, val) in enumerate(tscv.split(X_c)):
            self.model.fit(X_c.iloc[tr], y_c.iloc[tr])
            pred = self._predict_proba(X_c.iloc[val])
            buy_mask = pred['signal'] == 1
            if buy_mask.sum() > 10:
                val_idx = X_c.iloc[val].index
                acc = (pred.loc[val_idx, 'signal'].values[buy_mask.values] ==
                       y_c.loc[val_idx].values[buy_mask.values]).mean()
                scores.append(acc)
                print(f"  Fold {fold+1}: buy_acc={acc:.3f} n={buy_mask.sum()}")

        if scores:
            print(f"Mean buy accuracy: {np.mean(scores):.3f}")

        self.model.fit(X_c, y_c)
        return self

    def _predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        proba = self.model.predict_proba(X)
        classes = list(self.model.classes_)
        res = pd.DataFrame(index=X.index)
        res['buy_prob'] = proba[:, classes.index(1)] if 1 in classes else 0
        res['sell_prob'] = proba[:, classes.index(0)] if 0 in classes else 0
        res['raw_pred'] = self.model.predict(X)
        res['signal'] = 2

        if self.long_only:
            buy_conf = (res['raw_pred'] == 1) & (res['buy_prob'] >= self.confidence_threshold)
            res.loc[buy_conf, 'signal'] = 1
        else:
            high_conf = proba.max(axis=1) >= self.confidence_threshold
            res.loc[high_conf & (res['raw_pred'] == 1), 'signal'] = 1
            res.loc[high_conf & (res['raw_pred'] == 0), 'signal'] = 0
        return res

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        return self._predict_proba(X)

    def evaluate(self, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
        common = X_test.index[X_test.index.isin(y_test.index)]
        X_t = X_test.loc[common]
        y_t = y_test.loc[common].dropna().astype(int)
        X_t = X_t.loc[y_t.index]

        pred = self._predict_proba(X_t)
        buy_mask = pred['signal'] == 1
        metrics = {}

        if buy_mask.sum() > 0:
            common_idx = pred[buy_mask].index.intersection(y_t.index)
            buy_acc = (pred.loc[common_idx, 'signal'] == y_t.loc[common_idx]).mean()
            metrics['buy_accuracy'] = float(buy_acc)
            metrics['coverage'] = float(buy_mask.sum() / len(y_t))
            metrics['n_signals'] = int(buy_mask.sum())
            print(f"Buy signals: {buy_mask.sum():,}, accuracy: {buy_acc:.3f}")

        imp = pd.Series(self.model.feature_importances_, index=X_t.columns).sort_values(ascending=False)
        print("\nTop 10 features:")
        for feat, val in imp.head(10).items():
            print(f"  {feat:25s} {val:.4f}")

        return metrics


class CrossSectionalModel(BaseModel):
    """截面模型 — 相对强弱打分"""

    def __init__(self, top_k: int = 5, confidence_threshold: float = 0.55):
        self.top_k = top_k
        self.confidence_threshold = confidence_threshold
        self.model = LGBMClassifier(
            n_estimators=500, learning_rate=0.03, max_depth=5,
            num_leaves=31, min_child_samples=50, subsample=0.8,
            colsample_bytree=0.8, reg_alpha=0.5, reg_lambda=1.0,
            class_weight={0: 1.0, 1: 1.0, 2: 0.3},
            random_state=42, verbose=-1,
        )
        self.feature_names_ = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "CrossSectionalModel":
        mask = y.notna() & y.isin([0, 1, 2])
        X_c = X[mask]
        y_c = y[mask].astype(int)

        print(f"Cross-sectional training: {len(X_c):,} samples")

        datetimes = X_c.index.get_level_values('datetime').unique()
        tscv = TimeSeriesSplit(n_splits=5)
        scores = []

        for fold, (tr_idx, val_idx) in enumerate(tscv.split(datetimes)):
            tr_dts = datetimes[tr_idx]
            val_dts = datetimes[val_idx]
            tr_mask = X_c.index.get_level_values('datetime').isin(tr_dts)
            val_mask = X_c.index.get_level_values('datetime').isin(val_dts)

            self.model.fit(X_c[tr_mask], y_c[tr_mask])
            val_proba = self.model.predict_proba(X_c[val_mask])
            classes = list(self.model.classes_)
            buy_idx = classes.index(1) if 1 in classes else 0
            score_s = pd.Series(val_proba[:, buy_idx], index=X_c[val_mask].index)
            label_s = y_c[val_mask]
            label_dir = label_s.map({1: 1, 0: -1, 2: 0}).astype(float)
            rank_ic = score_s.corr(label_dir, method='spearman')
            scores.append(rank_ic)
            print(f"  Fold {fold+1}: RankIC={rank_ic:+.4f}")

        print(f"Mean RankIC: {np.mean(scores):+.4f}")
        self.model.fit(X_c, y_c)
        self.feature_names_ = list(X_c.columns)
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        proba = self.model.predict_proba(X)
        classes = list(self.model.classes_)
        buy_idx = classes.index(1) if 1 in classes else 0
        res = pd.DataFrame(index=X.index)
        res['buy_score'] = proba[:, buy_idx]
        res['sell_score'] = proba[:, classes.index(0)] if 0 in classes else 0
        res['raw_pred'] = self.model.predict(X)
        return res

    def select_top_k(self, scores_df: pd.DataFrame, dt: pd.Timestamp) -> list:
        try:
            dt_scores = scores_df.loc[dt, 'buy_score']
        except KeyError:
            return []
        if isinstance(dt_scores, float):
            return []
        filtered = dt_scores[dt_scores >= self.confidence_threshold]
        return filtered.nlargest(self.top_k).index.tolist() if len(filtered) > 0 else []

    def evaluate(self, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
        mask = y_test.notna()
        X_t = X_test[mask]
        y_t = y_test[mask].astype(int)
        scores = self.predict(X_t)
        y_dir = y_t.map({1: 1, 0: -1, 2: 0}).astype(float)
        rank_ic = scores['buy_score'].corr(y_dir, method='spearman')

        datetimes = X_t.index.get_level_values('datetime').unique()
        daily_ics = []
        for dt in datetimes:
            try:
                dt_score = scores.loc[dt, 'buy_score']
                dt_label = y_dir.loc[dt]
                if len(dt_score) >= 3:
                    daily_ics.append(dt_score.corr(dt_label, method='spearman'))
            except Exception:
                pass

        ic_mean = np.mean(daily_ics) if daily_ics else 0
        ic_std = np.std(daily_ics) if daily_ics else 1
        icir = ic_mean / (ic_std + 1e-8)

        print(f"RankIC: {rank_ic:+.4f}, ICIR: {icir:+.4f}")
        return {'rank_ic': float(rank_ic), 'ic_mean': float(ic_mean), 'icir': float(icir)}
