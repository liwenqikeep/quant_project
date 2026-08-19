# 量化交易系统

**定位：个人、非高频量化框架，周/日频调仓**

核心链路：数据 → 策略 → 回测 → 风控 → 执行

一个完整的模块化量化交易框架，支持从数据获取、策略开发、回测仿真到实盘交易的完整流程。

## 完整架构

系统包含以下核心模块：

### 1. 数据模块（data/）

负责数据的获取、清洗和存储。

**fetcher.py** - 数据获取
- 单只/批量股票历史数据获取
- 指数数据获取
- 实时行情获取
- 支持 AKShare、Tushare 等数据源

**processor.py** - 数据处理
- 技术指标计算（MA、EMA、MACD、RSI、布林带、KDJ）
- 价格/成交量特征工程
- 数据清洗与异常值处理
- 训练/测试集分割

**storage/database.py** - 数据持久化
- SQLAlchemy ORM 支持
- 股票数据、交易记录存储
- 回测结果存档

**storage/data_cache.py** - 数据缓存
- 内存缓存（LRU 策略）
- 磁盘缓存
- TTL 过期管理

### 2. 策略模块（strategies/）

策略开发和执行框架。

**base_strategy.py** - 策略基类
- 抽象接口设计
- 交易信号生成方法
- 持仓状态管理

**ma_strategy.py** - 均线策略
**macd_strategy.py** - MACD 策略
**rsi_strategy.py** - RSI 策略
**ml_strategy.py** - 机器学习策略

### 3. 回测模块（backtest/）

**backtester.py** - 回测引擎
- 交易模拟（买入/卖出/费用计算）
- 绩效指标计算（收益率、夏普比率、最大回撤、胜率）
- 可视化分析（权益曲线、回撤图）

### 4. 风控模块（risk/）

交易风险控制核心模块。

**risk_engine.py** - 风控引擎
- 订单风控校验
- 资金/仓位检查
- 回撤/波动率限制
- 杠杆控制

**position_limits.py** - 仓位限制
- 单股/行业/市值风格限制
- 黑名单管理
- 再平衡建议

**drawdown_control.py** - 回撤控制
- 动态仓位调整
- 回撤预警（正常→注意→警告→危险→强平）
- 自动减仓机制

**exposure_monitor.py** - 敞口监控
- 市场/行业/风格敞口跟踪
- 流动性风险监控
- Beta/波动率敞口管理

### 5. 交易执行模块（execution/）

从回测到实盘的桥梁。

**broker_adapter.py** - 券商适配器
- 统一交易接口
- 模拟券商（用于回测）
- 订单/成交/持仓管理

**order_manager.py** - 订单管理器
- 订单拆分与合并
- 风控集成
- 执行统计

**position_tracker.py** - 持仓追踪
- 实时持仓监控
- 成本/盈亏计算
- 交易历史记录

**trade_logger.py** - 交易日志
- 交易记录存档
- 审计追踪
- 统计分析

### 6. 消息面模块（sentiment/）

基本面和事件驱动分析。

**news_collector.py** - 新闻采集
- 财经新闻获取
- 公告信息采集
- 新闻缓存管理

**sentiment_analyzer.py** - 情感分析
- 基于规则/机器学习的情感分析
- 方面情感提取
- 交易信号生成

**event_detector.py** - 事件检测
- 涨跌停检测
- 重大新闻识别
- 大宗交易监控

**calendar.py** - 交易日历
- 交易日判断
- 节假日管理
- 日历查询

### 7. 组合管理模块（portfolio/）

多策略组合优化。

**optimizer.py** - 组合优化器
- 均值方差优化
- 最小方差组合
- 最大夏普组合
- 风险平价策略
- 最大分散化

**rebalancer.py** - 再平衡器
- 定期/阈值/混合触发
- 换手率控制
- 成本估算

**correlation_tracker.py** - 相关性跟踪
- 动态相关性计算
- 高相关对识别
- 分散化收益评估

### 8. 分析报告模块（analysis/）

策略绩效评估和报告生成。

**performance.py** - 绩效分析
- 收益率/波动率/夏普比率
- 最大回撤/卡玛比率
- 胜率/盈亏比
- Alpha/Beta/信息比率

**factor_analysis.py** - 因子分析
- IC/IR 计算
- 分组回测
- 因子有效性评估

**report_generator.py** - 报告生成
- HTML 格式报告
- Markdown 格式报告
- 策略对比报告

### 9. 基础设施模块（infrastructure/）

系统运行支撑。

**api_server.py** - API 服务器
- RESTful API
- 策略/持仓/回测接口
- Flask 框架支持

**scheduler.py** - 定时任务
- 周期任务调度
- 每日定时任务
- 任务状态管理

**monitor.py** - 系统监控
- CPU/内存/磁盘监控
- 策略运行状态跟踪
- 告警管理

**config_manager.py** - 配置管理
- YAML/JSON 配置
- 动态配置更新
- 配置验证

## 项目结构

