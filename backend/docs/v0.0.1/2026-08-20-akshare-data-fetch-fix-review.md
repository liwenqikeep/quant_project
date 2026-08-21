# AKShare 数据获取修复复检记录

> 版本 v0.0.1 ｜ 2026-08-20（初检）→ 2026-08-21（复检）
> 适用：`backend/quant/data` + `backend/quant/storage` + `backend/quant/infrastructure/scheduler` + `backend/quant/scripts`
> 上游基线：[2026-08-20-akshare-data-fetch-review.md](./2026-08-20-akshare-data-fetch-review.md)
> 复检方式：代码审查 + 实际运行验证

---

## 一、修复状态总览

| 类别 | 数量 | 说明 |
|------|------|------|
| ✅ 已修复 | 10 | P0-01、P0-04、P1-01、P1-02、P1-03、P1-04、P1-06、P2-01、P2-04、额外-01 |
| ⚠️ 部分修复 | 1 | P1-05（残留：异常被吞） |
| ❌ 未修复 | 5 | P0-02、P0-03、P2-02、P2-03、P2-05、P2-06 |

**新增问题**：infrastructure/__init__.py 直接导入 APIServer，Flask 未安装时模块不可导入。

---

## 二、问题修复详情

### P0 级问题

#### P0-01: SQLAlchemy JSON 导入丢失 ✅ 已修复

**验证**：`database.py:34` 已恢复 `JSON` 导入。
```python
from sqlalchemy import (
    create_engine,
    Column,
    ...
    JSON,  # ✅ 已恢复
)
```

---

#### P0-02: pytest 无法运行 ❌ 未修复

**问题**：
1. `test_data_sync.py` 中数据库测试直接 `Database()`，未注入临时 SQLite
2. 测试断言与实现不同步

**状态**：需专项整改。

---

#### P0-03: Ruff 不达标 ❌ 未修复

**问题**：未运行 ruff 验证。

**状态**：需专项整改。

---

#### P0-04: get_config() 签名不匹配 ✅ 已修复

**修复位置**：
- `utils/paths.py:42-44` - 改为 `from quant.config import get_config_manager; cfg = get_config_manager()`
- `data/sync.py:52-54` - 改为 `from quant.config import get_config_manager; cfg = get_config_manager()`

**修复后**：
```python
# paths.py
from quant.config import get_config_manager  # ✅ 正确
cfg = get_config_manager()

# sync.py DataSyncConfig.from_config
from quant.config import get_config_manager  # ✅ 正确
cfg = get_config_manager()
```

---

### P1 级问题

#### P1-01: L2 违规不落库 + 死条件 ✅ 已修复

**修复位置**：`calibration.py:175-179`

**修复前**：
```python
for d in set(dates):
    if d not in seen:  # ❌ 死条件（d 恒在 seen 中）
        continue
```

**修复后**：
```python
all_dates = set(dates)
for d in all_dates:  # ✅ 正确遍历所有日期
    if cal.trading_days and d not in set(cal.trading_days):
        non_trading_dates.append(d)
```

---

#### P1-02: 新鲜度检查失效 ✅ 已修复

**验证**：`sync.py:394` 已改为：
```python
actual_date = clean_df.index.max().date() if len(clean_df) else None
```

---

#### P1-03: L3 校准日志未落库 ✅ 已修复

**修复位置**：
1. `calibration.py:407` - drift_ratios 现在包含 `old_v` 和 `new_v`：
   ```python
   drift_ratios.append({"date": d, "col": col, "ratio": ratio, "old_v": old_v, "new_v": new_v})
   ```

2. `calibration.py:431-432` - 修复残留值问题：
   ```python
   old_value=float(r.get("old_v")),  # ✅ 使用 drift_ratios 中的值
   new_value=float(r.get("new_v")),
   ```

3. `sync.py:448-449` - issues 现在正确添加：
   ```python
   if matched_issue:
       issues.append(matched_issue)  # ✅ issues 不再为空
   ```

---

#### P1-04: weekday 偏移 ✅ 已修复

**修复位置**：`scheduler.py:347-350`

**修复前**：
```python
today_weekday = now.weekday()  # Monday=0, Sunday=6
if today_weekday not in self.weekdays:  # weekdays=[1,2,3,4,5]
```

**修复后**：
```python
# weekday() 返回 0=周一 ... 6=周日
# 配置 weekdays=[1,2,3,4,5] 表示周一到周五（1=周一）
# 所以需要 +1 对齐：0(周一)+1=1, 6(周日)+1=7
today_weekday = now.weekday() + 1  # ✅ 转为 1=Monday, ..., 7=Sunday
```

