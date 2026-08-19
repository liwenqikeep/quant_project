---
name: quant-backend
description: 本仓库后端 quant 包的开发与修改规范：模块分层与依赖方向、回测/风控/数据链路正确性红线、Python 代码风格（Ruff）、测试与配置要求。修改 backend/quant 下代码时必须使用。
---

# quant-backend — 后端量化开发规范

本技能是 backend/quant/ 的唯一开发规范，配合根目录 AGENTS.md 使用。开始任何后端改动前完整阅读本文件。

## 1. 适用范围

- backend/quant/** 下所有 Python 代码：新增、修改、重构、测试。
- 涉及 HTTP API 的改动：同时阅读 docs/api-integration.md 并保持契约同步。

## 2. 架构约束（MUST）

依赖方向单向：data → strategies → backtest → risk → execution。

- 分层：core（data / strategies / backtest / risk / portfolio / analysis / storage / utils）为维护重点；ext（execution / infrastructure / sentiment）为预留/实验，改动须在提交说明写明理由。
- 跨模块只经公共导出（__init__.py 或公开类/函数）交互，禁止导入内部私有符号。
- 新策略继承 strategies.base_strategy.BaseStrategy，信号列约定 1=买入 / -1=卖出 / 0=持有。
- 新数据源实现 data.base_data_source.BaseDataSource（get_stock_history / is_available）。
- 风控扩展基于 risk.risk_engine.RiskEngine；数据载体优先 dataclass。
- 配置驱动：费率/阈值/路径/端口等一律来自 config.yaml（quant.config.get_config），新增配置同步 config.yaml、ConfigManager 默认值与必填键校验。
- 基础设施归属：交易日历等放 utils，禁止业务模块重复实现。
- 依赖唯一来源 backend/pyproject.toml，新依赖须评估必要性并按 dev/ext/ml/sentiment 分组。

## 3. 回测与风控正确性红线

1. 禁止未来函数：信号 t 日收盘生成、t+1 执行，Backtester 默认 execution_price="next_open"，信号必须 shift(1)。
2. 成本口径统一：佣金、最低佣金（5 元）、滑点、印花税（卖出单边 0.0005）从配置读取；回测、风控、模拟经纪三处必须一致。
3. 指标口径统一：最大回撤统一为负值；夏普等由 analysis.performance.PerformanceAnalyzer 提供公共实现，禁止各模块各算一套。
4. 交易记录字段完整：date/symbol/side/price/amount/pnl/commission；回测结果含 volatility/calmar_ratio/profit_loss_ratio/avg_holding_days/total_cost_ratio，可直接喂给绩效分析与报告生成。
5. 数据获取失败必须抛 DataFetchError 或返回失败清单，禁止静默返回空 DataFrame。
6. 数据清洗禁止删除时间行，异常值用 winsorize 截尾。
7. ML 策略禁止标签泄漏：切分边界两侧各丢弃一天，实盘前做 walk-forward 验证。
8. 组合优化约束不可行时必须显式报错或自动放宽，禁止静默 clip+归一化掩盖。

## 4. Python 代码风格（Ruff）

- 工具：ruff 统一 lint + format，配置见 backend/pyproject.toml 的 [tool.ruff]（line-length 100，target py310）。
- 新代码必须通过 `ruff check .`（0 error）与 `ruff format --check .`；存量告警由专门的卫生任务清理，不阻塞无关功能。
- 类型标注：公共函数/方法必须有完整参数与返回值类型，优先 PEP 604（X | None）；数据载体用 dataclass。
- Docstring：中文，Google 风格（Args/Returns/Raises）；模块头说明模块用途。
- 命名：类 PascalCase、函数/变量 snake_case、常量 UPPER_SNAKE、私有 _x。
- import：标准库 → 第三方 → 本包，分组排序；禁止 import *。
- 日志：一律 quant.utils.logger，禁止 print；错误日志带上下文（symbol/task_id 等）。
- pandas：兼容 2.x/3.x，禁止已移除 API（如 Series.replace(method=...)）；禁止链式赋值；列名小写 snake_case。
- 禁止：裸 except、except: pass、assert 代替校验、可变默认参数、魔法数字、超长行。

## 5. 测试要求（MUST）

- 每个功能/修复配套测试（backend/quant/tests/test_*.py），覆盖正常路径 + 边界（空数据/除零/失败路径/极端行情）。
- 跨模块口径必须有专门测试（成本一致性、指标一致性、回测→报告链路）。
- 提交前在 backend 下运行 pytest 全量，必须全绿且存量用例无回归。

## 6. 提交约定

- 一个功能/一个整改项一个 commit；信息用 conventional commits（feat/fix/test/docs/style/refactor）。
- 不提交日志、缓存、数据、密钥、模型文件。
- 涉及接口变更：先改 docs/api-integration.md 再改代码。
