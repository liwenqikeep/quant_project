# P0-05: 非交易日校验误判停牌日

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P0

## Problem

`calibration.py:171-194` 将日历中不存在的日期（停牌日）标记为 failed，误判合法数据。

## Solution

移除或降级非交易日校验为 WARN 级日志：
```python
# 注释掉：
# for d in all_dates:
#     if cal.trading_days and d not in set(cal.trading_days):
#         non_trading_dates.append(d)
logger.warning(f"发现 {len(non_trading_dates)} 个非交易日日期，可能为停牌日")
```

## Files

- `backend/quant/data/calibration.py`

## Verification

停牌日数据不被标记为 failed
