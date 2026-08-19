# 项目审查问题与整改方案 — P2（中低优先级）

> 版本：v0.0.1（二次审查）
> 日期：2026-08-19
> 定位：个人、非高频量化框架
> 说明：P2 为中低优先级——不影响回测正确性，但影响工程卫生、维护成本与长期可扩展性，可在后续迭代处理。

---

## R-P2-01 项目未初始化 git，无版本管理

### 问题

- 项目根目录仍不是 git 仓库，无提交历史；
- `backend/.gitignore` 已存在且内容完整，但仓库未初始化，规则尚未生效。

### 影响

无法追踪变更、无法回滚；关键代码改动没有历史记录，对长期维护的个人项目风险大。

### 整改方案

```bash
cd quant_project
git init
git add backend/quant backend/docs backend/pyproject.toml backend/requirements*.txt
git commit -m "init: 量化框架基础版本 v0.0.1"
```

建议同时补充根目录 `.gitignore`（可复用 `backend/.gitignore` 内容），并在每次完成一个 P0/P1 整改项后单独提交，形成可回溯的整改记录。

---

## R-P2-02 README 与代码不同步

### 问题

- README 环境要求写 "Python 3.8+"，实际 `pyproject.toml` 要求 `>=3.10`，且代码使用了 3.10+ 特性；
- README 宣称支持 Tushare，实际为"规划中"实现（`TushareAdapter` 已建但需 token 且未验证）；
- README 目录树与实际结构不一致（如 `data/storage.py` 已改为薄封装、`storage/` 与 `data/` 职责已变化）；
- README 未体现"个人、非高频"定位与已修复/待修复状态。

### 影响

使用者按 README 操作会踩版本兼容坑；文档与代码脱节降低项目可信度。

### 整改方案

1. 环境要求改为 "Python 3.10+"；
2. Tushare 支持标注为"规划中（需配置 token）"；
3. 按当前 `backend/quant/` 实际结构重写目录树；
4. 在 README 开头补充定位说明："个人、非高频量化框架，周/日频调仓，核心链路为 数据 → 策略 → 回测 → 风控 → 执行"。

---

## R-P2-03 个人非高频场景下的模块过度建设

### 问题

以下模块对"个人、非高频"的使用场景属于超前建设，当前维护成本大于收益：

- `sentiment/`（新闻采集、情感分析、事件检测）：个人使用数据源不稳定、效果难以验证；
- `infrastructure/monitor.py`（CPU/内存/磁盘监控）：单机个人运行价值低；
- `infrastructure/api_server.py`：策略/持仓/回测 API 仍为内存示例，未接通真实链路；
- `execution/order_manager.py` 的订单拆分/合并/重试：非高频场景基本用不上。

### 影响

代码量大（约占全项目 40%），分散维护精力；示例 API 存在"看起来可用、实际不可用"的误导。

### 整改方案

1. 明确分层：`core/`（data、strategies、backtest、risk、portfolio、analysis）为当前维护重点；`ext/`（sentiment、execution、infrastructure）标注"预留/实验"；
2. API 模块要么接通真实回测/持仓链路，要么在文件头标注"示例，未接入生产"并移除误导性描述；
3. 非高频场景下订单管理建议只保留"下单 → 成交 → 记账"最小路径，拆分/重试逻辑可注释保留。

---

## R-P2-04 交易日历归属不清（utils 转发层）

### 问题

- `utils/calendar.py` 只是转发 `from quant.sentiment.calendar import TradingCalendar`，实现仍在 `sentiment/` 下；
- 交易日历属于市场基础设施工具，归属消息面模块语义不合理。

### 影响

模块语义混乱，未来维护者容易在错误的位置修改日历逻辑。

### 整改方案

1. 将 `TradingCalendar` 实现迁移到 `utils/calendar.py`（或新建 `market/` 模块），`sentiment/calendar.py` 改为反向转发以兼容旧引用；
2. 删除或废弃 `sentiment/__init__.py` 中可能的历史导出（当前未导出 calendar，无需改动）；
3. 更新 `utils/__init__.py` 注释与实际内容一致。

---

## R-P2-05 依赖清单双份维护

### 问题

- 核心依赖同时存在于 `backend/pyproject.toml` 的 `[project.dependencies]` 与 `backend/requirements.txt`；
- 两份清单目前内容基本一致，但未来改动容易只改一处，导致安装结果不一致。

### 影响

不同安装方式（`pip install -e .` vs `pip install -r requirements.txt`）得到不同依赖集，排查环境问题费时。

### 整改方案

二选一：

1. **推荐**：以 `pyproject.toml` 为唯一依赖源，删除 `requirements.txt`（或用 `requirements.txt` 仅固定版本：
   `pip install -e ".[dev]"` 与 `pip install -r requirements-dev.txt` 并存）；
2. 或保留双清单，但增加 CI 检查：对比两份文件内容一致（`pip-compile` 等工具可自动生成）。

---

## R-P2-06 空目录与占位文件

### 问题

`quant/` 下 `logs/`、`models/`、`notebooks/`、`scripts/` 仍为空目录；README 与文档把它们描述为既有模块。

### 影响

空目录造成"已实现"错觉，且无内容说明用途。

### 整改方案

1. 每个空目录补一个 `README.md` 说明用途与使用方式（例如 `models/` 说明模型文件存放规范）；
2. 或直接删除，待有实际内容再创建；
3. 检查 `backend/docs/` 与项目根 `docs/` 的职责划分，统一文档存放位置。

---

## P2 验收标准

1. 项目为 git 仓库，根目录与 backend 均有 .gitignore，整改过程有提交记录；
2. README 的环境要求、目录树、Tushare 支持状态与代码一致，并写明个人非高频定位；
3. 模块按 core/ext 分层标注清晰，示例 API 有明确标识；
4. 交易日历实现归属明确，无重复实现；
5. 依赖清单单一来源（或双清单一致且有检查机制）；
6. 空目录有说明或已清理。