# AKShare 数据获取修复复检记录

> 版本 v0.0.1 ｜ 2026-08-20（初检）→ 2026-08-21（复检v2）
> 适用：`backend/quant/data` + `backend/quant/storage` + `backend/quant/infrastructure/scheduler` + `backend/quant/scripts`
> 上游基线：[2026-08-20-akshare-data-fetch-review.md](./2026-08-20-akshare-data-fetch-review.md)
> 复检方式：代码审查 + 实际运行验证

---

## 一、修复状态总览

| 类别 | 数量 | 说明 |
|------|------|------|
| ✅ 已修复 | 9 | P0-01、P0-04、P1-01、P1-02、P1-03、P1-04、P1-06、P2-01、P2-04 |
| ⚠️ 部分修复 | 1 | P1-05（残留：异常被吞） |
| ❌ 未修复 | 6 | P0-02、P0-03、P2-02、P2-03、P2-05、P2-06 |
| ❌ 新 bug | 1 | storage/__init__.py 延迟导入实现错误 |

---

## 二、问题修复详情

### P0 级问题

#### P0-01: SQLAlchemy JSON 导入丢失 ✅ 已修复

**验证**：`database.py:34` 已恢复 `JSON` 导入。

---

#### P0-02: pytest 无法运行 ❌ 未修复

**问题**：测试未用 tmp SQLite，断言与实现不同步。

---

#### P0-03: Ruff 不达标 ❌ 未修复

---

#### P0-04: get_config() 签名不匹配 ✅ 已修复

**修复位置**：
- `utils/paths.py:42-44` → `from quant.config import get_config_manager; cfg = get_config_manager()`
- `data/sync.py:52-54` → `from quant.config import get_config_manager; cfg = get_config_manager()`

---

### P1 级问题

#### P1-01: L2 违规不落库 + 死条件 ✅ 已修复

**修复位置**：`calibration.py:175-179`
```python
all_dates = set(dates)
for d in all_dates:
    if cal.trading_days and d not in set(cal.trading_days):
        non_trading_dates.append(d)
```

---

#### P1-02: 新鲜度检查失效 ✅ 已修复

**验证**：`sync.py:394`
```python
actual_date = clean_df.index.max().date() if len(clean_df) else None
```

---

#### P1-03: L3 校准日志未落库 ✅ 已修复

**修复点**：
1. `calibration.py:407` - drift_ratios 包含 `old_v`/`new_v`
2. `calibration.py:431-432` - 正确获取 `r.get("old_v")`/`r.get("new_v")`
3. `sync.py:448-449` - issues 正确添加 `matched_issue`

---

#### P1-04: weekday 偏移 ✅ 已修复

**修复位置**：`scheduler.py:347-350`
```python
today_weekday = now.weekday() + 1  # ✅ 转为 1=Monday
```

**验证**：周一(0+1=1) in [1,2,3,4,5] = True ✅

---

#### P1-05: 日历降级失效 ⚠️ 部分修复

**残留问题**：`TradingCalendar.update_calendar` 异常被吞，`_calendar_ready` 未重置。

---

#### P1-06: 新链路未使用 DataFetchError ✅ 已修复

---

### P2 级问题

#### P2-01: fetcher.py 未按设计重构 ✅ 已修复

**验证**：`fetcher.py:115-120` 空 DataFrame 抛 `DataFetchError`。

---

#### P2-02: 超时配置未生效 ⚠️ 部分修复

`backoff_base_seconds` 已接入，`timeout_seconds` 仍无效。

---

#### P2-03: batch_size/max_workers 未使用 ❌ 未修复

---

#### P2-04: CLI 细节与设计不符 ✅ 已修复

---

#### P2-05/P2-06 ❌ 未修复

---

## 三、新发现的 Bug

### Bug-01: storage/__init__.py 延迟导入实现错误

**问题**：`__getattr__` 尝试从 `database.py` 导入 `StockData` 和 `TradeRecord`，但这两个类只在 `SQLALCHEMY_AVAILABLE=True` 时定义。

**错误**：
```
cannot import name 'StockData' from 'quant.storage.database'
```

**根因**：
```python
# storage/__init__.py
def __getattr__(name: str):
    if name in ("Database", "StockData", "TradeRecord"):
        from .database import Database, StockData, TradeRecord  # ❌ StockData 可能不存在
        return locals()[name]
```

当 SQLAlchemy 未安装时，`database.py` 中 `StockData` 和 `TradeRecord` 类未定义，导入失败。

**修复建议**：
```python
def __getattr__(name: str):
    if name == "Database":
        from .database import Database
        return Database
    if name in ("StockData", "TradeRecord"):
        from .database import SQLALCHEMY_AVAILABLE
        if not SQLALCHEMY_AVAILABLE:
            raise AttributeError(
                f"module 'quant.storage' has no attribute {name!r} "
                "(SQLAlchemy is not installed)"
            )
        from .database import StockData, TradeRecord
        return locals()[name]
    raise AttributeError(f"module 'quant.storage' has no attribute {name!r}")
```

---

## 四、环境依赖问题

当前验证环境缺少必要依赖，导致部分功能不可用：

| 依赖 | 状态 | 影响 |
|------|------|------|
| SQLAlchemy | ❌ 未安装 | storage 模块导入失败 |
| psutil | ❌ 未安装 | config/scheduler 等模块导入失败 |
| Flask | ⚠️ 未安装 | API 服务功能受限（运行时） |

---

## 五、验收标准核对

| 验收项 | 状态 | 说明 |
|--------|------|------|
| quant.storage 可导入 | ❌ | Bug-01：延迟导入错误 |
| paths.get_data_paths() | ❌ | 受 psutil 依赖缺失影响 |
| DataSyncService() 可构造 | ❌ | 受多模块依赖缺失影响 |
| L2 违规不落库 | ✅ | 死条件已修复 |
| 校准日志可追溯 | ✅ | issues 正确返回 |
| weekday 正确过滤 | ✅ | +1 修复 |
| 日历降级提示 | ⚠️ | 异常被吞残留 |

---

## 六、剩余工作

### 高优先级

1. **Bug-01**: `storage/__init__.py` 延迟导入修复
2. **P0-02**: pytest 修复（tmp SQLite + 断言同步）
3. **P0-03**: Ruff 达标

### 中优先级

4. **P1-05**: 日历降级异常处理
5. **P2-02**: timeout_seconds 配置生效
6. **P2-03**: batch_size/max_workers 并发

### 低优先级

7. **P2-05**: 测试覆盖补齐
8. **P2-06**: 提交拆分
