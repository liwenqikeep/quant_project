# P0-01: clean_data 使用 dropna() 删除时间序列行

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P0

## Problem

`DataProcessor.clean_data` 在 `processor.py:154` 使用 `df = df.dropna()` 删除含任意 NaN 的行，会破坏量化时间序列连续性。

## Solution

1. 移除 `dropna()` 调用
2. 非法值（价格 ≤ 0、成交量 < 0）改为 `df.loc[mask, col] = np.nan`
3. 调整 `process_stock_data` 顺序：先 clean 后 add_indicators

## Files

- `backend/quant/data/processor.py`

## Verification

`pytest backend/quant/tests/test_processor.py -v` 全绿，且清洗前后行数/索引一致
