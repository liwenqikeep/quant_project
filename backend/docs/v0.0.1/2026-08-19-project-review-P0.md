# 项目审查问题与整改方案 — P0（阻断级）

> 版本：v0.0.1（二次审查）
> 日期：2026-08-19
> 定位：个人、非高频量化框架
> 说明：P0 为阻断级——不修复则回测结果不可信、核心链路不可用，必须最先处理（建议 1-3 天）。

---

## R-P0-01 策略模块在 pandas 3.x 下崩溃

### 问题

MA / RSI / MACD / ML 四个策略均使用 pandas 已移除的 API：

```python
df["position"] = df["signal"].replace(to_replace=0, method="ffill").fillna(0).astype(int)
```

涉及文件与行号：

- `strategies/ma_strategy.py:68`
- `strategies/rsi_strategy.py:67`
- `strategies/macd_strategy.py:70`
- `strategies/ml_strategy.py:210`

在 pandas 3.0.2 下直接抛 `TypeError: NDFrame.replace() got an unexpected keyword argument 'method'`。而 `requirements` 声明 `pandas>=2.0.0`，3.x 在声明范围内，属于"声明范围内代码即坏"。

### 影响

所有技术面策略无法生成信号，回测链路不可用；8 个策略测试全部失败。

### 整改方案

将四处统一改为 `.where(...).ffill()` 写法：

```python
df["position"] = df["signal"].where(df["signal"] != 0).ffill().fillna(0).astype(int)
```

或等价写法：

```python
df["position"] = df["signal"].mask(df["signal"] == 0).ffill().fillna(0).astype(int)
```

整改后运行 `pytest quant/tests/test_strategies.py` 应全部通过。

---

## R-P0-02 回测存在未来函数（信号当日成交）

### 问题

`backtest/backtester.py:run()`（约 160-180 行）将信号与数据按索引对齐后，在**信号产生的当天**用当天 `close` 成交：

```python
self.execute_trade(idx, row["close"], int(row["signal"]), position_size)
```

均线金叉是收盘后才知道的，实盘中不可能用当日收盘价成交。这是回测收益虚高最常见的原因。

### 影响

所有策略的回测结果系统性偏乐观；对日频调仓的个人策略影响显著，回测与实盘差距会很大。

### 整改方案

标准做法：信号在 t 日收盘产生，t+1 日开盘执行。

1. `Backtester` 增加执行价格参数：

```python
def __init__(self, ..., execution_price: str = "next_open"):
    # "next_open": 次日开盘价执行（推荐，消除未来函数）
    # "next_close": 次日收盘价执行（更保守）
    self.execution_price = execution_price
```

2. `run()` 中把信号整体后移一天再合并：

```python
signals_aligned = signals.shift(1)  # t 日信号 → t+1 日执行
df = data.join(signals_aligned, how="left")
```

3. 成交价按配置选择：

```python
if self.execution_price == "next_open" and "open" in df.columns:
    exec_price = row["open"]
elif self.execution_price == "next_close":
    exec_price = row["close"]
else:
    exec_price = row["close"]  # 兼容旧行为，但应弃用
```

4. 回测结果中新增 `execution_price` 字段并在日志输出，便于复核。

---

## R-P0-03 成本模型不真实

### 问题

- 无滑点参数；
- 未实现 A 股佣金最低 5 元规则；
- 印花税默认 0.001（10 万分之 100），现行标准为 0.0005（2023-08 起）；
- 配置文件与代码默认值不一致时，以硬编码为准。

### 影响

个人资金量交易笔数少，单笔成本占比高；成本模型不准会直接扭曲收益率、胜率与夏普比率，导致"回测赚钱、实盘亏钱"。

### 整改方案

1. 佣金最低 5 元（可配置开关）：

```python
def _calc_commission(self, trade_value: float) -> float:
    commission = trade_value * self.commission
    if self.min_commission_enabled:
        commission = max(commission, self.min_commission)
    return commission
```

2. 滑点（bps，买入上浮、卖出下浮）：

