"""
Kronos tokenizer 特征提取器
基于清华 Kronos 金融 K 线基础模型，从 5 分钟线提取离散 token 特征
"""

import sys
import numpy as np
import pandas as pd
import torch
from pathlib import Path

from src.features.base import BaseFeature

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from model.kronos import KronosTokenizer


class KronosMinuteFeatureBuilder(BaseFeature):
    """基于 Kronos tokenizer 的 5 分钟线特征提取器"""

    def __init__(
        self,
        tokenizer_path: str = None,
        window: int = 48,
        device: str = "cpu",
        clip: float = 5.0,
        latent_dim: int = 32,
    ):
        if tokenizer_path is None:
            from config.settings import KRONOS_TOKENIZER_PATH
            tokenizer_path = str(KRONOS_TOKENIZER_PATH)

        self.window = window
        self.clip = clip
        self.device = device
        self.latent_dim = latent_dim
        self.tokenizer = self._load_tokenizer(tokenizer_path)

    def _load_tokenizer(self, path: str) -> KronosTokenizer:
        tokenizer = KronosTokenizer.from_pretrained(path)
        tokenizer = tokenizer.to(self.device)
        tokenizer.eval()
        return tokenizer

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.window + 1:
            return pd.DataFrame(index=df.index)

        OHLCV_COLS = ["open", "high", "low", "close", "volume"]
        if not all(c in df.columns for c in OHLCV_COLS):
            return pd.DataFrame(index=df.index)

        data = df[OHLCV_COLS].copy()
        data["amount"] = data["close"] * data["volume"]
        data = data.replace([np.inf, -np.inf], np.nan).ffill().bfill()
        if data.isnull().any().any():
            return pd.DataFrame(index=df.index)

        raw = data[["open", "high", "low", "close", "volume", "amount"]].values.astype(
            np.float32
        )

        features = self._extract_features(raw)
        cols = [f"kronos_f{i}" for i in range(features.shape[1])]
        result_index = df.index[self.window :]
        result = pd.DataFrame(features, index=result_index, columns=cols)
        return result

    def _extract_features(self, raw: np.ndarray) -> np.ndarray:
        n = len(raw)
        x_mean = raw.mean(axis=0)
        x_std = raw.std(axis=0) + 1e-5
        x_norm = (raw - x_mean) / x_std
        x_norm = np.clip(x_norm, -self.clip, self.clip)

        all_features = []
        has_pca = False
        pca = None

        for end in range(self.window, n):
            start = end - self.window
            window = x_norm[start:end]
            window_raw = raw[start:end]

            x_tensor = torch.from_numpy(window).unsqueeze(0).to(self.device)

            with torch.no_grad():
                z = self.tokenizer.embed(x_tensor)
                for layer in self.tokenizer.encoder:
                    z = layer(z)
                z_quant_input = self.tokenizer.quant_embed(z)
                _, _, z_indices = self.tokenizer.tokenizer(
                    z_quant_input, half=True, collect_metrics=False
                )

            latent = z.squeeze(0).cpu().numpy()
            s1_ids = z_indices[0].squeeze(0).cpu().numpy()
            s2_ids = z_indices[1].squeeze(0).cpu().numpy()

            feat = []

            if not has_pca:
                from sklearn.decomposition import PCA

                pca = PCA(n_components=self.latent_dim)
                pca.fit(latent)
                has_pca = True

            latent_pca = pca.transform(latent)[-1]
            feat.extend(latent_pca.tolist())

            feat.append(s1_ids[-1] / 1023.0)
            feat.append(s2_ids[-1] / 1023.0)

            s1_onehot = np.bincount(s1_ids, minlength=1024).astype(float)
            s1_prob = s1_onehot / (s1_onehot.sum() + 1e-8)
            s1_entropy = -(s1_prob * np.log(s1_prob + 1e-8)).sum()
            feat.append(s1_entropy / np.log(1024))

            s2_onehot = np.bincount(s2_ids, minlength=1024).astype(float)
            s2_prob = s2_onehot / (s2_onehot.sum() + 1e-8)
            s2_entropy = -(s2_prob * np.log(s2_prob + 1e-8)).sum()
            feat.append(s2_entropy / np.log(1024))

            feat.append((s1_ids[-1] - s1_ids[-2]) / 1023.0 if len(s1_ids) > 1 else 0.0)
            feat.append((s2_ids[-1] - s2_ids[-2]) / 1023.0 if len(s2_ids) > 1 else 0.0)

            vol = window_raw[:, 4]
            feat.append(vol.mean() / (vol.std() + 1e-8))

            close = window_raw[:, 3]
            rets = np.diff(close) / (close[:-1] + 1e-8)
            feat.append(rets.mean())
            feat.append(rets.std())

            feat.append(window_raw[-1, 3] / (window_raw[0, 3] + 1e-8) - 1)

            all_features.append(feat)

        return np.array(all_features, dtype=np.float32)


def build_kronos_features_panel(
    stock_codes: list,
    data_loader,
    start_date: str,
    end_date: str,
    tokenizer_path: str = None,
    window: int = 48,
    device: str = "cpu",
) -> pd.DataFrame:
    """
    构建多股票 Kronos 特征面板
    返回: MultiIndex DataFrame (datetime, code), columns=kronos features
    """
    builder = KronosMinuteFeatureBuilder(
        tokenizer_path=tokenizer_path, window=window, device=device
    )
    all_feats = []

    for i, code in enumerate(stock_codes):
        if (i + 1) % 10 == 0:
            print(f"  Kronos features: {i+1}/{len(stock_codes)} done")

        df = data_loader.load_minute(code, start_date, end_date, freq="5min")
        if df.empty or len(df) < window + 10:
            continue

        feat = builder.compute(df)
        if feat.empty:
            continue

        feat.index = pd.MultiIndex.from_arrays(
            [feat.index, [code] * len(feat)], names=["datetime", "code"]
        )
        all_feats.append(feat)

    if not all_feats:
        raise ValueError("No Kronos features computed")

    combined = pd.concat(all_feats).sort_index()
    print(f"Kronos features: {combined.shape[1]} factors, {len(combined):,} rows")
    return combined
