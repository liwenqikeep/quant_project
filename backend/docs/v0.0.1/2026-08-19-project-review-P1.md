# 项目审查问题与整改方案 — P1（高优先级）

> 版本：v0.0.1（二次审查）
> 日期：2026-08-19
> 定位：个人、非高频量化框架
> 说明：P1 为高优先级——不影响"能否运行"，但影响策略质量、数据可靠性与统计稳健性，建议 1-2 周内完成。

---

## R-P1-01 RSI / KDJ 指标除零与口径偏差

### 问题

`data/processor.py` 与 `strategies/rsi_strategy.py` 的 RSI 计算：

```python
rs = gain / loss
df["RSI"] = 100 - (100 / (1 + rs))
```

- 当 `loss == 0`（连续上涨/横盘）时产生 NaN/inf；
- 使用简单滚动均值，而非 Wilder 平滑（`alpha = 1/period`），与主流行情软件（通达信/同花顺）口径不一致。

KDJ 在 `high14 == low14`（涨跌停日）时 `RSV` 除零，同样产生 NaN。

### 影响

指标在极端行情日出现 NaN/inf，策略信号在这些日子不可用；RSI 数值与行情软件对不上，策略参数（如 30/70 阈值）的参考价值下降。

### 整改方案

1. RSI 改用 Wilder 平滑并处理除零：

```python
delta = df["close"].diff()
gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()

# 处理 loss=0：此时 RSI 应为 100
rs = gain / loss.replace(0, np.nan)
df["RSI"] = (100 - 100 / (1 + rs)).fillna(100.0)
```

2. KDJ 除零防护：

```python
denom = (high14 - low14).replace(0, np.nan)
df["RSV"] = ((df["close"] - low14) / denom * 100).fillna(50.0)
```

3. 增加单元测试：全涨/全跌/横盘序列下 RSI 为有限值且位于 [0,100]。

---

## R-P1-02 数据清洗用 3σ 删行，破坏时间序列

### 问题

`data/processor.py:clean_data`（约 169 行）对每个数值列做 3σ 过滤并**删除整行**：

```python
df = df[(df[col] > mean - 3*std) & (df[col] < mean + 3*std)]
```

价格序列是时间相关的，删除中间行会产生数据空洞，破坏滚动窗口指标与回测的时间连续性。

### 影响

清洗后数据出现断档，均线/波动率等指标在缺口附近异常；回测的交易日期与真实日历错位。

### 整改方案

改为基于收益率的 winsorize（截尾），不删行：

```python
@staticmethod
def winsorize_returns(df: pd.DataFrame, lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame:
    df = df.copy()
    ret = df["close"].pct_change()
    lo, hi = ret.quantile(lower), ret.quantile(upper)
    df["return_winsorized"] = ret.clip(lo, hi)
    # 用截尾后的收益重建清洗后的收盘价（可选）
    return df
```

若确需剔除异常值，应只剔除"价格本身非法"的数据（如 0、负数、停牌缺失），而不是按统计分布删行。

---

## R-P1-03 ML 策略训练/测试边界标签泄漏

### 问题

`strategies/ml_strategy.py:prepare_features` 的目标变量为 `close.shift(-1) > close`（次日涨跌）。`train()` 使用 `train_test_split(..., shuffle=False)` 简单切分，**切分点前最后一个训练样本的标签使用了测试集第一天的收盘价**，存在一天的信息泄漏。

### 影响

训练集"偷看"了一天未来数据，验证准确率虚高；策略上线后实际表现通常明显差于回测。

### 整改方案

1. 切分时在边界两侧各丢弃一天：

```python
split = int(len(X) * (1 - test_size))
X_train, X_test = X.iloc[:split - 1], X.iloc[split + 1:]
y_train, y_test = y.iloc[:split - 1], y.iloc[split + 1:]
```

2. 更推荐 walk-forward（滚动训练），至少按年滚动验证：

