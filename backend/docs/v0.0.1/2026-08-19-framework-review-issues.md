# 框架审查问题与整改方案（第三次审查）

> 版本：v0.0.1（第三次审查）
> 日期：2026-08-19
> 定位：个人、非高频量化框架，周/日频调仓
> 说明：本文件记录框架级审查发现的问题，按 P0（阻断级）/ P1（高优先级）/ P2（中低优先级）排序，每条包含问题、影响与整改建议。

---

## P0（阻断级）——不修复则核心链路不可用或回测结论不可外推

### R-FW-P0-01 数据层缺失，核心链路起点断裂

#### 问题

README 与既有审查文档均声明存在 `data/fetcher.py`（数据获取）与 `data/processor.py`（数据清洗/指标计算），但 `backend/quant/data/` 目录下只有空的 `raw/`、`processed/` 子目录，**没有任何 fetcher / processor 实现**。README 快速开始示例 `from data.fetcher import DataFetcher` 无法运行。

#### 影响

"数据 → 策略 → 回测"链路的第一步依赖外部手工塞入 DataFrame；P1 文档中针对 `data/processor.py` / `data/fetcher.py` 的问题描述（RSI 除零、3σ 删行、静默吞错、配置键脱节）全部落空，文档与代码脱节。项目名义上"从数据获取到实盘交易"，实际没有数据入口。

#### 整改建议

1. 实现最小可用的数据层：`fetcher.py`（akshare 拉取日线，支持批量与失败清单）、`processor.py`（基本清洗、常用技术指标、训练/测试切分）；
2. 或明确将数据层标记为"待实现"，删除/修正 README 中不存在的导入示例与目录树；
3. 无论哪种方案，README 快速开始必须与实际代码一致。

---

### R-FW-P0-02 执行层与回测层成本口径不一致（回测赚钱、实盘亏钱隐患）

#### 问题

- 回测器（`quant/backtest/backtester.py`）：佣金万三、最低 5 元、印花税**卖出单边收取万分之五**（与 config.yaml 及现行政策一致）；
- 模拟券商（`quant/execution/broker_adapter.py` `_calculate_commission`）：印花税**千分之一，且买入卖出都收**；
- 交易日志（`quant/execution/trade_logger.py` `_calculate_commission`）：印花税仍为**千分之一**；
- 上述费率全部硬编码，未从配置读取。

#### 影响

同一笔交易在回测与模拟/实盘路径成本相差一个数量级，回测收益无法外推到实盘；对低换手、大额单笔的交易影响相对较小，但对小资金、频繁交易的策略影响显著。

#### 整改建议

1. 统一为：佣金万三（最低 5 元）、印花税卖出单边万分之五、滑点从配置读取；
2. 三处费率统一从 `config.yaml`（`strategy.*`）读取；
3. 增加跨模块一致性测试：同一组交易数据，回测器、模拟券商、交易日志三者计算出的成本必须一致。

---

### R-FW-P0-03 回测 → 风控 → 执行未真正串联

#### 问题

`Backtester.run()` 是自包含的：信号直接进入 `execute_trade`，既不经过 `RiskEngine`，也不经过 `OrderManager` / `PositionLimitManager`。风控模块四个控制器（RiskEngine、PositionLimitManager、DrawdownController、ExposureMonitor）功能大量重叠（均在计算仓位比例、回撤阈值），但彼此独立、互不调用，也没有任何入口被回测主循环调用。

#### 影响

"多层风控"目前只是文档描述；实盘路径（OrderManager → RiskEngine）与回测路径是两套平行逻辑，回测中没有风控约束的验证，策略在回测中的换手/仓位行为无法代表实盘可执行性。

#### 整改建议

1. 为 `Backtester` 增加可选的风控钩子（至少接入"总仓位上限 + 单股仓位上限 + 回撤阈值"），拒绝信号或缩减仓位时记录原因；
2. 回测与实盘共享同一套 `RiskConfig` 来源；
3. 先打通"回测 → 风控 → 报告"最小闭环，再考虑订单拆分等高频特性。

