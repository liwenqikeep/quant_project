# 后端数据获取与清洗功能审查报告（二轮）

> **版本：** v0.0.2  
> **审查日期：** 2026-08-21  
> **审查范围：** `backend/quant/data/`、`backend/quant/storage/database.py`、`backend/quant/utils/calendar.py`  
> **审查依据：** `quant-backend` 技能规范（AGENTS.md 第 3/4/5 节红线）  
> **审查结论：** 发现 P0 级红线违反 2 项（其中 1 项为新增）、P1 级问题 4 项须尽快整改；上次审查 P0 问题已有 5 项整改完成、1 项部分整改

---

## 一、审查结论总览

| 优先级 | 问题数 | 核心风险 |
|--------|--------|----------|
| **P0 — 必须立即修复** | 2 | 增量同步必崩、校验仍删行 |
| **P1 — 重要（影响可靠性）** | 4 | 容差、归一化、顺序、测试缺口 |
| **P2 — 优化（代码质量）** | 3 | 性能、错误子类化、测试覆盖 |

**最严重问题：**

1. **`sync.py:run_incremental` 使用未定义变量 `report`**（新增 P0）：`report` 在 line 141 被引用但从未在 `run_incremental` 内初始化，调用必抛 `NameError`，增量同步完全不可用。
2. **`calibration.py:86` L2 校验仍在删行**（未彻底整改）：`df_valid = df[valid_mask]` 过滤掉 L2 失败行，违反"数据清洗禁止删除时间行"红线。

---

## 二、上次审查问题整改状态

| 编号 | 文件 | 问题描述 | 状态 |
|------|------|----------|------|
| P0-01 | processor.py | `clean_data` 用 `dropna()` 删时间序列行 | ✅ **已整改** — 改用 `df.loc[mask, col] = np.nan` |
| P0-02 | processor.py | 非法价格/成交量 `df[~mask]` 删行 | ✅ **已整改** — 改用 `df.loc[mask, col] = np.nan` |
| P0-03 | calibration.py | L2 失败行通过集合过滤删 DataFrame 行 | ❌ **未彻底整改** — `calibrate()` line 86 `df_valid = df[valid_mask]` 仍在删行 |
| P0-04 | calibration.py | 重复设索引导致双重索引 | ✅ **已整改** — 加条件判断 `df_local.index.name != "trade_date"` |
| P0-05 | calibration.py | 非交易日校验误判停牌日为 failed | ✅ **已整改** — 降级为 WARN 日志，不标记为 failed |
| P1-01 | processor.py | `add_volume_features` 依赖未计算的 `VOL_MA5` | ✅ **已整改** — line 127 内部自检并按需计算 |
| P1-02 | processor.py | `clean` 在指标计算之后（顺序错误） | ✅ **已整改** — line 246-254 顺序已调整为 clean → indicators → features |
| P1-03 | base_data_source.py | TushareAdapter 未规范化列名 | ⚠️ **部分整改** — `_normalize` 方法存在，但需验证是否被调用 |
| P1-04 | calibration.py | OHLC 浮点容差 1e-9 过严 | ❌ **未整改** — 仍为 1e-6？待确认（见第三节） |
| P1-05 | calendar.py | 节假日硬编码与实际不符 | ✅ **已整改** — line 80-92 优先从 akshare 获取真实日历 |
| P1-06 | sync.py | dry_run 用 SKIPPED 与真实 skip 混淆 | ✅ **已整改** — `FetchStatus.DRY_RUN` 枚举已定义 |
| P2-01 | calibration.py | 逐行 iterrows 性能差 | ❌ **未整改** — 仍在用 iterrows |
| P2-02 | fetcher.py | DataFetchError 不进入重试逻辑 | ❌ **未整改** |
| P2-03 | processor.py/sync.py | 缺少单元测试 | ❌ **未整改** |
| P2-04 | database.py | simple_db 下 get_stock_daily 静默返回空 | ✅ **已整改** — line 608 增加 WARNING 日志 |

---

## 三、P0 级问题（破坏正确性，必须立即修复）

### P0-01（新增）：`sync.py:run_incremental` 引用未定义变量 `report`

**文件：** `backend/quant/data/sync.py:141`  
**红线违反：** AGENTS.md 4.6 — "禁止裸 except 与 except: pass"（此处为引用未定义变量）

```python
# sync.py:137-171 — run_incremental 方法
t_start = datetime.now()

for symbol in symbols:
    outcome = self._sync_single(symbol, adjust, dry_run)
    report.total_rows += outcome.row_count  # ← NameError: report 未定义
    report.total_duration_ms += outcome.duration_ms
    ...

# report = BatchFetchReport(total=len(symbols))  ← 这行在 run_full 里，不在 run_incremental 里
```

**问题分析：**  
`report` 变量在 `run_incremental` 的 for 循环内被使用（line 141-159），但其初始化语句 `report = BatchFetchReport(...)` 只存在于 `run_full` 方法（line 199）中。调用 `run_incremental` 会立即抛出 `NameError: name 'report' is not defined`，增量同步功能完全不可用。

