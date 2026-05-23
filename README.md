# QuantPro — A股量化交易系统

> 全栈量化投资研究平台：数据采集 → 特征工程 → 模型训练 → 策略执行 → 回测评估 → Web 可视化 → 实盘交易

## 项目概览

QuantPro 是一个面向 A 股市场的全流程量化交易系统，覆盖从数据获取到实盘执行的完整链路。系统采用日线选股 + 日内交易的**双频率策略体系**，集成多 Agent 新闻分析团队，支持模拟交易和同花顺实盘对接。

| 指标 | 数值 |
|------|------|
| Python 核心文件 | 73 个 |
| Python 代码行数 | ~11,800 行 |
| 前端页面 | 16 个 |
| API 端点 | 80+ |
| 数据库表 | 17 个 |
| 支持股票数 | 5,200+ |

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        数据获取层                            │
│  Baostock(日/分钟/月线)  easyquotation(实时)  AKShare(新闻)  │
│  NewsNow API            RSS Feed(13源)       feedparser     │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               v                              v
┌────────────────────────┐      ┌──────────────────────────┐
│       market.db        │      │       quantpro.db        │
│  stock_kline (日线)    │      │  positions (持仓)        │
│  minute_kline (分钟线) │      │  trade_records (交易)    │
│  stock_info (股票信息) │      │  operation_logs (日志)   │
│  news (新闻)           │      │  news_raw (RSS原始)      │
│  news_factor (因子)    │      │  strategies (策略)       │
│  news_daily_factor     │      │                          │
└──────────┬─────────────┘      └──────────┬───────────────┘
           │                               │
           v                               v
