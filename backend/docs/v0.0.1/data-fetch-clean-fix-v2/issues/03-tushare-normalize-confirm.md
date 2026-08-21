# P1-01: TushareAdapter._normalize 是否被调用存疑

**Type:** task
**Status:** ready-for-agent
**Priority:** P1

## Problem

`_normalize` 方法存在于 `base_data_source.py`，需确认 `get_stock_history` 是否调用了它。

## Solution

在 `get_stock_history` 末尾确认：
```python
return self._normalize(df)
```

## Files

- `backend/quant/data/base_data_source.py`

## Verification

TushareAdapter 返回列名与 AKShare 一致
