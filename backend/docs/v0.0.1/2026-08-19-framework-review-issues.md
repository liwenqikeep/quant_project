# 框架审查问题与整改方案（第三次审查）

> 版本：v0.0.1（第三次审查，2026-08-19 复核更新）
> 定位：个人、非高频量化框架，周/日频调仓
> 说明：本文档为问题清单 + 整改方案 + 验收标准。实施方按本文档逐项整改，每项均须配套测试；验收不通过不得视为完成。

---

## 一、复核状态总表（2026-08-19）

| 编号 | 问题 | 复核状态 | 说明 |
|------|------|----------|------|
| R-FW-P0-01 | 数据层缺失 | ✅ 基本修复 | fetcher/processor/storage/数据源适配器已实现；data/ 目录未纳入 git，README 未同步，无测试 |
| R-FW-P0-02 | 执行层与回测层成本口径不一致 | ✅ 口径统一 | 三处印花税均为卖出单边万五；费率仍硬编码未配置化，无跨模块一致性测试 |
| R-FW-P0-03 | 回测→风控→执行未串联 | ✅ 机制具备 | Backtester 支持 risk_hook 并记录拒绝原因；无默认规则、无测试 |
| R-FW-P0-04 | 存储模块 SQLAlchemy 必现错误 | ✅ 已修复 | simple_db 显式初始化并判空；无 upsert、无双路径测试 |
| R-FW-P1-01 | 配置体系三套并存 | ⚠️ 部分修复 | utils/config.py 已改转发、印花税默认值统一；validate_config 必填键仍是旧键且无调用点，内置默认 data 段仍为旧键结构 |
| R-FW-P1-02 | 依赖清单不全 | ⚠️ 部分修复 | pyyaml/psutil 已补，flask/scipy/snownlp 已分组；transformers 被 import 但未声明 |
| R-FW-P1-03 | 指标口径残留 | ⚠️ 部分修复 | Calmar 已改为 abs()；夏普两处口径仍不一致，IC 仍为单序列滚动相关 |
| R-FW-P1-04 | 报告链路字段断层 | ❌ 未修复 | 回测结果缺 volatility/calmar/盈亏比/平均持仓，交易记录缺 symbol/amount |
| R-FW-P1-05 | 组合层悬空（无多标的回测） | ❌ 未修复 | 仅有单标的 backtester |
| R-FW-P2-01 | README 与代码脱节 | ❌ 未修复 | 安装命令引用不存在的 requirements.txt；快速开始导入路径无 quant. 前缀 |
| R-FW-P2-02 | 测试覆盖不足 | ⚠️ 部分修复 | 已补 test_paths；数据层/执行层/Database/报告/风控钩子仍无测试 |
| R-FW-P2-03 | 代码卫生 | ⚠️ 部分修复 | 中文方法名已改、sys 导入已补、空目录已补 README；ML 死代码、CRON 未实现仍存在 |
| R-FW-EXT-01 | 数据存储目录可配置（tmp/raw/processed） | ✅ 已修复 | config.yaml + paths.py + 四个存储点接入 + test_paths 已提交 |

---

## 二、待实施整改项（R1–R8）

### R1 配置校验与新结构对齐（P1-01 遗留）

**问题**：`quant/infrastructure/config_manager.py` 的 `validate_config` 必填键仍为旧键 `data.raw_data_path` / `data.processed_data_path`，与 config.yaml 的新结构（data_dir + tmp_dir/raw_dir/processed_dir）脱节；且该方法无调用点，形同虚设。`_init_default_config` 的 data 段也仍是旧键结构。

**要求**：
1. `required_keys` 改为新结构：`data.data_dir`、`data.tmp_dir`、`data.raw_dir`、`data.processed_dir`、`strategy.initial_cash`、`strategy.commission`、`strategy.stamp_tax`；
2. `_init_default_config` 的 data 段与 config.yaml 结构一致（含 data_dir/tmp_dir/raw_dir/processed_dir）；
3. `validate_config` 需被实际调用（建议在 ConfigManager 加载配置后执行，缺失必填键时输出 warning 并给出明确键名）。

**验收**：加载当前 config.yaml 后 `validate_config()` 返回空列表、无"缺失必填键"告警；内置默认配置结构 == config.yaml 结构。

---

### R2 依赖补全（P1-02 遗留）

**问题**：`quant/sentiment/sentiment_analyzer.py` 顶层 import `transformers`（有降级处理），但 `pyproject.toml` 的 sentiment extras 未声明。

**要求**：sentiment extras 增加 `transformers`；保持现有 try/except 降级模式。

**验收**：`pyproject.toml` 语法正确，sentiment extras 包含 transformers；未声明依赖仅剩无 import 的项。

---

### R3 指标口径统一（P1-03 遗留）

**问题**：
- 夏普：回测器 `Backtester.calculate_metrics` 使用 `returns.mean()/returns.std()*sqrt(252)`（无风险利率为 0）；`PerformanceAnalyzer._calculate_sharpe_ratio` 默认扣除 3% 无风险利率，两处结果不可比；
- IC：`quant/analysis/factor_analysis.py` 的 `calculate_ic` 是对单只股票自身时间序列做 rolling(20).corr，标准 IC 应为同一日期下股票间的截面相关。