┌─────────────────────────────────────────────────────────────┐
│                        特征工程层                            │
│  DailyFeature · MinuteFeature · TechnicalIndicators         │
│  CrossSectionalNormalize(z-score) · NewsFeatureBuilder      │
│  KronosMinuteFeature(时序大模型) · IntradayFeatureBuilder   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           v
┌─────────────────────────────────────────────────────────────┐
│                        模型训练层                            │
│  ThreeClassModel(LGBM三分类) · CrossSectionalModel(截面)    │
│  EnsembleModel(LGBM+XGB+CatBoost+RF 加权集成)              │
│  Kronos + CrossSectionalModel(时序大模型+截面)              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           v
┌─────────────────────────────────────────────────────────────┐
│                        策略执行层                            │
│                                                             │
│  日线: DailyPickPipeline                                    │
│    模型打分(60%) + 新闻Agent打分(40%) → 换手率控制 → Top20 │
│                                                             │
│  日内: IntradayStrategy                                     │
│    规则信号 + ML信号 → ATR仓位 → 止损/移动止损 → 熔断     │
│                                                             │
│  Agent团队: 宏观(15%) + 行业(25%) + 技术(20%)              │
│            + 情绪(15%) + 风控(25%) → CIO综合决策           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           v
┌─────────────────────────────────────────────────────────────┐
│                     回测 · 执行 · 展示                       │
│  BacktestEngine · PositionManager · easytrader(实盘)        │
│  Flask Web (14 Blueprint, 16页面, SSE流式)                  │
│  模型监控流水线: 预检→新闻→选股→日内→收市                  │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
quant——project/
├── main.py                    # CLI 统一入口
├── config/
│   ├── settings.py            # 统一配置管理 (7大配置类)
│   └── config.env             # 环境变量 (API Key等)
├── model/
│   ├── kronos.py              # Kronos 时序大模型
│   └── module.py              # 模型组件
├── data/
│   ├── db/
│   │   ├── market.db          # 行情数据库
│   │   └── quantpro.db        # 业务数据库
│   ├── models/                # 训练好的模型 (.pkl)
│   └── cache/                 # 运行时缓存
├── scripts/
│   ├── start.bat              # Windows 启动脚本
│   ├── daily_run.py           # 每日自动任务
│   ├── update_data.py         # 数据更新
│   ├── train_models.py        # 模型训练
│   └── backtest_full.py       # 完整回测
└── src/
    ├── data/                  # 数据层
    │   ├── loader.py          # 统一数据加载
    │   ├── fetcher.py         # Baostock 数据抓取
    │   ├── realtime.py        # 实时行情
    │   └── merger.py          # 数据库合并
    ├── features/              # 特征工程
    │   ├── base.py            # 特征基类
    │   ├── daily.py           # 日线特征
    │   ├── minute.py          # 分钟线特征
    │   ├── technical.py       # 技术指标
    │   ├── cross_sectional.py # 截面标准化
    │   ├── kronos.py          # Kronos 时序特征
    │   └── news.py            # 新闻因子特征
    ├── labels/                # 标签构建
    │   ├── quantile.py        # 分位数标签
    │   ├── ranking.py         # 截面排名标签
    │   └── intraday_labels.py # 日内标签
    ├── models/                # 模型层
    │   ├── lgbm_model.py      # LightGBM (三分类+截面)
    │   └── ensemble.py        # 集成模型
    ├── strategy/              # 策略层
    │   ├── daily_pick.py      # 每日选股流水线
    │   ├── position.py        # 持仓管理
    │   ├── risk.py            # 风控模块
    │   ├── regime.py          # 市场状态识别
    │   ├── intraday_strategy.py # 日内5分钟策略
    │   └── agent_team.py      # 多Agent新闻分析团队
    ├── backtest/              # 回测引擎
    │   ├── engine.py          # 回测引擎
    │   ├── intraday_backtest.py # 日内回测
    │   ├── metrics.py         # 绩效指标
    │   └── report.py          # 报告生成
    ├── execution/             # 交易执行
    │   ├── trader.py          # 真实交易 (easytrader)
    │   └── paper.py           # 模拟交易
    ├── news/                  # 新闻模块
    │   ├── fetcher.py         # AKShare + NewsNow 抓取
    │   ├── analyzer.py        # DeepSeek LLM 因子分析
    │   └── rss_fetcher.py     # RSS 13源抓取
    ├── commands/              # CLI 命令
    │   ├── data_cmd.py        # 数据管理
    │   ├── train_cmd.py       # 模型训练
    │   ├── backtest_cmd.py    # 回测
    │   ├── trade_cmd.py       # 交易
    │   ├── news_cmd.py        # 新闻
    │   └── intraday_cmd.py    # 日内策略
    ├── utils/                 # 工具
    │   ├── logger.py          # 日志
    │   ├── notify.py          # 通知 (微信/飞书/邮件)
    │   └── operation_logger.py # 操作日志
    └── web/                   # Web 应用
        ├── app.py             # Flask App 工厂
        ├── routes/            # 14个 API Blueprint
        │   ├── ai.py          # AI 选股/聊天/分析
        │   ├── console.py     # 总控台 (模型监控流水线)
        │   ├── stock.py       # 股票/ETF/基金数据
        │   ├── news.py        # 新闻 + 因子分析 + Agent团队
        │   ├── backtest.py    # 回测
        │   ├── mock_trade.py  # 模拟交易
        │   ├── real_trade.py  # 真实交易
        │   ├── strategy.py    # 策略监控
        │   ├── portfolio.py   # 持仓/组合
        │   └── ...            # 其他路由
        └── static/            # 前端静态文件
            ├── *.html         # 16个页面
            ├── styles.css
            └── js/            # 5个JS文件
