# P2-04: simple_db 模式下 get_stock_daily 静默返回空

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P2

## Problem

`database.py:607-608` simple_db 路径直接返回空 DataFrame，无日志警告，用户无法判断原因。

## Solution

增加日志警告：
```python
if self.simple_db:
    logger.warning("SimpleDatabase 不支持 get_stock_daily，返回空 DataFrame")
    return pd.DataFrame()
```

## Files

- `backend/quant/storage/database.py`

## Verification

simple_db 模式下调用 get_stock_daily 输出警告日志
