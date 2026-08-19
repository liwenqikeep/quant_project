# P0 级问题与解决方案（阻断级）

> 版本：v0.0.1
> 日期：2026-08-19
> 说明：P0 为阻断级问题——不修复则框架不可用或回测结果不可信，应最先处理（建议 1-2 天完成）。

---

## ISSUE-001 导入机制脆弱，无打包配置

### 问题

- 27 个文件通过 `sys.path.append(str(Path(__file__).parent.parent))` 硬编码导入路径（如 `backtest/backtester.py:9`、`data/fetcher.py:10`、`risk/risk_engine.py:13` 等）。
- 另有 5 个文件直接 `from utils.logger import logger` 却无该补丁（`data/processor.py:8`、`data/storage.py:9`、`strategies/ma_strategy.py:9`、`strategies/rsi_strategy.py:8`、`strategies/macd_strategy.py:8`），切换工作目录即报 `ModuleNotFoundError`。
- 项目无 `pyproject.toml` / `setup.py`，无法以标准包方式安装（`pip install -e .`）。

### 影响

只能在 `backend/src` 作为工作目录时运行；模块无法被外部复用、无法被测试框架稳定导入，是工程化改造的最大障碍。

### 解决方案

1. 在 `backend/` 建立标准 Python 包结构，增加 `pyproject.toml`，配置包根路径与 `packages`。
2. 全量删除 `sys.path.append`，统一改为包内导入（如 `from quant.utils.logger import logger`）。
3. 将 `utils.logger` 的初始化改为惰性加载（当前导入期即创建日志目录并写文件，副作用过大）。

---

## ISSUE-002 组合优化模块语法错误，无法导入

### 问题

- `portfolio/optimizer.py:269`：`def risk_parity objective(weights):` 函数名中间多一个空格，触发 `SyntaxError`。
- 同文件 `:280` 引用的 `risk_parity_objective` 因此不存在。
- 全项目编译验证：46 个文件中仅此 1 处语法错误，但导致整个 `portfolio` 包 import 失败。

### 影响

`from portfolio import ...` 直接崩溃；风险平价优化不可用。

### 解决方案

1. 立即修正为 `def risk_parity_objective(weights):`。
2. 补充冒烟测试：构造 3 只股票的协方差矩阵，验证 `_optimize_risk_parity` 可执行并返回合法权重。

---

## ISSUE-003 测试完全缺失

### 问题

- `backend/src/tests/` 目录存在但为空。
- `requirements.txt` 无 pytest / pytest-cov。

### 影响

费用、回撤、胜率、信号等核心逻辑任何一行改动都可能使回测结果失真，且无回归保护；对量化系统属于最高风险项。

### 解决方案

1. 将 `pytest`、`pytest-cov` 加入独立 dev 依赖组。
2. 首批测试覆盖（按优先级）：
   - 交易费用：买入不收印花税、卖出收取、佣金计算；
   - 指标：最大回撤、年化收益、夏普比率数值正确性；
   - 信号：MA/MACD/RSI 金叉死叉与边界情况（NaN、窗口不足）；
   - 风控：单股/总仓位上限拦截、回撤强平触发；
   - 存储：CSV 与数据库读写往返一致。
3. 接入 CI（如 GitHub Actions），`pytest` 全绿为合入门槛。

---

## P0 验收标准

1. 在任意工作目录执行 `pip install -e backend` 后，全部模块可正常导入，无 `sys.path` 补丁。
2. `pytest` 全量通过，覆盖费用、回撤、胜率、信号、风控核心逻辑。
3. `portfolio` 全部优化方法（含风险平价）可执行并返回合法权重。