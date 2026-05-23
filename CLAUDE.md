# 量化投资系统

A-share quantitative trading system with ML-based stock selection, backtesting, and paper trading.

## Project Structure

- `main.py` - 统一 CLI 入口（所有命令通过这里执行）
- `config/` - 集中配置（settings.py + .env）
- `src/commands/` - 命令模块（data/train/backtest/trade/system）
- `src/data/` - 数据层（Baostock 抓取、SQLite 加载、缓存）
- `src/features/` - 特征工程（日线、分钟、截面、技术指标）
- `src/labels/` - 标签构建（分位数、排名）
- `src/models/` - ML 模型（LightGBM、集成模型）
- `src/backtest/` - 回测引擎和绩效指标
- `src/strategy/` - 策略层（信号、持仓、风控、市场状态）
- `src/execution/` - 执行层（模拟交易）
- `src/news/` - 新闻抓取和情绪分析
- `src/web/` - Flask Web API（Blueprint 路由）
- `src/utils/` - 通用工具（日志、通知、辅助函数）
- `data/` - 数据库、缓存、模型文件（git-ignored）
- `tests/` - 单元测试

## Commands

```bash
# 数据管理
python main.py data update                    # 更新全部数据
python main.py data update --type daily       # 只更新日线
python main.py data update --minute 5         # 更新5分钟线
python main.py data info                      # 查看数据概况

# 模型训练
python main.py train single --symbol 000001   # 单股票训练
python main.py train cs                       # 截面模型训练
python main.py train ensemble                 # 集成模型训练

# 回测
python main.py backtest single --symbol 000001  # 单股票回测
python main.py backtest cs --model models/cs_model.pkl  # 截面回测

# 模拟交易
python main.py trade run                      # 执行每日交易
python main.py trade run --dry-run            # 模拟运行（不执行）
python main.py trade status                   # 查看持仓
python main.py trade history --limit 20       # 交易历史

# Web 服务
python main.py serve                          # 启动 Flask (0.0.0.0:5000)
python main.py serve --port 8080 --debug      # 自定义端口

# 系统
python main.py diagnose                       # 系统诊断
python main.py config show                    # 显示配置
```

## Architecture Rules

- All paths use `pathlib.Path`, never hardcoded strings
- API keys loaded from `config/config.env` via `python-dotenv`
- Data access goes through `src.data.loader.DataLoader`
- Models inherit from `src.models.base.BaseModel`
- Features inherit from `src.features.base.BaseFeature`
- Module dependency: utils <- data <- features <- models <- backtest/strategy
- CLI commands in `src/commands/`, dispatched by `main.py`
