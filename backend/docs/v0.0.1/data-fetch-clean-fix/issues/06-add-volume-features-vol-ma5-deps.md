# P1-01: add_volume_features 依赖未计算的 VOL_MA5

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P1

## Problem

`processor.py:127` 假设 `VOL_MA5` 已存在，单独调用 `add_volume_features` 时会产生全 NaN 列。

## Solution

```python
if "VOL_MA5" not in df.columns:
    df["VOL_MA5"] = df["volume"].rolling(window=5).mean()
df["vol_ratio"] = df["volume"] / df["VOL_MA5"]
```

## Files

- `backend/quant/data/processor.py`

## Verification

单独调用 `add_volume_features` 时 vol_ratio 正确计算