```
quant_project/
├── backend/
│   └── quant/                    # 核心模块
│       ├── analysis/             # 分析报告 [core]
│       │   ├── performance.py
│       │   ├── factor_analysis.py
│       │   ├── report_generator.py
│       │   └── __init__.py
│       ├── backtest/            # 回测引擎 [core]
│       │   ├── backtester.py
│       │   └── __init__.py
│       ├── data/                # 数据模块 [core]
│       │   ├── fetcher.py
│       │   ├── processor.py
│       │   ├── storage.py
│       │   └── __init__.py
│       ├── execution/            # 交易执行 [ext/预留]
│       │   ├── broker_adapter.py
│       │   ├── order_manager.py
│       │   ├── position_tracker.py
│       │   ├── trade_logger.py
│       │   └── __init__.py
│       ├── infrastructure/      # 基础设施 [ext/预留]
│       │   ├── api_server.py
│       │   ├── scheduler.py
│       │   ├── monitor.py
│       │   ├── config_manager.py
│       │   └── __init__.py
│       ├── portfolio/           # 组合管理 [core]
│       │   ├── optimizer.py
│       │   ├── rebalancer.py
│       │   ├── correlation_tracker.py
│       │   └── __init__.py
│       ├── risk/                # 风控模块 [core]
│       │   ├── risk_engine.py
│       │   ├── position_limits.py
│       │   ├── drawdown_control.py
│       │   ├── exposure_monitor.py
│       │   └── __init__.py
│       ├── sentiment/            # 消息面 [ext/实验]
│       │   ├── news_collector.py
│       │   ├── sentiment_analyzer.py
│       │   ├── event_detector.py
│       │   ├── calendar.py
│       │   └── __init__.py
│       ├── strategies/           # 策略模块 [core]
│       │   ├── base_strategy.py
│       │   ├── ma_strategy.py
│       │   ├── macd_strategy.py
│       │   ├── rsi_strategy.py
│       │   ├── ml_strategy.py
│       │   └── __init__.py
│       ├── storage/             # 数据存储 [core]
│       │   ├── database.py
│       │   ├── data_cache.py
│       │   └── __init__.py
│       ├── utils/               # 工具模块 [core]
│       │   ├── config.py
│       │   ├── logger.py
│       │   ├── calendar.py      # 交易日历（转发到 sentiment）
│       │   └── __init__.py
│       ├── tests/               # 测试
│       ├── config.yaml
│       └── pyproject.toml
├── docs/                        # 文档
├── AGENTS.md
└── README.md

# 模块分层说明
# [core]   - 当前维护重点
# [ext]    - 预留/实验模块
```

## 环境要求

- **Python 3.10+**（需要 pandas 3.x 支持）
- pandas >= 2.0.0（推荐最新版本）
- numpy >= 1.24.0
- akshare >= 1.13.0（默认数据源）
- matplotlib >= 3.7.0
- scikit-learn >= 1.3.0
- sqlalchemy >= 2.0.0
- Tushare 支持：规划中（需配置 token）

## 安装

```bash
cd backend
pip install -e ".[dev]"  # 安装项目及开发依赖
# 或
pip install -r requirements.txt
```

## 快速开始

### 数据获取与回测

```python
from data.fetcher import DataFetcher
from data.processor import DataProcessor
from strategies.ma_strategy import MAStrategy
from backtest.backtester import Backtester

# 获取数据
fetcher = DataFetcher()
df = fetcher.get_stock_history("000001.SZ", "20200101", "20231231")

# 处理数据
processor = DataProcessor()
df_processed = processor.process_stock_data(df)

# 生成信号
strategy = MAStrategy(short_window=10, long_window=30)
signals = strategy.generate_signals(df_processed)

# 回测
backtester = Backtester(initial_cash=1000000)
results = backtester.run(df_processed, signals)

print(f"总收益: {results['total_return']:.2%}")
print(f"夏普: {results['sharpe_ratio']:.2f}")
```

### 完整策略运行（含风控）

```python
from risk.risk_engine import RiskEngine
from execution.broker_adapter import SimulatedBroker
from execution.order_manager import OrderManager

# 初始化组件
broker = SimulatedBroker(initial_cash=1000000)
risk_engine = RiskEngine()
order_manager = OrderManager(broker, risk_engine)

# 策略信号 -> 订单 -> 风控 -> 执行
# ...完整流程参见各模块示例
```

### 生成分析报告

```python
from analysis.performance import PerformanceAnalyzer
from analysis.report_generator import ReportGenerator

analyzer = PerformanceAnalyzer()
metrics = analyzer.analyze(equity_curve)

generator = ReportGenerator()
report_path = generator.generate_backtest_report(
    "均线策略",
    results
)
```

## 核心特性

- **完整链路**：从数据到策略到执行，覆盖量化交易全流程
- **模块化设计**：各模块独立，可按需组合使用
- **风控优先**：内置多层风控机制，保障资金安全
- **灵活扩展**：基类设计便于开发新策略和新功能
- **可视化报告**：自动生成绩效分析图表和 HTML 报告
- **配置驱动**：通过 YAML/JSON 配置文件管理所有参数

## 扩展开发

### 开发新策略

```python
from strategies.base_strategy import BaseStrategy
import pandas as pd

class MyStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="MyStrategy")
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        signals = pd.DataFrame(index=data.index)
        # 策略逻辑
        signals['signal'] = 0  # 1买入, -1卖出, 0持有
        return signals
```

### 添加新数据源

在 `data/fetcher.py` 中扩展数据获取方法，或实现新的 Fetcher 类。

### 自定义风控规则

继承 `RiskEngine` 类，扩展 `check_order` 方法添加自定义风控逻辑。
