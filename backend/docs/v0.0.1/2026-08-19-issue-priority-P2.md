# P2 级问题与解决方案（中低优先级）

> 版本：v0.0.1
> 日期：2026-08-19
> 说明：P2 为中低优先级问题——不影响运行与核心结果，但影响工程卫生、协作效率与使用者体验，可在后续迭代中处理。

---

## ISSUE-008 依赖声明混乱

### 问题

- `requirements.txt` 中 `numpy>=1.24.0` 重复声明两次。
- `backtrader`、`backtesting`、`torch`、`lightgbm`、`xgboost` 均被声明但代码中无任何引用（回测为自研引擎，ML 策略只用 sklearn）。
- 无 dev/生产依赖分离；`jupyter`、`seaborn`、`plotly` 等工具类依赖混在核心依赖中。

### 影响

安装体积与时间无谓增大；依赖与实现脱节，误导使用者。

### 解决方案

1. 去重并删除未使用依赖（`backtrader`、`backtesting` 二选一或全删，以自研引擎为准；torch/lgbm/xgboost 待真实需要时再加）。
2. 拆分 `requirements.txt`（核心）与 `requirements-dev.txt`（pytest、notebook 等），或改用 `pyproject.toml` 的 optional-dependencies。

---

## ISSUE-009 工程卫生缺失

### 问题

- 项目尚不是 git 仓库，无版本控制与提交历史。
- 无 `.gitignore`，`__pycache__`、日志、数据、模型产物无排除规则。
- `tests/`、`notebooks/`、`scripts/`、`models/`、`logs/`、`docs/` 等目录为空，README 却将其描述为既有模块，易产生"已实现"的错觉。

### 影响

无法追踪变更、无法回滚；误提交产物风险高；空目录误导协作与使用。

### 解决方案

1. `git init` 并补充 `.gitignore`（`__pycache__/`、`*.pyc`、`logs/`、`data/raw/*`、`data/processed/*`、`models/*`、`.env` 等）。
2. 空目录要么补充 `README.md` 说明用途，要么删除；README 中未实现的描述改为"规划中"。

---

## ISSUE-010 模块归属不合理、文档漂移、API 仅为示例

### 问题

- 交易日历 `sentiment/calendar.py` 归属消息面模块，实际属于数据/基础设施工具，被误归类。
- `infrastructure/api_server.py` 中策略、持仓、回测 API 均为内存态示例（`StrategyAPI.run` 只返回"已启动"文案，`BacktestAPI` 不真正执行回测），与"提供策略/持仓/回测接口"的文档描述不符。
- README 环境要求写 Python 3.8+，但代码使用了 3.10+ 的 `dataclass` 字段默认工厂、联合类型等特性，声明不准确。

### 影响

模块语义混乱，API 存在"看起来可用、实际不可用"的误导；环境声明不准确导致兼容性误判。

### 解决方案

1. 将 `calendar.py` 移入 `utils/`（或新建 `market/` 工具模块）。
2. API 层明确区分"示例"与"生产实现"：要么接通真实策略/回测/持仓链路，要么在文档与注释中标注为示例并移除误导性描述。
3. 按实际使用的 Python 特性更新最低版本要求（建议直接声明 3.10+，或做兼容性改造）。

---

## P2 验收标准

1. `requirements.txt` 无重复与未使用依赖，核心/dev 依赖分组清晰。
2. 项目为 git 仓库，`.gitignore` 覆盖缓存、日志、数据、模型产物。
3. README 目录树与实际代码一致，未实现功能明确标注"规划中"。
4. `calendar.py` 归位到合理模块，API 示例与生产实现标注清晰。
5. 最低 Python 版本声明与代码实际使用的特性一致。