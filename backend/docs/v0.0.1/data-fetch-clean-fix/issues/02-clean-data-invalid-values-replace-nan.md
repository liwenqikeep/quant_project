# P0-02: clean_data 非法价格/成交量直接删行

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P0

## Problem

`processor.py:159-170` 通过 `df = df[~invalid_close]` 和 `df = df[~invalid_volume]` 直接删除非法值行，应改为 NaN 替换。

## Solution

```python
if "close" in df.columns:
    invalid_close = (df["close"] <= 0) | df["close"].isna()
    if invalid_close.any():
        logger.warning(f"发现 {invalid_close.sum()} 条非法收盘价，替换为 NaN")
        df.loc[invalid_close, "close"] = np.nan

if "volume" in df.columns:
    invalid_volume = (df["volume"] < 0) | df["volume"].isna()
    if invalid_volume.any():
        logger.warning(f"发现 {invalid_volume.sum()} 条非法成交量，替换为 NaN")
        df.loc[invalid_volume, "volume"] = np.nan
```

## Files

- `backend/quant/data/processor.py`

## Verification

测试用例：非法价格/成交量行被保留，仅值变为 NaN
