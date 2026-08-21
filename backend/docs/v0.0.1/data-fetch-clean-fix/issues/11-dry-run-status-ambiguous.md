# P1-06: dry_run 模式使用 SKIPPED 状态与真实 skip 混淆

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P1

## Problem

`sync.py:264-275` dry_run 返回 `FetchStatus.SKIPPED`，与断点已覆盖目标的真实 skip 状态无法区分。

## Solution

在 `FetchStatus` 枚举中新增 `DRY_RUN = "dry_run"`：
```python
class FetchStatus(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    EMPTY = "empty"
    STALE = "stale"
    SKIPPED = "skipped"
    DRY_RUN = "dry_run"  # 新增
```

`sync.py` 中 dry_run 路径返回 `FetchStatus.DRY_RUN`。

## Files

- `backend/quant/data/models.py`
- `backend/quant/data/sync.py`

## Verification

dry_run 状态与 SKIPPED 状态可区分
