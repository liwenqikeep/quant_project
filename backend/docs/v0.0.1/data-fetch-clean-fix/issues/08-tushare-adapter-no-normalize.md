# P1-03: TushareAdapter 未规范化列名

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P1

## Problem

`base_data_source.py:242-268` Tushare 分支直接返回原始 DataFrame（列名 `trade_date/open/close/high/low/vol/amount`），与 AKShare 规范化列名不一致。

## Solution

在 `get_stock_history` 返回前调用 `_normalize` 方法：
```python
return self._normalize(df)
```

并实现 `_normalize` 方法将 Tushare 列名映射为规范列名。

## Files

- `backend/quant/data/base_data_source.py`

## Verification

TushareAdapter 返回列名与 AkshareAdapter 一致
