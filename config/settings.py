"""
统一配置管理
所有路径、参数、API keys 集中管理，禁止硬编码
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict
import os

# ── 项目根目录 ─────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent

# ── 数据库配置 ─────────────────────────────────────────────────────
DB: Dict[str, Path] = {
    "market": ROOT / "data" / "db" / "market.db",
    "quantpro": ROOT / "data" / "db" / "quantpro.db",
}

# ── 目录路径 ───────────────────────────────────────────────────────
PATHS: Dict[str, Path] = {
    "model_dir": ROOT / "data" / "models",
    "log_dir": ROOT / "logs",
    "cache_dir": ROOT / "data" / "cache",
    "db_dir": ROOT / "data" / "db",
}

for path in PATHS.values():
    path.mkdir(parents=True, exist_ok=True)

# ── API 密钥 ───────────────────────────────────────────────────────
def _load_env_file():
    env_file = ROOT / "config" / "config.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value

_load_env_file()

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# ── Kronos 模型路径 ──────────────────────────────────────────────
KRONOS_TOKENIZER_PATH = Path(os.environ.get("KRONOS_TOKENIZER_PATH", str(ROOT / "model" / "Kronos-Tokenizer-base")))


# ── 数据类配置 ─────────────────────────────────────────────────────
@dataclass
class DataConfig:
    frequency: str = "daily"
    default_symbol: str = "sh.600519"
    lookback_days: int = 250
    stock_pool_size: int = 100
    min_trading_days: int = 15
    realtime_source: str = "tencent"


@dataclass
class LabelConfig:
    quantile_bins: int = 5
    forward_days: int = 5
    top_ratio: float = 0.2
    bottom_ratio: float = 0.2


@dataclass
class ModelConfig:
    n_estimators: int = 500
    learning_rate: float = 0.05
    max_depth: int = 6
    num_leaves: int = 31
    min_child_samples: int = 20
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    random_state: int = 42
    model_dir: Path = PATHS["model_dir"]


@dataclass
class TradeConfig:
    total_capital: float = 1_000_000.0
    max_positions: int = 10
    stop_loss_pct: float = -0.05
    take_profit_pct: float = 0.15
    max_hold_days: int = 10
    commission: float = 0.0003
    stamp_duty: float = 0.001
    min_order_amount: float = 5000.0


@dataclass
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    commission: float = 0.0003
    slippage: float = 0.001
    stamp_duty: float = 0.001
    top_k: int = 5
    rebalance_days: int = 5


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False


@dataclass
class AIConfig:
    api_key: str = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url: str = os.environ.get("AI_BASE_URL", "https://api.deepseek.com/v1")
    chat_model: str = os.environ.get("AI_CHAT_MODEL", "deepseek-v4-pro")
    pro_model: str = os.environ.get("AI_PRO_MODEL", "deepseek-v4-pro")


ai_config = AIConfig()


@dataclass
class ProxyConfig:
    enabled: bool = os.environ.get("PROXY_ENABLED", "").lower() in ("true", "1", "yes")
    socks5_host: str = os.environ.get("PROXY_SOCKS5_HOST", "127.0.0.1")
    socks5_port: int = int(os.environ.get("PROXY_SOCKS5_PORT", "1080"))
    http_host: str = os.environ.get("PROXY_HTTP_HOST", "127.0.0.1")
    http_port: int = int(os.environ.get("PROXY_HTTP_PORT", "10809"))


@dataclass
class NewsConfig:
    rss_max_per_source: int = 5
    analyze_batch_size: int = 5
    analyze_rate_limit_seconds: float = 1.0
    impact_decay_halflife: int = 3


# ── 全局实例 ───────────────────────────────────────────────────────
data_config = DataConfig()
label_config = LabelConfig()
model_config = ModelConfig()
trade_config = TradeConfig()
backtest_config = BacktestConfig()
server_config = ServerConfig()
proxy_config = ProxyConfig()
news_config = NewsConfig()


# ── 工具函数 ───────────────────────────────────────────────────────
def get_db_path(db_name: str) -> Path:
    if db_name not in DB:
        raise ValueError(f"Unknown database: {db_name}. Available: {list(DB.keys())}")
    return DB[db_name]


def print_config_summary():
    print("=" * 60)
    print("量化交易系统配置")
    print("=" * 60)
    print(f"项目根目录:  {ROOT}")
    print(f"市场数据库:  {DB['market']}  [{'OK' if DB['market'].exists() else 'MISSING'}]")
    print(f"业务数据库:  {DB['quantpro']}  [{'OK' if DB['quantpro'].exists() else 'MISSING'}]")
    print(f"股票池大小:  {data_config.stock_pool_size}")
    print(f"初始资金:    {trade_config.total_capital:,.0f}")
    print(f"最大持仓:    {trade_config.max_positions}")
    print(f"模型目录:    {PATHS['model_dir']}")
    print(f"DeepSeek:    {'已配置' if DEEPSEEK_API_KEY else '未配置'}")
    print("=" * 60)


if __name__ == "__main__":
    print_config_summary()