---

### R-FW-P0-04 存储模块 SQLAlchemy 正常路径存在必现错误

#### 问题

`quant/storage/database.py` 的 `Database.get_session()` 直接访问 `self.simple_db`，但该属性只在降级路径 `_use_simple_db()` 中创建；当 SQLAlchemy 正常安装并连接成功时，属性不存在，首次调用即抛 `AttributeError`。

#### 影响

所有走 SQLAlchemy 路径的读写（行情、交易记录、回测结果持久化）全部不可用；现有 `test_storage.py` 只测了 CSV 往返，完全未覆盖 Database 类，问题不会被测试发现。

#### 整改建议

1. 在 `__init__` 中显式初始化 `self.simple_db = None`，并在 `get_session` 中判空；
2. 补测 SQLAlchemy 与简化版两条路径的读写；
3. 行情写入改为 upsert（当前 `bulk_save_objects` 重复保存会插入重复行）。

---

## P1（高优先级）——不影响能否运行，但影响可靠性、统计稳健性与维护成本

### R-FW-P1-01 配置体系三套并存，默认值不一致

#### 问题

存在三套配置加载实现：`quant/config.py`（ConfigManager 入口）、`quant/utils/config.py`（另一套 Config 单例）、`quant/infrastructure/config_manager.py`（底层实现）；`ConfigManager._init_default_config` 中内置默认印花税仍为 `0.001`，与 `config.yaml` 的 `0.0005` 不一致。

#### 影响

配置来源与默认值不统一，容易产生"改了配置没生效"或"换了入口默认值不同"的困惑，长期维护成本高。

#### 整改建议

1. 只保留 `quant/config.py` + `quant/infrastructure/config_manager.py` 一条链路，删除 `quant/utils/config.py`（或将其改为对前者的薄转发）；
2. 统一内置默认值，与 `config.yaml` 保持一致；
3. 配置加载后执行必填键校验，缺失时给出明确告警。

---

### R-FW-P1-02 依赖清单不全

#### 问题

代码中使用但未在 `pyproject.toml` 声明的依赖：`yaml`（config_manager 顶层 import）、`psutil`（monitor 顶层 import，未声明会直接导入失败）、`flask` / `flask-cors`（api_server）、`scipy`（optimizer，已做可选降级）、`snownlp` / `transformers`（sentiment，已做可选降级）。

#### 影响

按 README 安装基础依赖后，部分模块无法导入或功能受限；"看起来可用的示例模块"与"实际可用的模块"边界不清。

#### 整改建议

1. 基础依赖补充 `pyyaml`、`psutil`、`flask`、`flask-cors`；
2. `scipy`、`snownlp`、`transformers` 移入 optional extras；
3. 对可选依赖的 import 统一使用现有 try/except 降级模式。

---

### R-FW-P1-03 指标口径残留问题

#### 问题

- **Calmar 符号错误**：`quant/analysis/performance.py` 的 `_calculate_calmar_ratio` 为 `年化收益 / 最大回撤`；回撤统一为负值后，赚钱的策略 Calmar 也显示负数；
- **夏普定义不一致**：回测器 `calculate_metrics` 的夏普不含无风险利率，绩效分析器默认扣除 3% 无风险利率；
- **IC 方法学偏差**：`quant/analysis/factor_analysis.py` 的 IC 是对单只股票自身的时间序列做滚动相关再求平均；标准 IC 应为同一日期下的**截面相关**（股票间），当前实现方向需要调整。

#### 影响

同一策略在不同入口看到的风险指标不一致；因子有效性的结论可能失真。

#### 整改建议

1. Calmar 改为 `年化收益 / |最大回撤|`，并补单元测试；
2. 统一夏普口径（建议全项目默认扣除同一无风险利率，或明确文档说明差异）；
3. 因子分析改为按日期逐期计算截面 IC 后再统计均值/IR。

