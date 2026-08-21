# 数据获取与清洗功能整改规范

## Problem Statement

后端 `data` 模块存在 5 个 P0 级红线违反（P0-01 ~ P0-05）和 6 个 P1 级问题（P1-01 ~ P1-06），其中最严重的是 `DataProcessor.clean_data` 和 `DataCalibrator.validate` 在多处通过 `dropna()` / 布尔索引过滤方式删除了时间序列行，直接违反 AGENTS.md 第 4.6 节红线——"数据清洗禁止删除时间行（破坏序列连续性）"。

量化回测要求全量日期索引连续无断裂，删行会导致信号对齐错误、指标计算偏差，使得回测结果不可信。

## Solution

按三轮优先级整改：
1. **第一轮（P0 修复）：** 修复 P0-01 ~ P0-05，确保时间序列不删行、数据不因校验误判被删除
2. **第二轮（P1 修复）：** 修复 P1-01 ~ P1-06，确保数据规范化、浮点容差合理、日历准确
3. **第三轮（P2 优化）：** 性能优化、测试补全、dry_run 枚举分离

## User Stories

1. 作为量化分析师，我希望数据清洗不删除时间序列行，保证回测时间序列连续无断裂，避免信号漂移和指标失真
2. 作为量化开发者，我希望 `clean_data` 方法仅做列级非法值过滤（价格 ≤ 0 → NaN，成交量 < 0 → NaN），不删除任何行
3. 作为量化开发者，我希望 `process_stock_data` 流程顺序为 `clean → add_indicators → add_price_features → add_volume_features`，确保清洗不影响后续指标计算
4. 作为量化开发者，我希望 `DataCalibrator.validate` 返回 `(valid_mask, issues)`，调用方通过 valid_mask 过滤，不在清洗器内删行
5. 作为量化开发者，我希望 `DataCalibrator._calibrate_overlap` 不重复设置索引，避免双重索引破坏 loc 查询
6. 作为量化开发者，我希望非交易日校验降级为 WARN 级日志，不误判停牌日为校验失败
7. 作为量化开发者，我希望 `add_volume_features` 内部自检 `VOL_MA5` 是否存在，按需计算
8. 作为量化开发者，我希望 `TushareAdapter.get_stock_history` 返回前规范化列名，与 AKShare 适配器一致
9. 作为量化开发者，我希望 OHLC 浮点精度容差放宽至 1e-6，避免涨跌停附近数据被误判
10. 作为量化开发者，我希望交易日历从 akshare 实时获取真实数据，节假日不硬编码
11. 作为量化开发者，我希望 `FetchStatus` 枚举新增 `DRY_RUN` 值，区分 dry_run 模式与真实 skip 状态
12. 作为量化开发者，我希望 `validate` 使用向量化布尔索引替代 iterrows 逐行检查，提升性能
13. 作为量化开发者，我希望所有 `DataFetchError` 进入统一重试逻辑，区分可重试与不可重试子类
14. 作为量化测试工程师，我希望补充 `processor.py` 和 `sync.py` 的单元测试，覆盖边界场景
15. 作为量化测试工程师，我希望验证清洗前后 DataFrame 行数不变、index 不变
16. 作为量化运维人员，我希望 `Database.get_stock_daily` 在 simple_db 模式下输出日志警告，避免静默返回空

## Implementation Decisions

### 模块修改

- **`backend/quant/data/processor.py`**：`DataProcessor.clean_data`、`DataProcessor.add_volume_features`、`DataProcessor.process_stock_data`
- **`backend/quant/data/calibration.py`**：`DataCalibrator.validate`、`DataCalibrator._calibrate_overlap`
- **`backend/quant/data/base_data_source.py`**：`TushareAdapter.get_stock_history`
- **`backend/quant/data/sync.py`**：`DataSyncService._sync_single`（dry_run 状态）
- **`backend/quant/utils/calendar.py`**：`TradingCalendar._generate_default_calendar`
- **`backend/quant/data/models.py`**：`FetchStatus` 枚举新增 `DRY_RUN`

### 接口变更

| 模块 | 接口 | 变更 |
|------|------|------|
| `DataProcessor.clean_data` | `(df: pd.DataFrame) → pd.DataFrame` | 移除 `dropna()` 和布尔删行，改为 `df.loc[mask, col] = np.nan` |
| `DataProcessor.add_volume_features` | `(df: pd.DataFrame) → pd.DataFrame` | 内部自检 `VOL_MA5`，不存在则计算 |
| `DataProcessor.process_stock_data` | 同上 | 调整顺序：clean → add_indicators → add_price_features → add_volume_features |
| `DataCalibrator.validate` | `(df, symbol) → (valid_mask: pd.Series, issues: list)` | 返回 valid_mask 而非删行后的 DataFrame |
| `DataCalibrator._calibrate_overlap` | 同上 | 加条件判断避免重复设索引 `if df_local.index.name != "trade_date"` |
| `TushareAdapter.get_stock_history` | 同上 | 调用 `_normalize` 方法规范化列名 |
| `FetchStatus` | 枚举 | 新增 `DRY_RUN = "dry_run"` |

