# AGENTS.md — 量化交易系统 AI 协作规范

> 版本 v0.1.0 ｜ 2026-08-19 ｜ 适用：在本仓库内工作的所有 AI 代理
> 项目定位：个人、非高频量化框架，周/日频调仓
> 核心链路：数据 → 策略 → 回测 → 风控 → 执行

---

## 1. 项目做什么

个人量化交易回测框架。后端 Python 实现完整模块化链路（数据、策略、回测、风控、组合、分析、存储），前端处于规划阶段，**暂不实施前端规范，保留口子**（见第 8 节）。

- 后端：`backend/quant/`，配置 `backend/quant/config.yaml`，依赖唯一来源 `backend/pyproject.toml`
- 文档分工：根 `docs/` 放跨前后端文档（如联调契约）；`backend/docs/v0.0.1/` 放后端审查与整改记录
- 当前状态：v0.0.1，已完成三轮框架审查及 P0/P1/P2、R1-R8 整改，回测/风控/数据链路红线已在代码中落实

## 2. 角色与职责

AI 接手任务时先明确当前扮演的角色；跨角色任务按顺序完成各角色动作，产出物各自留档。

| 角色 | 职责 | 产出物 |
|------|------|--------|
| 需求提出者（量化分析师） | 把投资想法转成结构化需求：目标、标的范围、周期、信号定义、绩效指标、验收条件 | 需求文档（含可量化的回测验收指标） |
| 产品经理（量化技术负责人） | 评审需求可行性、拆解任务、定义强制约束与优先级、最终验收 | 任务清单、验收结论 |
| 开发（量化开发） | 分前后端：后端 Python 实现 + 测试 + 日志；前端暂缓（见第 8 节） | 代码、测试、提交记录 |
| 测试（回测） | 对需求做回测验证、指标口径复核、回归测试、出报告 | 回测报告、pytest 结果 |

每轮需求的标准流程：

1. 分析师产出需求（含验收指标，如“夏普 > 1.2、最大回撤 < 15%、t+1 执行、成本含佣金/滑点/印花税”）；
2. 技术负责人评审并拆解，标注影响模块（core/ext）与强制约束；
3. 开发实现，遵守第 4、5 节与第 6 节对应技能；
4. 测试执行回测验证与 pytest 全量，按第 4 节红线复核口径；
5. 技术负责人验收：pytest 全绿 + 回测指标达标 + 无回归，方可结束。

## 3. 架构现状（改动前必读）

模块分层（`backend/quant/`）：

- core（当前维护重点）：`data`、`strategies`、`backtest`、`risk`、`portfolio`、`analysis`、`storage`、`utils`
- ext（预留/实验）：`execution`、`infrastructure`（api_server/scheduler/monitor）、`sentiment`；改动须说明理由，禁止把示例代码描述为已接入生产
- 配置体系：`config.yaml` → `quant.config.get_config(key, default)`，`ConfigManager` 加载时校验必填键
- 日志：`quant.utils.logger`（loguru 优先，标准库兜底）；路径：`quant.utils.paths` + 配置 `data.data_dir`

## 4. 强制要求（MUST，违反即打回）

### 4.1 环境管理（conda）

- Python 环境统一由 conda 管理，环境名固定为 `quant_project`；禁止使用其他环境名或系统 Python 直接安装/运行项目依赖。
- 环境不存在时必须先创建：`conda create -n quant_project python=<版本> -y`；Python 版本必须满足 `backend/pyproject.toml` 的 `requires-python`（当前 `>=3.10`）。
- 环境存在时必须先激活：`conda activate quant_project`；所有 `python` / `pip` / `pytest` / `ruff` 等命令一律在激活后的环境下执行。
- 本要求同样适用于沙箱（sandbox）：沙箱内执行任何命令前，必须先确认已处于 `quant_project` 环境，禁止以基础环境或其他环境代替。
- 依赖安装统一在激活 `quant_project` 后执行：`cd backend && pip install -e ".[dev]"`（依赖唯一来源 `backend/pyproject.toml`）。
- 可用 `conda env list` 或 `python -c "import sys; print(sys.prefix)"` 校验当前环境；不一致时先切换再继续，不得跳过。

### 4.2 分层与依赖

- 数据流单向：`data → strategies → backtest → risk → execution`，禁止反向依赖与跨层直达。
- 跨模块只通过公共导出交互，禁止导入内部私有符号。
- core 之外模块改动需写明理由；ext 模块保持“预留/实验”标注。

### 4.3 抽象与扩展

- 新策略必须继承 `strategies/base_strategy.py:BaseStrategy`；新数据源必须实现 `data/base_data_source.py:BaseDataSource`；风控扩展基于 `risk/risk_engine.py:RiskEngine`。
- 数据载体优先 dataclass，枚举用 enum，禁止公共接口返回裸 dict。

### 4.4 配置驱动

- 费率、阈值、路径、端口、时间范围等参数一律从 `config.yaml` 读取，禁止硬编码魔法数字。
- 新增配置必须三处同步：`config.yaml`、`ConfigManager` 默认配置、必填键校验。

### 4.5 回测正确性红线