```

## 核心功能

### 1. 数据管理

- **历史行情**: Baostock 日线/5分钟线/月线，5,200+ 只 A 股
- **实时行情**: easyquotation 腾讯源，支持单股/批量查询
- **新闻数据**: AKShare 东方财富个股新闻 + CCTV 市场新闻 + 13 个 RSS 财经源
- **增量更新**: 自动检测过期数据，支持增量抓取

### 2. 特征工程

- **技术指标**: MA/EMA/MACD/RSI/KDJ/Bollinger/ATR 等
- **截面标准化**: 跨股票 z-score (clip[-3,3])，消除量纲差异
- **Kronos 时序特征**: 基于时序大模型的深度学习特征表示
- **新闻因子**: 14 个原始因子 + 4 个衍生因子，支持截面排名标准化

### 3. 模型训练

| 模型 | 用途 | 验证方式 |
|------|------|---------|
| ThreeClassModel | 单股三分类 (buy/sell/hold) | TimeSeriesSplit 5折 |
| CrossSectionalModel | 截面选股排名 | RankIC / ICIR |
| EnsembleModel | 多模型加权集成 | OOF AUC |
| Kronos + 截面 | 时序大模型 + 截面 | RankIC |

### 4. 策略体系

**日线选股 (DailyPickPipeline)**:
- 模型打分 60% + 新闻 Agent 打分 40%
- 极低换手: 每日最多新增 3 只，最少持有 5 天
- 分数跌幅超 -0.15 才替换

**日内策略 (IntradayStrategy)**:
- 规则信号 (趋势+动量+突破+K线形态) + ML 信号
- ATR 动态仓位 + 止损/移动止损 + 日亏损熔断

**多 Agent 新闻分析 (AgentTeam)**:
- 5 个专业 Agent: 宏观(15%) / 行业(25%) / 技术(20%) / 情绪(15%) / 风控(25%)
- CIO 综合决策，风控一票否决
- 基于 DeepSeek V4 Pro

### 5. 回测评估

- 单股回测 / 截面回测 / 日内回测
- 指标: CAGR / Sharpe / MaxDrawdown / Turnover / RankIC / ICIR
- 时序分割 (train/valid/test)，无随机分割

### 6. 交易执行

- **模拟交易**: JSON 持久化，完整买卖/持仓/平仓记录
- **实盘交易**: easytrader 对接同花顺客户端，支持买卖/撤单/新股申购
- **风控**: 最大杠杆 / 单股权重上限 / 换手率上限 / 回撤止损

### 7. Web 可视化

16 个页面，80+ API 端点:

| 页面 | 功能 |
|------|------|
| 首页 | 大盘指数/系统状态/快捷入口 |
| A股市场 | 5,200+ 股票列表，沪A/深A筛选 |
| 股票详情 | K线(5分/日/周/月) + AI分析 |
| AI 助手 | 流式聊天/选股/分析 |
| 回测 | 触发/历史/结果展示 |
| 持仓 | 模拟/真实持仓概览 |
| 每日讯息 | 新闻 + 关键词 + AI摘要 |
| 模型监控 | 实时流水线 (预检→新闻→选股→日内→收市) |
| 总控台 | 系统诊断/告警/设置 |

## 快速开始

### 环境要求

- Python 3.11+
- Windows (easytrader 依赖)

### 安装

```bash
# 克隆项目
git clone <repo-url>
cd quant——project

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp config/config.env.example config/config.env
# 编辑 config/config.env，填入 DEEPSEEK_API_KEY 等
```

### 数据初始化

```bash
# 更新日线数据
python main.py data update

# 更新分钟线数据
python main.py data update --minute

# 查看数据状态
python main.py data info
```

### 模型训练

```bash
# 截面模型训练 (推荐)
python main.py train cs

# 集成模型训练
python main.py train ensemble

# 单股模型训练
python main.py train single --code 000001
```

### 回测

```bash
# 截面回测
python main.py backtest cs

# 单股回测
python main.py backtest single --code 000001
```

### 启动 Web 服务

```bash
# 方式1: CLI 启动
python main.py serve

# 方式2: 直接启动
python -m src.web.app

# 方式3: Windows 脚本
scripts\start.bat
```

访问 http://127.0.0.1:5000

### 新闻分析

```bash
# 抓取新闻
python main.py news fetch

# 新闻因子分析 (DeepSeek LLM)
python main.py news analyze
```

## CLI 命令

```bash
python main.py <command> [options]

Commands:
  data update          更新行情数据 (--minute 更新分钟线)
  data info            查看数据状态
  train cs             训练截面模型
  train single         训练单股模型 (--code 指定股票)
  train ensemble       训练集成模型
  backtest cs          截面回测
  backtest single      单股回测
  trade daily          每日模拟交易
  news fetch           抓取新闻
  news analyze         新闻因子分析
  serve                启动 Web 服务
  diagnose             系统诊断
  config show          显示配置
  pick                 每日选股
  intraday backtest    日内回测
