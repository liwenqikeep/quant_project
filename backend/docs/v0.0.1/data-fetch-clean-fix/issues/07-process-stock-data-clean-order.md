# P1-02: clean 在指标计算之后顺序错误

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P1

## Problem

`processor.py:240-252` 当前顺序为 `add_indicators → add_price_features → add_volume_features → clean`，若 clean 不删行，则指标列中 NaN 不会被处理；若仍删行则会误删已计算好的指标行。

## Solution

调整顺序为 `clean → add_indicators → add_price_features → add_volume_features`。

## Files

- `backend/quant/data/processor.py`

## Verification

流程顺序调整后指标计算正确