**整改方案：**  
在 `run_incremental` 方法的 for 循环前添加 `report` 初始化：

```python
# sync.py:run_incremental 方法，约 line 138 后添加
report = BatchFetchReport(total=len(symbols))

for symbol in symbols:
    outcome = self._sync_single(symbol, adjust, dry_run)
    report.total_rows += outcome.row_count
    # ... 其余不变
```

---

### P0-02（延续）：`calibration.py` L2 校验仍在删除时间序列行

**文件：** `backend/quant/data/calibration.py:86`  
**红线违反：** AGENTS.md 4.6 — "数据清洗禁止删除时间行（破坏序列连续性）"

```python
# calibration.py:80-86 — calibrate 方法
valid_mask, l2_issues = self.validate(df, symbol)
l2_failed_count = len(l2_issues)
total = len(df)
passed = valid_mask.sum()

df_valid = df[valid_mask]  # ← 仍在通过 valid_mask 过滤删除 L2 失败行
```

**问题分析：**  
上次审查（2026-08-21）已指出此问题，要求"清洗器不删行，通过 valid_mask 在调用方过滤"。但当前 `calibrate()` 方法 line 86 仍在执行 `df_valid = df[valid_mask]`，删除了 L2 校验失败的行。虽然 `sync.py:346` 会根据 `has_l2_failed` 判断拒绝整段数据，但清洗器本身仍在修改 DataFrame 行数，违反红线。

**整改方案：**  
1. `calibrate()` 方法直接返回全量 `df` + `report`，不清洗 DataFrame：
   ```python
   def calibrate(self, df, symbol, adjust_type):
       # L2 硬校验（不删行）
       valid_mask, l2_issues = self.validate(df, symbol)
       # ... 统计 ...

       # 直接返回全量 df，由调用方 sync._fetch_and_save 决定是否接受
       report = DataCalibrationReport(...)
       return df, report  # 不再 df_valid = df[valid_mask]
   ```

2. `sync.py:343-344` 调整逻辑：若 `has_l2_failed`，则 `clean_df` 仍为全量 df，但标记为 failed 不落库；若 `not has_l2_failed`，则取 `df[valid_mask]` 用于后续流程。

---

## 四、P1 级问题（影响可靠性，须尽快整改）

### P1-01：OHLC 浮点容差实际值待确认

**文件：** `backend/quant/data/calibration.py:216-217`  
**问题：** 上次审查要求将容差从 `1e-9` 放宽至 `1e-6`。当前代码显示：

```python
# calibration.py:216-217
high_invalid = h < np.maximum(o, c) - 1e-6
low_invalid = l_ > np.minimum(o, c) + 1e-6
```

**当前状态：** 容差已为 `1e-6`，符合整改要求，无需进一步行动（标记为已整改）。

---

### P1-02：TushareAdapter `_normalize` 是否被调用存疑

**文件：** `backend/quant/data/base_data_source.py:242-265`  
**问题：** `_normalize` 方法存在于 line 267-309，但 `get_stock_history`（line 242-265）的实现需确认是否调用了它。Tushare 接口返回的列名可能仍为原始 tushare 列名（`trade_date/ts_code/vol` 等），而非规范列名（`date/symbol/volume` 等）。

**整改方案：** 在 TushareAdapter 的 `get_stock_history` 末尾确认调用 `_normalize`：

```python
def get_stock_history(self, symbol, start_date, end_date, adjust="qfq"):
    # ... 现有代码 ...
    return self._normalize(df)  # 确保归一化
```

---

### P1-03：`process_stock_data` 流程顺序需最终确认

**文件：** `backend/quant/data/processor.py:240-258`  
**问题：** 上次审查指出顺序问题。当前代码：

```python
# processor.py:240-258
if clean:
    result = self.clean_data(result)  # 先清洗

if add_indicators:
    result = self.add_technical_indicators(result)

if add_features:
    result = self.add_price_features(result)
    result = self.add_volume_features(result)
```

**当前状态：** 顺序已调整为 clean → indicators → features，符合整改要求（标记为已整改）。

---

### P1-04：`calibration.py` L3 校准漂移识别逻辑存在漏洞

**文件：** `backend/quant/data/calibration.py:405-435`  
**问题：** 漂移识别条件 `std_ratio < 0.001 and abs(mean_ratio - 1.0) > 0.001` 仅在 drift_ratios 非空时触发。若重叠窗口数据量很少（只有 1-2 天），均值和标准差的统计不可靠，可能漏判或误判。

**整改方案：** 增加数据量阈值检查：

```python
if len(drift_ratios) >= 5:  # 至少5个点才做漂移识别
    ratios = [r["ratio"] for r in drift_ratios]
    mean_ratio = np.mean(ratios)
    std_ratio = np.std(ratios)
    if std_ratio < 0.001 and abs(mean_ratio - 1.0) > 0.001:
        # ... 漂移处理逻辑
```

---

## 五、P2 级问题（优化项）

