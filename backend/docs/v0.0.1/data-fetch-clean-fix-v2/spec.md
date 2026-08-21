# 数据获取与清洗功能整改规范（第二轮）

## Problem Statement

二轮审查发现新增 P0 bug 和遗留问题：

1. **sync.py:run_incremental 必崩**：line 141 引用未定义变量 `report`，增量同步完全不可用
2. **calibration.py:calibrate 仍在删行**：line 86 `df_valid = df[valid_mask]` 删除 L2 校验失败行，违反 AGENTS.md 4.6 节红线
3. **TushareAdapter 规范化未确认**：_normalize 方法存在但需确认是否被调用
4. **漂移识别数据量阈值缺失**：重叠窗口数据量少时统计不可靠

## Solution

按三轮优先级整改：
1. **P0 紧急修复**：run_incremental 变量初始化、L2 不删行
2. **P1 重要修复**：确认 Tushare 归一化、增加漂移识别阈值
3. **P2 优化**：向量化校验、性能优化、测试补全

## User Stories

1. 作为量化运维人员，我希望 `run_incremental` 能正常运行，不抛出 NameError
2. 作为量化分析师，我希望数据清洗不删除时间序列行，保证回测时间序列连续无断裂
3. 作为量化开发者，我希望 `calibrate()` 返回全量 DataFrame，不修改行数，由调用方决定是否过滤
4. 作为量化开发者，我希望 TushareAdapter 返回的列名与 AKShare 一致（规范列名）
5. 作为量化开发者，我希望漂移识别在数据量足够时触发，避免误判
6. 作为量化开发者，我希望 OHLC 校验使用向量化布尔索引，提升性能
7. 作为量化测试工程师，我希望补充 DataSyncService.run_incremental 边界测试

## Implementation Decisions

### P0-01: run_incremental 引用未定义变量

在 `run_incremental` 的 for 循环前添加初始化：
```python
report = BatchFetchReport(total=len(symbols))
```

### P0-02: calibrate 不删行

修改 `calibrate()` 方法，直接返回全量 df：
```python
def calibrate(self, df, symbol, adjust_type):
    valid_mask, l2_issues = self.validate(df, symbol)
    # 不执行 df_valid = df[valid_mask]
    # 直接返回全量 df
    report = DataCalibrationReport(...)
    return df, report
```

`sync.py` 调整逻辑：
- 若 `has_l2_failed`，整段数据标记为 failed 不落库
- 若 `not has_l2_failed`，取 `df[valid_mask]` 用于后续流程

### P1-01: 确认 TushareAdapter._normalize 被调用

在 `get_stock_history` 末尾确认：
```python
return self._normalize(df)
```

### P1-02: 增加漂移识别数据量阈值

```python
if len(drift_ratios) >= 5:  # 至少5个点才做漂移识别
    # ... 漂移处理逻辑
```

### P2-01: 向量化 OHLC 校验

使用向量化布尔索引替代 iterrows：
```python
high_invalid = h < np.maximum(o, c) - 1e-6
low_invalid = l_ > np.minimum(o, c) + 1e-6
price_invalid = (price_cols_data <= 0).any(axis=1)
volume_invalid = (vol < 0) | (amt < 0)
```

## Testing Decisions

- `test_data_sync.py`：新增 `run_incremental` 测试用例
- `test_calibration.py`：验证 calibrate 返回全量 df
- 验收：`pytest backend/quant/tests/ -v` 全绿

## Out of Scope

- 前端相关
- 其他数据源适配器
- 回测引擎联动

## Further Notes

- P0 修复前增量同步不可用，需立即处理
- 整改完成后建议运行端到端回测验证
