# P0-02: calibrate 仍在删除 L2 校验失败行

**Type:** task
**Status:** ready-for-agent
**Priority:** P0

## Problem

`calibration.py:86` 执行 `df_valid = df[valid_mask]` 删除 L2 校验失败行，违反"数据清洗禁止删除时间行"红线。

## Solution

1. `calibrate()` 方法直接返回全量 df，不执行 `df_valid = df[valid_mask]`
2. `sync.py` 调整逻辑：若 `has_l2_failed` 则整段不落库；若 `not has_l2_failed` 则取 `df[valid_mask]` 用于后续流程

```python
def calibrate(self, df, symbol, adjust_type):
    valid_mask, l2_issues = self.validate(df, symbol)
    # 不执行 df_valid = df[valid_mask]
    report = DataCalibrationReport(...)
    return df, report  # 返回全量 df
```

## Files

- `backend/quant/data/calibration.py`
- `backend/quant/data/sync.py`

## Verification

`pytest backend/quant/tests/test_data_sync.py -v` 全绿