- 禁止未来函数：信号 t 日收盘产生，t+1 执行，默认 `execution_price="next_open"`，信号必须 shift(1)。
- 成本口径统一：佣金、最低佣金（5 元）、滑点、印花税（卖出单边 0.0005）从配置读取；回测、风控、模拟经纪必须一致。
- 指标口径统一：最大回撤统一为负值；夏普等指标由 `PerformanceAnalyzer` 提供公共实现，禁止各模块各算一套。
- 回测结果字段完整，可直接喂给绩效分析与报告生成；交易记录含 symbol/amount/side/pnl。
- 组合优化约束不可行必须显式报错或自动放宽；ML 策略禁止标签泄漏，实盘前做 walk-forward。

### 4.6 数据与错误处理

- 数据获取失败必须抛 `DataFetchError` 或返回失败清单，禁止静默返回空 DataFrame。
- 数据清洗禁止删除时间行（破坏序列连续性），异常值用 winsorize 截尾。
- 禁止裸 except 与 `except: pass`；异常须带上下文并记日志。

### 4.7 测试与提交

- 每个功能/修复必须配套测试，覆盖正常路径 + 边界（空数据/除零/失败路径/极端行情）。
- 合入前 `pytest` 全量必须通过，存量用例不得回归。
- 一个功能/整改项一个 commit，信息用 conventional commits（feat/fix/test/docs/style/refactor）。
- 不提交日志、缓存、数据、密钥、模型文件（`.gitignore` 已覆盖，提交前确认）。

## 5. 代码风格（Python，当前主流工具链）

- 工具链：Ruff 统一 lint + format（配置见 `backend/pyproject.toml` 的 `[tool.ruff]`；line-length 100，target py310）；新代码必须 `ruff check` 0 error + `ruff format --check` 通过。
- 类型标注：公共函数/方法必须有完整参数与返回值类型，优先 PEP 604（`X | None`）。
- Docstring：中文，Google 风格（Args/Returns/Raises），模块头说明用途。
- 命名：类 PascalCase、函数/变量 snake_case、常量 UPPER_SNAKE、私有 `_x`。
- import：标准库 → 第三方 → 本包分组排序；禁止 `import *`。
- 日志一律 `quant.utils.logger`，禁止 print。
- pandas 兼容 2.x/3.x：禁止已移除 API（如 `replace(method=...)`）、链式赋值；列名小写 snake_case。
- 详细规则与禁止项以第 6 节 `quant-backend` 技能为准。

## 6. AI 开发技能（Skills 目录）

本仓库技能目录：`.agents/skills/`。

| 技能 | 用途 | 使用时机 |
|------|------|----------|
| `quant-backend/SKILL.md` | 后端开发完整规范（架构约束、回测红线、代码风格、测试） | 修改 `backend/quant/**` 任何代码前，必须完整读取 |
| `quant-frontend/SKILL.md` | 前端预留技能（仅联调契约基线） | 任何前端相关工作开始时读取 |

使用规则：

1. 后端任务启动时必须先完整读取 `quant-backend/SKILL.md` 再动手，禁止凭印象开发。
2. 前端任务启动时读取 `quant-frontend/SKILL.md`；当前只有契约约束，无代码风格要求。
3. 技能只约束本仓库工作，不得修改用户个人技能库（`~/.codex/skills`）。
4. 可选：把技能目录复制/链接到 `~/.codex/skills/` 可被 Codex 自动发现；不安装时本文档仍强制读取本仓库技能。
5. 新增技能按 skill-creator 规范创建（name/description 前置、agents/openai.yaml、quick_validate 校验通过），并在本节登记。

## 7. 前后端联调

- 契约文档：`docs/api-integration.md`（唯一事实来源）。
- 基线：`/api/v1` 前缀、统一响应 `{ code, message, data, request_id, timestamp }`、分页规范、错误码表。
- 后端接口变更必须先改契约文档再改代码；前端按契约 mock，不依赖示例 API 的具体行为。
- 当前后端 API（`infrastructure/api_server.py`）仍是内存示例，未接通真实链路；契约先行，实施时按契约改造。

## 8. 明确的口子与待办

- 前端：技术栈未定，暂不规范；技术栈确定后由技术负责人补充 `quant-frontend` 技能内容并更新第 2 节角色说明。
- 依赖：以 `pyproject.toml` 为唯一来源（`requirements-dev.txt` 仅作参考清单）。
- 风格存量：现有代码的 Ruff 存量告警由专门的代码卫生任务清理，不阻塞无关功能开发。

## 9. 建议引入的成熟 Skills

以下技能建议引入（多数已在本机安装，可直接使用）：

| 技能 | 用途 | 适用角色 |
|------|------|----------|
| clarify-requirements | 需求澄清与结构化（中文/英文） | 需求提出者（量化分析师） |
| archify | 架构/时序/流程可视化（HTML+SVG，可导出） | 技术负责人、文档 |
| find-skills | 发现更多可安装技能 | 所有人 |
| skill-installer | 从清单/GitHub 仓库安装技能 | 所有人 |
| skill-creator | 自建与维护技能 | 技术负责人 |

第三方技能方向（引入前用 find-skills/skill-installer 核验来源与维护状态）：量化数据与回测最佳实践类、测试与覆盖率、安全与密钥扫描、代码审查类。
