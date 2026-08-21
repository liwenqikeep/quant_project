# P2-01: validate 逐行 iterrows 性能差

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P2

## Problem

`calibration.py:197-276` 对每行调用 `iterrows()` 检查 OHLC 关系，数据量大时性能差。

## Solution

用向量化布尔索引一次完成所有行检查：

```python
high_invalid = df["high"] < df[["open", "close"]].max(axis=1)
low_invalid = df["low"] > df[["open", "close"]].min(axis=1)
price_invalid = (df[["open", "close", "high", "low"]] <= 0).any(axis=1)
volume_invalid = df["volume"] < 0
```

## Files

- `backend/quant/data/calibration.py`

## Verification

性能测试：10k 行数据校验时间 < 1s
