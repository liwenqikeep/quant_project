# P0-01: run_incremental 引用未定义变量 report

**Type:** task
**Status:** ready-for-agent
**Priority:** P0

## Problem

`sync.py:141` 在 for 循环内引用 `report`，但 `report` 从未在 `run_incremental` 内初始化，导致 `NameError`。

## Solution

在 `run_incremental` 的 for 循环前添加初始化：
```python
report = BatchFetchReport(total=len(symbols))
```

## Files

- `backend/quant/data/sync.py`

## Verification

运行 `pytest backend/quant/tests/test_data_sync.py::TestDataSyncServiceInterval -v` 通过