```

## API 端点

| 路径 | 方法 | 功能 |
|------|------|------|
| `/api/stock/list` | GET | 股票列表 (分页/筛选/市场) |
| `/api/stock/detail/<code>` | GET | 股票详情 (日线/5分钟线) |
| `/api/stock/search` | GET | 股票搜索 |
| `/api/news/latest` | GET | 最新新闻 |
| `/api/news/stock/<code>` | GET | 个股新闻 |
| `/api/news/analyze` | POST | 触发新闻因子分析 |
| `/api/news/agent-team` | POST | 触发多Agent分析 |
| `/api/news/factors/<code>` | GET | 个股新闻因子 |
| `/api/news/daily-factors/<code>` | GET | 日频聚合因子 |
| `/api/ai/chat` | POST | AI 流式聊天 (SSE) |
| `/api/ai/pick` | POST | AI 选股 |
| `/api/backtest/run` | POST | 触发回测 |
| `/api/mock/account` | GET | 模拟账户 |
| `/api/mock/buy` | POST | 模拟买入 |
| `/api/mock/sell` | POST | 模拟卖出 |
| `/api/portfolio/positions` | GET | 持仓列表 |
| `/api/console/report` | GET | 总控台报告 |
| `/api/monitor/status` | GET | 模型监控状态 |
| `/api/system/health` | GET | 系统健康检查 |

## 数据库

### market.db — 行情数据库

| 表 | 说明 | 记录量级 |
|----|------|---------|
| stock_kline | 日K线 | 650万+ |
| minute_kline | 5分钟K线 | 1.5亿+ |
| monthly_kline | 月K线 | 20万+ |
| stock_info | 股票名称/行业 | 7,500+ |
| news | 新闻 (AKShare+RSS) | 持续增长 |
| news_factor | LLM 提取因子 | 持续增长 |
| news_daily_factor | 日频聚合因子 | 持续增长 |

### quantpro.db — 业务数据库

| 表 | 说明 |
|----|------|
| positions | 持仓记录 (入场/出场/盈亏) |
| trade_records | 交易记录 (详细版) |
| trade_log | 交易日志 |
| operation_logs | 操作日志 |
| strategies | 策略列表 |
| news_raw | RSS 原始新闻 |

## 技术栈

| 层次 | 技术 |
|------|------|
| 数据源 | Baostock · easyquotation · AKShare · feedparser · newspaper3k |
| 数据存储 | SQLite · JSON |
| 特征工程 | pandas · numpy · Kronos (PyTorch) |
| ML 模型 | LightGBM · XGBoost · CatBoost · RandomForest |
| LLM | DeepSeek V4 Pro |
| 回测 | 自研引擎 (TimeSeriesSplit · RankIC/ICIR) |
| 交易执行 | easytrader (同花顺) · 模拟交易 |
| Web 后端 | Flask · flask-cors · 14 Blueprint |
| Web 前端 | 原生 HTML/CSS/JS · SSE 流式 |
| 通知 | 微信 Webhook · 飞书 Webhook · 邮件 |

## 关键设计

1. **双频率策略**: 日线选股 (截面模型+新闻Agent) + 日内5分钟 (规则+ML)，覆盖不同持仓周期
2. **多Agent新闻分析**: 5专业Agent + CIO综合决策，风控一票否决，权重偏向风控(25%)和行业(25%)
3. **极低换手控制**: 每日最多新增3只，分数跌幅超-0.15才替换，最少持有5天
4. **截面标准化**: 跨股票 z-score (clip[-3,3])，消除量纲差异
5. **模型监控流水线**: Web端一键启动 预检→新闻→选股→日内→收市 完整流水线
6. **三层降级查询**: trade_records → mock_account.json → operation_logs，确保鲁棒性
7. **统一配置管理**: 7个 dataclass 配置类 + config.env，所有参数可配置

## 免责声明

本项目仅供量化投资研究学习使用，不构成任何投资建议。实盘交易存在风险，请谨慎决策。作者不对因使用本系统导致的任何投资损失承担责任。
