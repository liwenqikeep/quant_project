# P1 级问题与解决方案（核心功能缺口）

> 版本 v0.0.1 ｜ 2026-08-20
> 说明：P1 为核心功能缺口——不修复则设计需求 1/3/4 与验收标准不满足、数据可信度受损（建议 2–3 天完成）。

---

## P1-01 L2 硬校验违规行仍落库（数据正确性红线）

### 问题

- `data/sync.py:_fetch_and_save` 调用 `self.calibrator.calibrate(df, ...)` 后**丢弃清洗结果**，落库仍用原始 `df` 构造 bars（`_df_to_bars(df, ...)`）。
- `data/calibration.py:calibrate` 只返回 `DataCalibrationReport`（不含清洗后 DataFrame），L2 校验出的违规行仍写入 `stock_daily`，且状态为 success/partial 而非 failed。
- L2 的"日期唯一且为交易日"校验尚未实现。

### 影响

违反设计第五章"违规行不落库，整段 status=failed"的硬性要求；脏数据直接进入回测数据链路，污染策略与绩效。

### 解决方案

1. `DataCalibrator.calibrate` 改为返回 `(clean_df, report)`（或新增 `calibrate_with_data` 保持旧签名兼容）：

```python
def calibrate(
    self, df: pd.DataFrame, symbol: str, adjust_type: str
) -> tuple[pd.DataFrame, DataCalibrationReport]:
    ...
```

2. `sync._fetch_and_save` 流程调整：

```python
clean_df, report = self.calibrator.calibrate(df, symbol, adjust)
if report.has_l2_failed:
    # 整段 failed：不落库，错误详情写 data_fetch_log.error
    self._write_fetch_log(symbol, adjust, start_str, end_str, "failed", 0, "L2 校验失败")
    return FetchOutcome(symbol=symbol, status=FetchStatus.FAILED, error="L2 校验失败", ...)
bars = self._df_to_bars(clean_df, symbol, adjust)  # 只落合法行
```

3. L2 补充校验：
   - 区间内 `trade_date` 去重，重复日期判 failed；
   - 交易日校验：`trade_date` 不在交易日历判 failed（停牌日无行属正常，不在此列）。

### 验收标准

构造含非法 OHLC 行的拉取结果，同步后 `stock_daily` 无该行、`data_fetch_log.status=failed`；重复日期 / 非交易日行同样拦截。

> 复检状态（2026-08-20）：**主体已修复，存在残留**。`calibrate` 已返回 `(clean_df, report)`，sync 对 L2 违规整段 failed 且不落库，去重与非交易日校验已新增。
>
> 残留问题：
> 1. `calibrate` 的 L2 非交易日校验直接使用 `get_calendar()` 单例，不感知 `_calendar_ready` 降级状态：日历陈旧（默认 2020–2025）时，2026 年真实交易日会被判为非交易日，导致整段 failed，与 P1-05 的降级语义冲突；
> 2. `validate()` 中 `if d not in seen: continue` 为死条件（`d` 恒在 `seen` 中）。
> 建议：非交易日校验改为仅当日历可用且覆盖该日期时执行；清理死代码。

---

## P1-02 新鲜度检查失效（需求 4 核心未生效）

### 问题

- `sync._fetch_and_save` 中 `actual = self._parse_date(end_str)`，而增量模式下 `end_str` 恰好等于期望交易日，因此 `actual == expected` 恒成立，`stale` 永远为 False。
- 数据源未发布期望交易日数据时不会产生任何 stale/empty 提示，需求 4（"数据缺失有提示"）实际未实现。
- `stale_tolerance_trading_days` 已读入 `DataSyncConfig` 但从未使用。

### 解决方案

1. `actual` 改为本次拉取结果的最大 `trade_date`：

```python
actual = df.index.max().date() if len(df) else None
```

2. 判定逻辑（容忍度语义与技术负责人确认后定稿）：

