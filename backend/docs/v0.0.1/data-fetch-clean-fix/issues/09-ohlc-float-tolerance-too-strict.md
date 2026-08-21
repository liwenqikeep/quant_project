# P1-04: OHLC 浮点精度容差 1e-9 过严

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P1

## Problem

`calibration.py:226-227` 容差仅 1e-9，涨跌停附近数据因浮点精度可能误判。

## Solution

```python
if not (h >= max(o, c) - 1e-6):  # 从 1e-9 改为 1e-6
    # ...
if not (l_ <= min(o, c) + 1e-6):  # 从 1e-9 改为 1e-6
```

## Files

- `backend/quant/data/calibration.py`

## Verification

涨跌停数据不被误判为 failed