### 关键代码变更

#### processor.py:clean_data — 不删行

```python
# 移除: df = df.dropna()
# 移除: df = df[~invalid_close]
# 改为:
if "close" in df.columns:
    invalid_close = (df["close"] <= 0) | df["close"].isna()
    if invalid_close.any():
        logger.warning(f"发现 {invalid_close.sum()} 条非法收盘价，替换为 NaN")
        df.loc[invalid_close, "close"] = np.nan

if "volume" in df.columns:
    invalid_volume = (df["volume"] < 0) | df["volume"].isna()
    if invalid_volume.any():
        logger.warning(f"发现 {invalid_volume.sum()} 条非法成交量，替换为 NaN")
        df.loc[invalid_volume, "volume"] = np.nan
```

#### processor.py:add_volume_features — 自检 VOL_MA5

```python
if "VOL_MA5" not in df.columns:
    df["VOL_MA5"] = df["volume"].rolling(window=5).mean()
df["vol_ratio"] = df["volume"] / df["VOL_MA5"]
```

#### calibration.py:validate — 返回 valid_mask

```python
def validate(self, df: pd.DataFrame, symbol: str) -> tuple[pd.Series, list[CalibrationIssue]]:
    # ... 校验逻辑 ...
    failed_dates = {issue["trade_date"] for issue in issues if issue["decision"] == "failed"}
    valid_mask = pd.Series([d not in failed_dates for d in dates], index=df.index)
    return valid_mask, issues
```

#### calibration.py:_calibrate_overlap — 避免重复设索引

```python
if "trade_date" in df_local.columns and df_local.index.name != "trade_date":
    df_local = df_local.set_index("trade_date")
```

#### calibration.py:validate — 移除非交易日校验

```python
# 移除非交易日校验（或降级为 WARN 级日志）
# for d in all_dates:
#     if cal.trading_days and d not in set(cal.trading_days):
#         non_trading_dates.append(d)
```

#### base_data_source.py:TushareAdapter — 规范化列名

```python
def get_stock_history(self, symbol, start_date, end_date, adjust="qfq") -> pd.DataFrame:
    # ... Tushare 接口调用 ...
    return self._normalize(df)  # 添加规范化调用
```

#### calibration.py:validate — OHLC 容差放宽

```python
if not (h >= max(o, c) - 1e-6):  # 从 1e-9 改为 1e-6
    # ...
if not (l_ <= min(o, c) + 1e-6):  # 从 1e-9 改为 1e-6
```

#### calendar.py — 使用 akshare 替代硬编码

```python
def _generate_default_calendar(self):
    """默认日历直接尝试从 akshare 获取真实日历，无网络时使用保守逻辑"""
    if AKSHARE_AVAILABLE:
        try:
            self.update_calendar()
            return
        except Exception:
            pass
    # 降级：所有工作日作为交易日（节假日由用户手动配置）
    self.trading_days = [...]
```

#### sync.py — dry_run 状态分离

```python
class FetchStatus(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    EMPTY = "empty"
    STALE = "stale"
    SKIPPED = "skipped"
    DRY_RUN = "dry_run"  # 新增
```

#### fetcher.py — DataFetchError 进入重试

```python
except DataFetchError as e:
    last_error = e
    # 进入重试循环，不立即 raise
```

## Testing Decisions

### 测试范围

| 模块 | 测试文件 | 覆盖场景 |
|------|----------|----------|
| `DataProcessor.clean_data` | `test_processor.py` | 清洗前后行数/index 不变、非法值替换为 NaN |
| `DataProcessor.process_stock_data` | `test_processor.py` | 顺序调整后指标计算正确、空数据/全 NaN 边界 |
| `DataProcessor.add_volume_features` | `test_processor.py` | 单独调用时不依赖外部 VOL_MA5 |
| `DataCalibrator.validate` | `test_calibration.py` | valid_mask 正确过滤失败行、停牌日不误判 |
| `DataCalibrator._calibrate_overlap` | `test_calibration.py` | 重复设索引不产生 MultiIndex |
| `TushareAdapter` | `test_data_sync.py` | 列名规范化与 AKShare 一致 |
| `DataSyncService._resolve_interval` | `test_data_sync.py` | skip/breakpoint/overlap/dry_run 场景 |
| `TradingCalendar` | `test_calendar.py` | akshare 获取失败降级逻辑 |

### 验收标准

- `pytest backend/quant/tests/` 全量通过
- 清洗前后 `len(df)` 和 `df.index` 完全一致
- OHLC 涨跌停数据不被误判为 failed
- 非交易日（停牌日）不被误判为校验失败

## Out of Scope

- 前端数据展示与交互
- 其他数据源适配器（如东方财富 Choice）
- 回测引擎与风控模块的联动测试
- 历史数据的离线修复方案

## Further Notes

- 整改顺序严格按三轮执行，P0 修复前任何回测结果不可信
- 建议在 pytest 全绿后进行一次端到端回测验证
- 节假日硬编码整改可后续引入 `chinese_calendar` 库实现农历节日计算
