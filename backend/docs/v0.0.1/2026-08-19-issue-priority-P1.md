# P1 级问题与解决方案（高优先级）

> 版本：v0.0.1
> 日期：2026-08-19
> 说明：P1 为高优先级问题——不影响"能否运行"，但影响结果正确性、可维护性与文档可信度，建议 1-2 周内完成。

---

## ISSUE-004 配置体系是死代码

### 问题

- `backend/src/config.yaml` 定义了数据源、股票池、佣金、模型路径等完整配置，但全项目无任何模块真正读取它。
- `utils/config.py` 的 `Config` 单例与 `infrastructure/config_manager.py` 的 `ConfigManager` 均无消费者。
- 各模块使用硬编码默认值（如 `Backtester` 佣金 0.0003、印花税 0.001；`DataFetcher` 固定 akshare）。

### 影响

配置文件形同虚设，参数分散在代码里，策略/风控参数无法统一管理和动态调整。

### 解决方案

1. 指定唯一配置入口（建议保留 `ConfigManager`，废除或合并 `utils/config.py` 单例）。
2. 为 `Backtester`、`RiskEngine`、`DataFetcher`、`TaskScheduler` 增加从配置读取参数的构造方式，硬编码只作默认值兜底。
3. 启动入口统一加载 `config.yaml`，并增加配置校验（`validate_config` 已具备雏形，需接线）。

---

## ISSUE-005 回测引擎正确性 bug 与功能缺口

### 问题（均位于 `backtest/backtester.py`）

1. 印花税双向收取：买入分支 `:86` 与卖出分支 `:107` 都计算 `stamp_tax = trade_value * self.stamp_tax`；A 股印花税仅卖出征收，回测收益系统性偏低。
2. 回撤未持久化：`calculate_metrics` 只在局部 `equity_df` 副本上计算 `peak`/`drawdown`（`:198-199`），`plot_results` 从 `self.equity_curve` 重建 DataFrame 后访问 `equity_df["drawdown"]`（`:278`），直接 `KeyError` 崩溃。
3. 死代码：`run()` 中 `:148` 的 `if "signal" in signals.columns: ... else: ...` 两个分支完全相同。
4. 功能缺口：无滑点模型、仅支持单标的、全仓进出、无基准对比、无多标的组合回测。
5. 接口脱节：`Backtester` 只消费预生成的 signal 列，`BaseStrategy.on_bar` 事件驱动接口从未被使用，策略对象与回测引擎没有真正联动。
6. 胜率算法缺陷：分批卖出时，`win_rate` 分母统计所有卖出记录，分子只统计数量完全匹配的卖出，结果失真。

### 影响

回测结果与真实交易成本结构不符；绘图功能存在必现崩溃；指标口径与实盘预期偏差大。

### 解决方案

1. 买入不再计印花税；佣金补充最低 5 元规则（可配置开关）。
2. 将 `peak`/`drawdown` 写入 `equity_curve` 每条记录，或让 `plot_results` 接受 `calculate_metrics` 的返回结果。
3. 删除死分支，信号合并改为按索引显式 `align`，防止索引错位。
4. 增加 `slippage`（bps）与 `benchmark` 参数；重构为可支持多标的组合账户（Position/Order 数据模型）。
5. 明确回测引擎输入契约：接受策略对象或 signal 序列二选一；移除未使用的 `on_bar` 或真正实现事件驱动模式。
6. 胜率改为按"完整买卖对"计算（配对平仓法），与 `execution/position_tracker.py` 的成本口径统一。
7. 指标计算与 `analysis/performance.py` 去重：回测引擎只输出交易流与权益曲线，绩效指标统一由 `PerformanceAnalyzer` 计算，避免两套口径漂移。

---

## ISSUE-006 存储层重复，职责不清

### 问题

- `data/storage.py`（`DataStorage`，CSV/SQLite）与 `storage/` 包（`Database` + `DataCache`，SQLAlchemy + 缓存）功能重叠。
- README 目录树写 `data/storage.py`，文字描述却引用 `storage/database.py`、`storage/data_cache.py`，文档自身矛盾。

### 影响

两套存储抽象并存，调用方不知选哪套；未来 schema 或缓存策略变更时双份维护，必然漂移。

### 解决方案

1. 合并为单一 `storage/` 层：CSV/Parquet 文件读写归入 `storage/`（文件存储适配器），SQLAlchemy 保持 `storage/database.py`，缓存归 `storage/data_cache.py`。
2. `data/` 模块只保留获取与清洗职责，删除 `data/storage.py` 或降级为对 `storage` 的薄封装。
3. 同步修正 README 目录树。

---

## ISSUE-007 数据源抽象名不副实

### 问题

- `data/fetcher.py` 声明支持 AKShare、Tushare，但 `self.source` 固定为 `"akshare"`，仅实现 akshare 调用；README 中 Tushare 支持为虚。
- `get_index_history` 对 `ak.stock_zh_index_daily` 传入 `"000001.SH"` 格式，与该接口实际要求（如 `"sh000001"`）不符，存在兼容隐患。
- `get_realtime_quote` 每次调用全量拉取行情快照再过滤，效率低。
- 数据获取失败时静默返回空 DataFrame，错误被吞掉。

### 影响

多数据源能力无法兑现；切换数据源需改代码；故障难以排查。

### 解决方案

1. 定义统一数据源接口（`BaseDataSource`），akshare/tushare 分别实现适配器，`DataFetcher` 按配置选择并支持回退。
2. 修复指数代码格式映射；失败时记录日志并抛出或返回带错误信息的对象，而不是静默空表。
3. 实时行情改为按代码查询或加缓存（复用 `DataCache`）。

---

## P1 验收标准

1. 修改 `config.yaml` 的佣金/回测区间/股票池后，回测行为随之改变。
2. 一次标准回测（买入→持有→卖出）的现金、持仓、费用与手算结果一致，且印花税仅卖出收取。
3. `plot_results` 可正常输出权益曲线、回撤图、持仓图。
4. 存储仅保留单一入口，`data/` 与 `storage/` 职责边界清晰。
5. 数据源可配置切换，获取失败有明确日志与错误返回。