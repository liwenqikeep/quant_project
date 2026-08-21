# P1-05: 节假日硬编码与实际不符

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P1

## Problem

`calendar.py:83-98` 端午节(6,22)、中秋节(9,18)等农历节日用固定日期硬编码，与实际不符。

## Solution

`_generate_default_calendar` 优先从 akshare 获取真实日历，失败时降级为保守逻辑（所有工作日作为交易日）。

```python
def _generate_default_calendar(self):
    if AKSHARE_AVAILABLE:
        try:
            self.update_calendar()
            return
        except Exception:
            pass
    # 降级：所有工作日作为交易日
```

## Files

- `backend/quant/utils/calendar.py`

## Verification

日历包含真实节假日数据
