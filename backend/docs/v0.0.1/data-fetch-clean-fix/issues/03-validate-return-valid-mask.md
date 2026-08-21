# P0-03: validate L2 校验失败后删行

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P0

## Problem

`calibration.py:279-286` 通过集合过滤删 DataFrame 行，违反不删行红线。

## Solution

`validate` 方法改为返回 `(valid_mask: pd.Series, issues: list)`，调用方通过 valid_mask 过滤。

```python
def validate(self, df: pd.DataFrame, symbol: str) -> tuple[pd.Series, list[CalibrationIssue]]:
    # ... 校验逻辑 ...
    failed_dates = {issue["trade_date"] for issue in issues if issue["decision"] == "failed"}
    valid_mask = pd.Series([d not in failed_dates for d in dates], index=df.index)
    return valid_mask, issues
```

调用方 `sync.py` 使用 valid_mask 过滤。

## Files

- `backend/quant/data/calibration.py`
- `backend/quant/data/sync.py`

## Verification

`pytest backend/quant/tests/test_calibration.py -v` 全绿