```python
def _apply_slippage(self, price: float, side: str) -> float:
    if side == "buy":
        return price * (1 + self.slippage)
    return price * (1 - self.slippage)
```

3. 默认值修正：`stamp_tax` 默认改为 0.0005；`config.yaml` 同步更新。

4. 建议在回测结果中输出"总成本/总成交额"比值，直观检查成本占比是否合理。

---

## R-P0-04 风控引擎买入成本口径错误

### 问题

`risk/risk_engine.py:137` 买入资金检查硬编码"佣金+印花税"双收：

```python
required_cash = trade_value * (1 + 0.0003 + 0.001)  # 佣金+印花税
```

A 股买入不收印花税；且该值硬编码、未从配置读取，与回测器口径不一致。

### 影响

风控会高估买入所需资金，可能误拦正常订单；与回测成本模型口径不一致，实盘执行与回测对不上。

### 整改方案

1. 从配置读取成本参数（`RiskConfig` 增加 `commission`、`stamp_tax` 字段，默认 0.0003 / 0.0005）。
2. 买入资金检查只计佣金：

```python
if direction == "buy":
    required_cash = trade_value * (1 + self.config.commission)
```

3. 卖出检查（若实现）只计佣金+印花税；与回测器 `execute_trade` 的口径保持一致。
4. 增加单测：买入时 `required_cash` 不含印花税。

---

## R-P0-05 绩效指标口径不一致（回撤正负、交易字段不兼容）

### 问题

- `backtest/backtester.py` 最大回撤返回**负数**（`drawdown.min()`）；
- `analysis/performance.py:203` 最大回撤返回**正数**（`abs(drawdown.min())`）；
- 回测器交易记录字段为 `signal`(1/-1)，绩效分析器 `_calculate_trade_metrics` 期望 `side`/`pnl` 字段——**回测结果无法直接喂给绩效分析模块**。

### 影响

指标口径混乱，同一策略两种口径算出相反符号的回撤；分析报告链路断裂。

### 整改方案

1. 统一回撤符号：建议全项目使用"回撤为负、最大回撤为负值"口径（与回撤曲线绘图一致）。`performance.py` 改为返回 `drawdown.min()`（负值）。
2. 交易记录兼容：`Backtester.execute_trade` 输出时补充 `side`（"buy"/"sell"）与 `pnl`（卖出配对后计算）字段；`PerformanceAnalyzer` 保持按 `side`/`pnl` 计算。
3. 增加跨模块测试：用同一组交易数据分别跑 `Backtester.calculate_metrics` 与 `PerformanceAnalyzer.analyze`，断言回撤符号一致、胜率一致。

---

## R-P0-06 测试套件未全绿（10 个失败）

### 问题

当前 `pytest` 结果：31 通过 / 10 失败。

- 策略 8 个失败：根因是 R-P0-01 的 pandas 兼容问题；
- 风控 2 个失败：`tests/test_risk.py` 对 `PositionLimits`（配置数据类）调用 `set_total_value`，该方法实际属于 `PositionLimitManager`（`risk/position_limits.py:41`）。

### 影响

"测试全绿"是框架可信的底线；未全绿时任何修复都可能引入回归而无人察觉。

### 整改方案

1. 修复 R-P0-01 后，8 个策略测试应自动恢复。
2. `test_risk.py` 中两处改为使用 `PositionLimitManager`：

```python
from quant.risk.position_limits import PositionLimits, PositionLimitManager

limits = PositionLimitManager(PositionLimits())
limits.set_total_value(100000)
limits.update_position("AAPL", 10000, industry="科技")
```

3. 跑通后固定 CI 门槛：`pytest` 全绿方可合入。

---

## P0 验收标准

1. 四个策略在 pandas 3.x 下均可正常生成信号；
2. 回测默认改为次日执行，且执行价可配置；
3. 成本模型含滑点、最低佣金、正确印花税，默认值与 config.yaml 一致；
4. RiskEngine 买入资金检查不含印花税；
5. 回撤符号与交易字段在全项目统一，回测结果可直接喂给绩效分析；
6. `pytest` 全量通过。