```python
if actual is None:
    status, message = "empty", f"数据源无 [{start}, {end}] 数据"
else:
    lag_days = len(cal.get_trading_days_between(actual, expected))
    if actual < expected and lag_days > stale_tolerance_trading_days:
        status, message = "stale", f"期望最新 {expected}，数据源实际 {actual}"
    elif actual < expected:
        status, message = "partial", f"数据源尚未发布 {expected}，最新截至 {actual}"
    else:
        status, message = "success", None
```

3. `message` 走 `FetchOutcome.message` + `logger.warning`；`stale/empty` 写入 `data_fetch_log.status`；`_build_detail` 的 `freshness` 段保留。
4. 与设计 6.2 示例（滞后 1 交易日即提示 stale）的对齐：本文档采用"容忍度内为 partial、超容忍度为 stale"语义，避免在容忍度内也告警风暴。

### 验收标准

mock 数据源返回截止到前一天的数据 → 同步结果带提示文本且 `status=stale`（或容忍度内 `partial`）；无任何数据 → `status=empty`；非交易日 → 期望日回退上一交易日。

> 复检状态（2026-08-20）：**已修复**。`actual` 已改为本次拉取最大 `trade_date`；容忍度语义（partial/stale）与 `_build_detail` 的 freshness 段均已落地。
>
> 小瑕疵：`_fetch_and_save` 的 empty 分支把提示文本写入 `data_fetch_log.error` 列，语义应为审计提示而非错误，建议改放 `detail`。

---

## P1-03 L3 修正校准决策矩阵未实现

### 问题

- 复权漂移识别（全区间价格同比例系统性偏移）未实现；
- 所有超差差异一律标记 `KEEP_LOCAL`（"保留本地"），但 `sync` 随后仍用新数据 upsert 覆盖，决策与行为矛盾；
- `BACKFILL`（本地缺行）、`DISCREPANCY`（源缺行）两类决策从未产生；
- `calibration.enabled / price_tolerance / volume_tolerance / auto_correct_drift / alert_on_discrepancy` 配置未接入，`DataSyncService` 使用全默认 `CalibrationConfig()`；
- `CalibrationConfig` 未纳入 `DataSyncConfig.from_config`。

### 影响

校准形同虚设：漂移无法识别，超差数据无条件覆盖本地，差异无法按决策矩阵追溯，数据可信度受损。

### 解决方案

1. `DataSyncConfig` 增加 `calibration: CalibrationConfig` 字段，`from_config` 从 `data.fetch.calibration.*` 读取；`DataSyncService.__init__` 用之构造校准器，`enabled=False` 时跳过 L3（L2 仍执行）。
2. `_calibrate_overlap` 增加漂移识别：对重叠窗口内每行计算各价格列 `ratio = new / old`，若全体 ratio 近似一致（如标准差 < 0.001）且均值偏离 1 → 判定复权漂移；`auto_correct_drift=true` 时 `AUTO_CORRECT_DRIFT`，否则 `KEEP_LOCAL` + 告警。
3. 决策落地到 sync：
   - `AUTO_CORRECT_DRIFT`：新数据 upsert，逐行写校准日志（decision=drift）；
   - `KEEP_LOCAL` / `DISCREPANCY`：对应行**不覆盖**（从 bars 排除或恢复本地值），写 `data_calibration_log` + `logger.warning`；
   - 本地缺行、源有行：正常 upsert，补写 `BACKFILL` 校准日志；
   - 源缺行、本地有行：保留本地，写 `DISCREPANCY` 日志，`alert_on_discrepancy` 控制告警强度。
4. `calibrate` 返回 `(clean_df, report)`，report 携带每行决策，sync 据此决定 upsert 集合。

### 验收标准

构造五类场景（容差内一致 / 全区间同比例漂移 / 单日价格超差 / 本地缺行 / 源缺行），落库结果与 `data_calibration_log.decision` 符合设计决策矩阵；`auto_correct_drift=false` 时漂移不覆盖本地。