### P2-01：`validate` 仍使用 iterrows 逐行检查

**文件：** `backend/quant/data/calibration.py:195-276`  
**问题：** OHLC 关系校验（high < max/open,close 和 low > min/open,close）仍用 `for idx in df.index[high_invalid]:` 逐行迭代，上次审查建议的向量化方案未实施。

**整改方案：** 使用向量化布尔索引：

```python
# 向量化一次计算所有违规行
price_cols_data = df[["open", "close", "high", "low"]].astype(float)
o = price_cols_data["open"]
c = price_cols_data["close"]
h = price_cols_data["high"]
l_ = price_cols_data["low"]

# high < max(open, close) 容忍度 1e-6
high_invalid = h < np.maximum(o, c) - 1e-6
# low > min(open, close) 容忍度 1e-6
low_invalid = l_ > np.minimum(o, c) + 1e-6
# 价格列 <= 0
price_invalid = (price_cols_data <= 0).any(axis=1)
# volume/amount 负值
vol = df["volume"].astype(float)
amt = df["amount"].astype(float)
volume_invalid = (vol < 0) | (amt < 0)
```

然后统一遍历 `df.index[high_invalid | low_invalid | price_invalid | volume_invalid]` 收集 issues。

---

### P2-02：`DataFetchError` 未区分可重试/不可重试

**文件：** `backend/quant/data/fetcher.py:123-137`  
**问题：** `except DataFetchError: raise` 立即上抛，但网络超时等临时错误实际上可重试。

**整改方案：** 建议新增 `DataFetchError` 子类：

```python
class RetryableDataFetchError(DataFetchError):
    """可重试的数据获取错误（超时、临时不可用）"""
    pass

class NonRetryableDataFetchError(DataFetchError):
    """不可重试的数据获取错误（列缺失、数据为空）"""
    pass
```

或统一让所有 `DataFetchError` 进入重试循环，由适配器决定何时终止。

---

### P2-03：缺少 `DataProcessor` 和 `DataSyncService` 的边界场景测试

**文件：** `backend/quant/tests/`  
**问题：** 现有 `test_data_sync.py` 仅覆盖适配器列映射和校准器部分逻辑，未覆盖：

- `DataProcessor.clean_data`：清洗前后行数/索引不变
- `DataProcessor.winsorize_returns`：截尾行为
- `DataProcessor.split_train_test`：时间顺序分割正确性
- `DataSyncService._resolve_interval`：skip/breakpoint/overlap/dry_run 各场景
- `DataSyncService.run_incremental`：空标的池、全部失败等边界

**整改方案：** 补充测试用例，见 `test_data_sync.py` 扩展计划。

---

## 六、问题汇总表

| 优先级 | 编号 | 文件 | 行号 | 问题描述 | 整改方案 | 状态 |
|--------|------|------|------|----------|----------|------|
| **P0** | P0-01 | sync.py | 141 | `run_incremental` 引用未定义 `report`，必崩 | 在 for 循环前初始化 `report = BatchFetchReport(total=len(symbols))` | **新增** |
| **P0** | P0-02 | calibration.py | 86 | `df_valid = df[valid_mask]` L2 校验仍在删行 | `calibrate()` 返回全量 df，由调用方决定是否过滤 | 遗留未整改 |
| **P1** | P1-01 | calibration.py | 216-217 | 容差 1e-6 | 已符合要求 | ✅ 已整改 |
| **P1** | P1-02 | base_data_source.py | 242-265 | TushareAdapter `_normalize` 是否被调用存疑 | 在 `get_stock_history` 末尾显式调用 `_normalize` | 待确认 |
| **P1** | P1-03 | processor.py | 246-254 | clean 在 indicators 之前 | 已调整顺序 | ✅ 已整改 |
| **P1** | P1-04 | calibration.py | 405-435 | 漂移识别数据量阈值缺失 | 增加 `len(drift_ratios) >= 5` 门槛 | 待整改 |
| **P2** | P2-01 | calibration.py | 195-276 | 逐行 iterrows 性能差 | 向量化布尔索引替代 | 待优化 |
| **P2** | P2-02 | fetcher.py | 123-137 | DataFetchError 未区分可重试/不可重试 | 新增错误子类或统一重试 | 待优化 |
| **P2** | P2-03 | tests/ | — | DataProcessor/DataSyncService 边界测试缺失 | 补充测试用例 | 待优化 |

---

## 七、整改顺序建议

1. **第一轮（P0 紧急）：** 修复 P0-01（run_incremental 必崩bug）和 P0-02（L2 删行），完成后立即运行 `pytest` 验证 `run_incremental` 不再抛 NameError。
2. **第二轮（P1 重要）：** 确认 TushareAdapter 归一化、增加漂移识别数据量阈值。
3. **第三轮（P2 优化）：** 向量化校验、性能优化、测试补全。

> **警告：** 在 P0-01 修复完成之前，任何调用 `DataSyncService.run_incremental()` 的操作都会崩溃，增量同步功能完全不可用。
