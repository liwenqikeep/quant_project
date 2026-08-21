# P0-04: _calibrate_overlap 重复设置索引

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P0

## Problem

`calibration.py:341-342` 对已设 index 的 DataFrame 再次调用 `set_index("trade_date")`，形成 MultiIndex，破坏 loc 查询。

## Solution

```python
if "trade_date" in df_local.columns and df_local.index.name != "trade_date":
    df_local = df_local.set_index("trade_date")
```

## Files

- `backend/quant/data/calibration.py`

## Verification

测试：本地数据已有 index 时不产生 MultiIndex