> 复检状态（2026-08-20）：**部分修复**。漂移识别、`KEEP_LOCAL` 跳过落库、`BACKFILL / DISCREPANCY` 决策均已实现，但存在以下残留：
>
> 1. `sync._apply_calibration` 恒返回 `issues=[]`，**校准差异从未写入 `data_calibration_log`**，违反验收"校准日志可追溯"；
> 2. `calibration.enabled` 已读入配置但从未被检查，L3 无条件执行；
> 3. 漂移 issue 的 `old_value / new_value` 通过 `"old_v" in dir()` 取上次循环残留值，写入日志的数值错误；
> 4. 重叠窗口仅 1 天时也会被判定为"复权漂移"，需限制最小样本数。
> 建议：`_apply_calibration` 返回真实校准 issue 列表；`enabled=False` 时跳过 `_calibrate_overlap`；漂移 issue 记录每行实际 old/new 值。

---

## P1-04 定时任务 DataSyncJob 未实现（需求 1）

### 问题

- `infrastructure/scheduler.py` 仅有 `ScheduledTasks.daily_data_update` 静态方法直接调 `run_incremental()`；
- 设计要求的职责全部缺失：读取 `data.fetch.schedule`（enabled / time / weekdays）、当日已成功不重复执行、进程内互斥、错过补跑（catch_up）、`Asia/Shanghai` 时区与交易日处理；
- `add_daily_task` 不支持 weekdays；`schedule` 配置在 config.yaml 与默认值中已存在但无代码消费。

### 解决方案

新增 `DataSyncJob`（放 `infrastructure/scheduler.py`）：

```python
class DataSyncJob:
    def __init__(self, scheduler, db, config=None): ...

    def register(self) -> str | None:
        # 读 data.fetch.schedule；disabled 返回 None
        # add_daily_task(name, self._run, hour, minute)
        # catch_up=true 且已过触发时间且当日未同步 → 立即补跑

    def _run(self):
        # 1. 互斥锁 acquire(blocking=False)，拿不到则跳过
        # 2. 当日已成功同步（data_fetch_log 当日 fetched_at 的 success/partial）
        #    → 已成功则 skipped 记日志
        # 3. 星期不在 weekdays → 跳过
        # 4. 调 DataSyncService.run_incremental()
```

配套 `Database` 新方法：

```python
def has_successful_fetch_today(
    self,
    symbol: str | None = None,
    adjust_type: str | None = None,
    today: date | None = None,
) -> bool: ...
```

时间统一 `datetime.now(ZoneInfo("Asia/Shanghai"))`（标准库 zoneinfo）。

### 验收标准

按 `default_time` 到点触发；当日已成功不重复执行；两个任务实例互斥；启动时已过触发时间且当日未同步则补跑；周末 / 非交易日跳过。

> 复检状态（2026-08-20）：**部分修复**。`DataSyncJob` 已实现（去重 / 互斥 / 补跑 / weekdays 过滤），但存在关键残留：
>
> 1. **weekday 偏移 1（需优先修复）**：config `weekdays: [1,2,3,4,5]` 按设计表示周一至周五，而代码用 `datetime.now().weekday()`（周一=0）直接比对 → 周一（0）被跳过、周六（5）会执行；
> 2. `data.fetch.schedule` 未配置 `time` 键，`DataSyncJob` 硬编码 `"17:30"`，未读取 `data.fetch.default_time`（当前与默认值一致，属一致性命中）；
> 3. 触发时间计算用本地时区，weekday 判断用 Asia/Shanghai，两处基准建议统一。

---

## P1-05 交易日历前置未实现，目标日期解析错误

### 问题

