# P2-01: validate 逐行 iterrows 性能差

**Type:** task
**Status:** ready-for-agent
**Priority:** P2

## Problem

OHLC 关系校验仍用 `for idx in df.index[high_invalid]:` 逐行迭代。

## Solution

使用向量化布尔索引：
```python
high_invalid = h < np.maximum(o, c) - 1e-6
low_invalid = l_ > np.minimum(o, c) + 1e-6
price_invalid = (price_cols_data <= 0).any(axis=1)
volume_invalid = (vol < 0) | (amt < 0)
```

## Files

- `backend/quant/data/calibration.py`

## Verification

性能测试：10k 行数据校验时间 < 1s
