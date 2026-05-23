"""
集成模型 — LightGBM + XGBoost + CatBoost + RandomForest
"""

import numpy as np
import pandas as pd
import joblib
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr

from src.models.base import BaseModel


class EnsembleModel(BaseModel):
    """多模型集成"""

    def __init__(self, weights: dict = None):
        self.weights = weights or {
            'lgbm': 0.4, 'xgb': 0.3, 'catboost': 0.2, 'rf': 0.1
        }
        self.models = {}
        self._build_models()

    def _build_models(self):
        from lightgbm import LGBMClassifier
        from xgboost import XGBClassifier
        from catboost import CatBoostClassifier
        from sklearn.ensemble import RandomForestClassifier

        self.models = {
            'lgbm': LGBMClassifier(
                n_estimators=500, learning_rate=0.05, max_depth=6,
                num_leaves=31, subsample=0.8, colsample_bytree=0.8,
                random_state=42, verbose=-1,
            ),
            'xgb': XGBClassifier(
                n_estimators=300, learning_rate=0.05, max_depth=6,
                subsample=0.8, colsample_bytree=0.8,
                random_state=42, eval_metric='logloss', verbosity=0,
            ),
            'catboost': CatBoostClassifier(
                iterations=300, learning_rate=0.05, depth=6,
                random_seed=42, verbose=0,
            ),
            'rf': RandomForestClassifier(
                n_estimators=200, max_depth=8,
                random_state=42, n_jobs=-1,
            ),
        }

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "EnsembleModel":
        mask = y.notna()
        X_c = X.loc[mask].copy()
        y_c = y.loc[mask].astype(int)

        print(f"Ensemble training: {len(X_c):,} samples")

        tscv = TimeSeriesSplit(n_splits=3)
        oof_preds = {name: np.zeros(len(X_c)) for name in self.models}

        for fold, (tr, val) in enumerate(tscv.split(X_c)):
            for name, model in self.models.items():
                model.fit(X_c.iloc[tr], y_c.iloc[tr])
                proba = model.predict_proba(X_c.iloc[val])
                classes = list(model.classes_)
                if 1 in classes:
                    oof_preds[name][val] = proba[:, classes.index(1)]

        # Calculate OOF AUC
        for name in self.models:
            valid = oof_preds[name] > 0
            if valid.sum() > 0:
                try:
                    auc = roc_auc_score(y_c[valid] == 1, oof_preds[name][valid])
                    print(f"  {name}: OOF AUC={auc:.4f}")
                except Exception:
                    pass

        # Retrain on full data
        for name, model in self.models.items():
            model.fit(X_c, y_c)

        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        preds = {}
        for name, model in self.models.items():
            proba = model.predict_proba(X)
            classes = list(model.classes_)
            if 1 in classes:
                preds[name] = proba[:, classes.index(1)]

        # Weighted average
        combined = np.zeros(len(X))
        total_weight = 0
        for name, weight in self.weights.items():
            if name in preds:
                combined += preds[name] * weight
                total_weight += weight

        if total_weight > 0:
            combined /= total_weight

        res = pd.DataFrame(index=X.index)
        res['buy_score'] = combined
        res['raw_pred'] = (combined >= 0.5).astype(int)
        return res

    def evaluate(self, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
        mask = y_test.notna()
        X_t = X_test.loc[mask]
        y_t = y_test.loc[mask].astype(int)

        pred = self.predict(X_t)
        metrics = {}

        try:
            auc = roc_auc_score(y_t, pred['buy_score'])
            metrics['auc'] = float(auc)
            print(f"Test AUC: {auc:.4f}")
        except Exception:
            pass

        # Direction accuracy
        direction = (pred['buy_score'] > 0.5).astype(int)
        acc = (direction == y_t).mean()
        metrics['accuracy'] = float(acc)
        print(f"Test accuracy: {acc:.4f}")

        return metrics