- `sync._resolve_target_date` 直接 `get_calendar()`，但从未初始化 / 更新日历；
- `utils/calendar.py` 兜底日历 `_generate_default_calendar` 仅覆盖 2020–2025，且当前数据目录（`d:/desk/code/personal/data`）不存在，无本地 `trading_days.json`；
- 2026-08-20 执行增量时，期望最新交易日会被解析为 **2025-12-31**，同步结果仍报 success——系统性滞后一年。

### 影响

目标日期解析错误，增量区间错误、新鲜度判定失真，同步结果不可信。

### 解决方案

1. `DataSyncService` 增加 `_ensure_calendar()`：同步开始前若日历为空或最新日期早于今天前一年，调用 `TradingCalendar.update_calendar()`（`ak.tool_trade_date_hist_sina()`）；
2. 拉取失败：不抛异常，置 `self._calendar_ready = False`，`_resolve_target_date` 降级返回"今天"，并在报告中给出明确提示（设计 12.9：降级为提示而非静默）；freshness 判定跳过；
3. 日历数据同步写入 `trade_calendar` 表（`utils.calendar` 保持单一事实来源，storage 侧提供落库方法）；
4. 补充测试：mock 日历失败 → 不抛异常且有提示；日历含 2026 数据 → 期望日解析正确。

### 验收标准

首次同步前自动初始化日历；2026 年增量区间 end 解析为真实最近交易日；日历不可用时降级提示且不静默。

> 复检状态（2026-08-20）：**部分修复**。`_ensure_calendar` 与降级返回今天已实现，但存在残留：
>
> 1. `TradingCalendar.update_calendar` 内部 try/except 吞掉异常（只记日志不抛），`_ensure_calendar` 的降级分支永远不会触发，`_calendar_ready` 恒为 True；
> 2. 日历为空且 `target_date_mode="today"` 时，`get_previous_trading_day` 会死循环；
> 3. `_ensure_calendar` 更新的是新建 `TradingCalendar()` 实例，而 `validate` / `_resolve_target_date` 用 `get_calendar()` 单例，两处数据源可能不一致（建议统一更新单例并刷新）；
> 4. 与 P1-01 残留联动：日历陈旧时 L2 非交易日校验会误杀真实交易日数据。

---

## P1-06 新链路未使用 DataFetchError

### 问题

- 设计第十一节与技能红线要求"数据获取失败必须抛 DataFetchError 或返回失败清单"；
- `AkshareAdapter` 失败抛 `RuntimeError`，列缺失也抛 `RuntimeError`；`DataFetchError` 只在旧 `fetcher.py` 定义且未被新链路使用。

### 影响

异常语义不统一，调用方无法按业务异常分类处理；新链路依赖 `except Exception` 兜底，掩盖错误类型。

### 解决方案

1. 新建 `data/errors.py` 定义 `DataFetchError(Exception)`（带 symbol / interval 上下文），从 `data/__init__.py` 导出；
2. `AkshareAdapter.get_stock_history / _normalize` 抛 `DataFetchError`；
3. `sync._fetch_and_save` 优先捕获 `DataFetchError` 计入失败清单，`except Exception` 仅作兜底；
4. 旧 `fetcher.py` 的 `DataFetchError` 改为从 errors.py 导入，避免双份定义。

### 验收标准

数据源不可用 / 重试耗尽 / 列缺失均抛 `DataFetchError`；同步失败清单 `error` 带 symbol 与区间上下文。

> 复检状态（2026-08-20）：**已修复**。`data/errors.py` 已建，adapter 抛 `DataFetchError`，sync 优先捕获，fetcher 与 `data/__init__.py` 均已复用导出。

---

## P1 总体验收

1. L2 违规不落库、整段 failed；
2. 数据源缺当日数据时返回 stale/empty 提示（message + 日志 + 审计）；
3. L3 五类决策行为与设计矩阵一致，校准日志可追溯；
4. 定时任务四要素（到点 / 去重 / 互斥 / 补跑）通过测试；
5. 交易日历自动初始化且失败降级提示；
6. 新链路统一 DataFetchError。
