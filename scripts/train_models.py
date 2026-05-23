#!/usr/bin/env python
"""
模型训练入口
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.loader import DataLoader
from src.features.daily import DailyFeatureBuilder, build_daily_features_panel
from src.labels.quantile import SmartLabelBuilder
from src.models.lgbm_model import ThreeClassModel
from config.settings import data_config, model_config


def main():
    print("=" * 60)
    print("Model Training")
    print("=" * 60)

    loader = DataLoader()
    symbols = loader.get_daily_symbols(min_days=200)[:50]
    print(f"Training pool: {len(symbols)} stocks")

    if not symbols:
        print("No stocks available")
        return

    # Load data and build features
    print("\nBuilding features...")
    features = build_daily_features_panel(symbols, loader, "2022-01-01", "2025-12-31")

    # Build labels
    print("\nBuilding labels...")
    # For daily features, we use a simpler label approach
    # TODO: integrate with proper daily label builder

    print("Training complete (placeholder). Implement full pipeline next.")


if __name__ == '__main__':
    main()