---

### R-FW-P1-04 报告链路字段断层

#### 问题

`Backtester.calculate_metrics` 返回结果中没有 `volatility`、`calmar_ratio`、`profit_loss_ratio`、`avg_holding_days`，交易记录中也没有 `symbol`、`amount` 字段；`ReportGenerator` 直接读取这些字段，生成报告时输出 0 / N/A。

#### 影响

HTML/Markdown 报告"看起来完整、实际缺数据"，降低报告可信度。

#### 整改建议

1. 回测结果补齐风险/交易统计字段（可由 PerformanceAnalyzer 计算后合并）；
2. 交易记录补 `symbol`、`amount`；
3. 增加报告生成快照测试，断言关键字段非空。

---

### R-FW-P1-05 组合层悬空：没有多标的回测引擎消费权重

#### 问题

`portfolio/optimizer.py` 与 `rebalancer.py` 能计算目标权重与再平衡计划，但 `Backtester` 只支持单标的、固定手数仓位；没有按权重构建组合并逐期再平衡的回测路径，优化结果无法被验证。

#### 影响

组合优化结论无法回测验证，"优化后上线"的链路断裂；对周/日频调仓的个人框架，组合级回测是核心场景之一。

#### 整改建议

1. 新增按目标权重执行的多标的回测入口（复用现有成本模型与信号延迟机制）；
2. 或至少提供"权重 → 每日组合收益"的净值合成工具，作为优化器输出的验证层。

---

## P2（中低优先级）——不影响正确性，但影响工程卫生与可维护性

### R-FW-P2-01 README 与代码脱节

#### 问题

- 快速开始示例导入路径缺少 `quant.` 前缀（`from data.fetcher import ...` 安装后无法导入，且 fetcher 本身不存在）；
- 目录树包含不存在的 `data/storage.py`；
- 安装说明引用不存在的 `requirements.txt`（实际只有 `requirements-dev.txt`）。

#### 整改建议

按实际代码重写 README 的快速开始与目录树；`pip install -e ".[dev]"` 作为唯一安装方式。

---

### R-FW-P2-02 测试覆盖不足

#### 问题

现有测试仅覆盖策略、回测器、优化器、绩效、风控基础与 CSV 存储；数据层（待实现）、执行层（broker/order/position）、Database 类、报告生成、路径解析均无测试。

#### 整改建议

优先补齐执行层成本一致性、Database 双路径、路径解析三组测试；每项整改配套对应单元测试。

---

### R-FW-P2-03 代码卫生问题

#### 问题

- `quant/risk/position_limits.py` 存在中英文混合方法名 `get_rebalance寤鸿`；
- `MLStrategy.train` 的 `tune_hyperparams` 参数与 `GridSearchCV` 导入未使用；
- `TaskScheduler` 定义了 `CRON` 类型但未实现；
- `backend/quant/` 下 `logs/`、`models/`、`notebooks/`、`scripts/` 为空目录，README 却将其描述为已有模块；
- `DataCache._estimate_size` 中使用了未导入的 `sys`（pickle 失败时会 NameError）。

#### 整改建议

清理死代码与空目录（或补 README 说明），修正方法名与缺失 import。

---

## 验收标准

1. 执行层与回测层成本口径一致（佣金/印花税/滑点同源），跨模块成本一致性测试通过；
2. 回测主循环可挂载风控钩子，仓位/回撤规则生效并有日志；
3. Database 的 SQLAlchemy 与简化路径均可正常读写，测试覆盖；
4. 配置单源化，内置默认值与 config.yaml 一致；
5. 依赖清单与代码 import 一致（基础依赖 + 可选 extras）；
6. Calmar/夏普/IC 口径统一或有明确文档说明，指标单元测试通过；
7. 报告生成关键字段非空；
8. README 快速开始可直接运行；
9. 数据存储目录（tmp / raw / processed）可通过 config.yaml 配置并生效。
