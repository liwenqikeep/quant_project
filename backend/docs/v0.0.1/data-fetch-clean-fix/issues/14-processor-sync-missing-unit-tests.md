# P2-03: 缺少 processor.py 和 sync.py 单元测试

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P2

## Problem

`test_data_sync.py` 仅覆盖适配器和校准器，未覆盖 `DataProcessor` 边界行为和 `DataSyncService._resolve_interval` 各场景。

## Solution

补充测试用例：
- 清洗前后行数/索引不变
- 一字板合法不删行
- winsorize 截尾行为
- `_resolve_interval` skip/breakpoint/overlap/dry_run 场景

## Files

- `backend/quant/tests/test_processor.py`
- `backend/quant/tests/test_data_sync.py`

## Verification

`pytest backend/quant/tests/ -v` 全绿
