# P1-02: 漂移识别数据量阈值缺失

**Type:** task
**Status:** ready-for-agent
**Priority:** P1

## Problem

漂移识别条件 `std_ratio < 0.001 and abs(mean_ratio - 1.0) > 0.001` 仅在 drift_ratios 非空时触发。若重叠窗口数据量很少（1-2天），统计不可靠。

## Solution

增加数据量阈值检查：
```python
if len(drift_ratios) >= 5:  # 至少5个点才做漂移识别
    # ... 漂移处理逻辑
```

## Files

- `backend/quant/data/calibration.py`

## Verification

数据量不足5时不触发漂移识别