```python
# 伪代码：每 6 个月训练一次，预测后 3 个月
for train_end in range(first_train_end, len(X), step):
    train = X.iloc[:train_end]
    test = X.iloc[train_end:train_end + horizon]
    # fit → predict → 累积结果
```

3. 在 README 中说明：ML 策略为实验性质，实盘前必须做 walk-forward 验证与样本外检验。

---

## R-P1-04 组合优化约束不可行时被静默掩盖

### 问题

`portfolio/optimizer.py`：

- 最小方差/最大夏普/风险平价使用 `bounds=(min_weight, max_weight)`，默认 `max_weight=0.3`；
- 当资产数 n < 4 时，权重上限之和 `0.3*n < 1`，约束不可行，SLSQP 无法收敛；
- 代码随后 `clip + 归一化` 强行兜底，**静默扭曲权重而不报错**。

个人组合通常 3-5 只标的，极易踩中。

### 影响

优化结果可能违反权重上限却不自知，组合实际风险暴露与模型假设不符。

### 整改方案

1. 优化前做可行性校验：

```python
n = len(symbols)
if n * self.config.max_weight < 1.0 - 1e-6:
    raise ValueError(
        f"权重上限 {self.config.max_weight} 过小，{n} 只资产最大总权重 "
        f"{n * self.config.max_weight:.2f} < 1，约束不可行"
    )
```

2. 或自动放宽上限：

```python
effective_max = max(self.config.max_weight, 1.0 / n + 0.05)
```

3. 增加测试：2 只资产 + 默认配置时应明确报错（或自动放宽），不允许静默归一化。

---

## R-P1-05 数据获取失败静默吞错

### 问题

`data/fetcher.py:get_stock_history` 捕获所有异常后返回空 DataFrame：

```python
except Exception as e:
    logger.error(f"获取 {symbol} 数据失败: {e}")
    return pd.DataFrame()
```

调用方无法区分"该股票确实无数据"与"网络/接口故障"；批量获取时坏数据会静默混入。

### 影响

数据缺失时策略/回测可能在残缺数据上运行，产出看似正常实则无效的结果。

### 整改方案

1. 失败时抛异常（或返回带错误元数据的对象）：

```python
except Exception as e:
    logger.error(f"获取 {symbol} 数据失败: {e}")
    raise DataFetchError(f"{symbol}: {e}") from e
```

2. `get_stock_batch` 捕获后记录失败清单并跳过，返回 `(results, failures)` 元组，而不是静默忽略。
3. 增加重试（如 3 次指数退避）与请求间隔，避免被数据源限流。

---

## R-P1-06 config.yaml 与代码配置键不一致

### 问题

- `data/fetcher.py:37` 读取 `data.sources.default`，但 `config.yaml` 中只有 `data.sources.akshare.enabled` / `data.sources.tushare.token`，没有 `default` 键；
- 当前只是碰巧回退到 "akshare" 才没暴露问题。

### 影响

配置与代码脱节，将来切换默认数据源时配置不生效，容易产生"改了配置没反应"的困惑。

### 整改方案

1. 在 `config.yaml` 的 `data.sources` 下显式增加默认源：

```yaml
data:
  sources:
    default: "akshare"
    akshare:
      enabled: true
    tushare:
      enabled: false
      token: "your_token_here"
```

2. 增加配置校验（`ConfigManager.validate_config` 已存在雏形）：加载后校验必需键是否存在，缺失时给出明确警告。

---

## P1 验收标准

1. RSI/KDJ 在极端行情（全涨/跌停/横盘）下为有限数值，且 RSI 与主流行情软件口径一致；
2. 数据清洗不再删除时间行，改用截尾处理；
3. ML 策略无切分边界标签泄漏，提供 walk-forward 示例；
4. 组合优化对不可行约束明确报错或自动放宽，权重合法；
5. 数据获取失败明确抛错并带失败清单，配置键与代码一致；
6. 新增的每个整改项均有对应单元测试。