**要求**：
1. 夏普口径统一：抽取公共定义（推荐由 PerformanceAnalyzer 提供 `calculate_sharpe(returns, risk_free_rate)`），回测器与其使用同一默认值（0.03 或保持 0 二选一，但必须一致且文档注明）；存量测试如断言具体值需同步更新并说明；
2. IC 增加截面算法：对 `factor_data`（日期×股票）与 `forward_returns`（日期×股票）按日计算 cross-sectional 相关，再统计均值/标准差/IR；保留原单序列接口不破坏兼容；
3. 两者均补单元测试。

**验收**：同一收益序列，回测器与绩效分析器夏普一致；截面 IC 用例与手算一致；pytest 全绿。

---

### R4 报告链路字段补齐（P1-04）

**问题**：回测结果缺 `volatility`、`calmar_ratio`、`profit_loss_ratio`、`avg_holding_days`，交易记录缺 `symbol`、`amount`，`ReportGenerator` 输出 0/N/A。

**要求**：
1. `Backtester.calculate_metrics` 结果补充上述字段（可调用/复用 PerformanceAnalyzer 计算，避免两处各算一遍）；
2. 交易记录补充 `symbol`（Backtester 增加可选的 `symbol` 参数，默认空串）与 `amount`；
3. `ReportGenerator` 增加一次完整回测→生成 HTML/Markdown 的测试，断言关键字段非空且非 0 占位。

**验收**：完整回测生成的 HTML 报告中 volatility/calmar/盈亏比/平均持仓/交易金额均为真实值；测试覆盖。

---

### R5 多标的组合回测入口（P1-05）

**问题**：`portfolio/optimizer.py` 与 `rebalancer.py` 产出权重/再平衡计划，但没有消费权重的回测引擎。

**要求**（最小可用范围，避免过度设计）：
1. 新增组合回测功能（建议放 `quant/backtest/portfolio_backtester.py`）：输入多标的日收盘价/收益 + 目标权重序列（或定期再平衡计划），输出组合净值曲线与基础绩效指标；
2. 换仓按 t+1 执行并扣除成本（复用现有佣金/印花税/滑点口径）；至少支持"定期再平衡"触发方式，可复用 `portfolio/rebalancer.py`；
3. 提供单元测试：手工构造两组权重/收益，断言组合收益与手算一致；成本扣减断言。

**验收**：示例/测试可运行；组合净值与手算基准一致；与单标的 backtester 成本口径一致。

---

### R6 README 修正（P2-01）

**问题**：README 安装命令引用不存在的 `requirements.txt`；快速开始导入路径 `from data.fetcher import ...` 无 `quant.` 前缀且与包结构不符；目录树与实际不一致。

**要求**：README 与当前代码完全对齐：
1. 安装方式统一为 `pip install -e ".[dev]"`；
2. 快速开始改为 `from quant.data.fetcher import DataFetcher`、`from quant.data.processor import DataProcessor`、`from quant.backtest.backtester import Backtester` 等实际路径；
3. 目录树按 `backend/quant/` 实际结构更新（data/、storage/ 等）。

**验收**：按 README 从零操作可走通"获取数据 → 处理 → 策略 → 回测 → 报告"。

---

### R7 测试补强（P2-02）

**要求**（至少覆盖以下四组，每组独立测试文件或测试类）：
1. 数据层：fetcher 使用 mock/假适配器验证重试、失败清单、DataFetchError；processor 验证技术指标（RSI 极值、KDJ 除零）、clean_data 不删时间行、winsorize；
2. 执行层成本一致性：同一笔买入/卖出，回测器、SimulatedBroker、TradeLogger 计算的手续费完全一致；
3. Database 双路径：SQLAlchemy（sqlite 内存/临时文件）与 SimpleDatabase 读写回环；
4. Backtester risk_hook：钩子拒绝信号时记录 risk_rejections、不成交、结果包含拒绝记录。

**验收**：新增用例全部通过且纳入 pytest 全量。

---

### R8 代码卫生收尾（P2-03 遗留）

**问题**：`MLStrategy.train` 的 `tune_hyperparams` 参数与 `GridSearchCV` 导入未使用；`TaskScheduler` 定义 `CRON` 类型但未实现。

**要求**：
1. ML 策略：实现 `tune_hyperparams=True` 时的 GridSearchCV 调参，或移除该参数与导入（二选一，倾向实现）；
2. 调度器：实现 CRON 任务执行，或移除 `CRON` 枚举（二选一，倾向移除并注明）。

**验收**：无未使用导入；pytest 全绿；行为变化有测试或文档说明。

---

## 三、全局约束

1. 不改动本文档；不改动与本批整改无关的模块行为；
2. 遵循现有代码风格：dataclass/enum、`quant.utils.logger` 日志、类型标注；
3. 每项整改必须配套测试；**存量测试必须全部继续通过**（回归红线）；
4. 不提交 git；不删除已有文件除非必要并说明；
5. 完成前必须运行 `pytest` 全量并汇报结果；如环境缺依赖，需先安装或明确说明阻塞原因；
6. 逐项汇报：R 编号、改动文件、测试结果、遗留问题；不得交付半成品。

---

## 四、验收标准

1. R1–R8 逐项通过代码审查（结构、口径、风格）；
2. `pytest` 全量通过（含新增用例），且存量用例无回归；
3. 快速功能验收：配置校验无告警、成本一致性用例通过、组合回测与手算一致、报告字段非空、README 示例路径可导入；
4. 任一 R 不通过 → 打回整改，直到通过。
