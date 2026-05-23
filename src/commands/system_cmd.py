"""
系统命令 — serve / diagnose / config
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def cmd_serve(args):
    """启动 Web 服务"""
    from src.web.app import create_app
    from config.settings import server_config, print_config_summary

    print_config_summary()
    app = create_app()
    print(f"\nStarting server on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


def cmd_diagnose(args):
    """系统诊断"""
    from config.settings import DB, PATHS, print_config_summary
    from src.data.loader import DataLoader

    print_config_summary()

    print("\n=== Database Check ===")
    for name, path in DB.items():
        exists = path.exists()
        size_mb = path.stat().st_size / 1024 / 1024 if exists else 0
        status = f"OK ({size_mb:.1f} MB)" if exists else "MISSING"
        print(f"  {name}: {status}")

    print("\n=== Data Content ===")
    try:
        loader = DataLoader()
        info = loader.get_db_info()
        for k, v in info.items():
            print(f"  {k}: stocks={v['stocks']}, rows={v['rows']}, {v['start']} ~ {v['end']}")
    except Exception as e:
        print(f"  Error: {e}")

    print("\n=== Model Files ===")
    model_dir = PATHS["model_dir"]
    if model_dir.exists():
        models = list(model_dir.glob("*.pkl"))
        print(f"  Found {len(models)} model files")
        for m in models[:10]:
            print(f"    {m.name} ({m.stat().st_size / 1024:.1f} KB)")
    else:
        print("  Model directory not found")

    print("\n=== Config ===")
    from config.settings import data_config, trade_config, model_config
    print(f"  Stock pool: {data_config.stock_pool_size}")
    print(f"  Capital: {trade_config.total_capital:,.0f}")
    print(f"  Max positions: {trade_config.max_positions}")
    print(f"  Stop loss: {trade_config.stop_loss_pct*100:.1f}%")
    print(f"  Model trees: {model_config.n_estimators}")


def cmd_config_show(args):
    """显示当前配置"""
    from config.settings import (
        data_config, label_config, model_config,
        trade_config, backtest_config, server_config,
    )

    configs = [
        ("Data", data_config),
        ("Label", label_config),
        ("Model", model_config),
        ("Trade", trade_config),
        ("Backtest", backtest_config),
        ("Server", server_config),
    ]

    for name, cfg in configs:
        print(f"\n{name} Config:")
        for k, v in vars(cfg).items():
            print(f"  {k}: {v}")