**验证**：
- 周一 (0+1=1) in [1,2,3,4,5] = True ✅
- 周六 (5+1=6) in [1,2,3,4,5] = False ✅

---

#### P1-05: 日历降级失效 ⚠️ 部分修复

**已修复**：
- `_ensure_calendar` 实现（`sync.py:220-243`）
- 日历不可用时降级返回今天

**残留问题**：`TradingCalendar.update_calendar` 或调用处异常被吞，未重置 `_calendar_ready`。

---

#### P1-06: 新链路未使用 DataFetchError ✅ 已修复

**验证**：
- `data/errors.py` 已建立 `DataFetchError` 类
- `sync.py` 优先捕获 `DataFetchError`
- `base_data_source.py` 抛 `DataFetchError`
- `data/__init__.py` 已导出

---

### P2 级问题

#### P2-01: fetcher.py 未按设计重构 ✅ 已修复

**修复位置**：`fetcher.py:115-120`

**修复后**：
```python
if df.empty:
    raise DataFetchError(
        f"{symbol}: [{start_date}-{end_date}] 数据为空",
        symbol=symbol,
        interval=f"{start_date}-{end_date}",
    )
```

---

#### P2-02: 超时配置未生效 ⚠️ 部分修复

**已修复**：`backoff_base_seconds` 已接入配置与重试逻辑。

**残留**：`timeout_seconds` 仍未生效（signal 超时处理死代码未移除）。

---

#### P2-03: batch_size/max_workers 未使用 ❌ 未修复

`run_incremental` / `run_full` 仍为单标的串行循环。

---

#### P2-04: CLI 细节与设计不符 ✅ 已修复

`calibrate --symbols` 已改为可选，缺省取 `stock_pool`。

---

#### P2-05: 测试覆盖不足 ❌ 未修复

测试未用 tmp SQLite 注入，断言与实现不同步。

---

#### P2-06: 提交拆分与代码卫生 ❌ 未修复

无新提交；RUF001/2/3 项目级决策未定。

---

## 三、额外发现的问题

### 额外-01: storage/__init__.py 导入错误 ✅ 已修复

**修复**：`storage/__init__.py` 改为使用 `__getattr__` 延迟导入：
```python
def __getattr__(name: str):
    """延迟导入 Database/StockData/TradeRecord（仅在 SQLAlchemy 可用时）"""
    if name in ("Database", "StockData", "TradeRecord"):
        from .database import Database, StockData, TradeRecord
        return locals()[name]
    raise AttributeError(f"module 'data' has no attribute {name!r}")
```

---

### 额外-02: infrastructure/__init__.py 导入问题 ❌ 新发现问题

**问题**：`quant/infrastructure/__init__.py:6` 直接导入 `APIServer`：
```python
from .api_server import APIServer  # ❌ Flask 未安装时失败
```

**影响**：Flask 未安装时整个 `quant.infrastructure` 模块无法导入，导致 `quant.config` 加载 `ConfigManager` 时失败（因为 `infrastructure/__init__.py` 会触发导入）。

**修复建议**：参考 `storage/__init__.py` 改为 `__getattr__` 延迟导入。

---

## 四、验收标准核对

| 验收项 | 状态 | 说明 |
|--------|------|------|
| quant.storage 可导入 | ✅ | 延迟导入已实现 |
| quant.infrastructure 可导入 | ❌ | 新问题：Flask 未安装时崩溃 |
| paths.get_data_paths() 正常 | ❌ | 受 infrastructure 导入问题影响 |
| DataSyncService() 可构造 | ❌ | 受 infrastructure 导入问题影响 |
| L2 违规不落库 | ✅ | 死条件已修复 |
| 校准日志可追溯 | ✅ | issues 正确返回 |
| weekday 正确过滤 | ✅ | +1 修复 |
| 日历降级提示 | ⚠️ | 异常被吞残留 |

---

## 五、剩余工作

### 高优先级

1. **额外-02**: `infrastructure/__init__.py` 导入问题
   - 影响：`quant.config` 无法加载，导致整条链路不可用
   - 修复：改为延迟导入

2. **P0-02**: pytest 无法运行
   - 测试未用 tmp SQLite
   - 断言与实现不同步

3. **P0-03**: Ruff 不达标
   - 需运行 `ruff check --fix` + `ruff format`

### 中优先级

4. **P1-05**: 日历降级失效
   - 异常被吞导致降级不触发

5. **P2-02**: timeout_seconds 配置未生效

6. **P2-03**: batch_size/max_workers 未使用

### 低优先级

7. **P2-05**: 测试覆盖不足
8. **P2-06**: 提交拆分与代码卫生
