# AKShare 数据获取功能技术实现设计

> 版本 v0.0.1 ｜ 2026-08-19 ｜ 适用：`backend/quant/data` + `backend/quant/storage` + `backend/quant/infrastructure/scheduler`
> 上游基线：[2026-08-19-ashare-data-fields-tables.md](./2026-08-19-ashare-data-fields-tables.md)（字段与表设计，本设计以其为数据模型基线）
> 状态：待技术负责人评审后拆分开发任务

---

## 一、需求目标与设计对应

目标：以 AKShare 为默认数据源，实现**可定时执行、可增量获取、数据可校准、默认获取时间可配置且数据缺失有提示**的 A 股日线数据同步链路，并为后续策略/回测提供口径统一的规范化数据。

| # | 功能需求 | 设计决策 | 落点模块 |
|---|---------|---------|---------|
| 1 | 可以定时执行 | 双通道：进程内调度器（复用 `infrastructure/scheduler.py`）+ 系统级定时任务（CLI 入口），支持每日定时、错过补跑、重复执行互斥 | `infrastructure/scheduler.py`、`quant/scripts/data_download.py` |
| 2 | 可以增量获取数据 | 以 `data_fetch_log` 成功断点为续拉依据，首次全量回填，增量带尾部重叠窗口，`upsert` 幂等落库 | `quant/data/sync.py`、`quant/storage/database.py` |
| 3 | 数据校准 | 三层：规范校准（列映射/单位/代码后缀）→ 质量硬校验（OHLC 等，违规不落库）→ 修正校准（重叠窗口与本地对比、复权漂移识别、自动覆盖或告警），校准明细落 `data_calibration_log` | `quant/data/base_data_source.py`、`quant/data/calibration.py` |
| 4 | 全局默认获取时间可配置，数据源无对应时间数据时给出提示 | `data.fetch.default_time` 配置每日默认触发时间；`target_date_mode` 定义期望最新数据日；拉取后做新鲜度检查，缺数据返回 `stale/empty` 状态并给出明确提示文本 | `quant/data/sync.py`、`quant/config` 三处同步 |
| 5 | 其他注意事项 | 网络重试/限流、停牌与缺失行、复权因子漂移、幂等与并发互斥、审计可观测、存储兼容、测试与验收 | 全文第十二节 |

---

## 二、总体架构

### 2.1 模块划分

```text
backend/quant/
├── data/                      # core：数据链路主体
│   ├── base_data_source.py    # 重构：AkshareAdapter 列映射/单位换算/重试超时（修复 12 列问题）
│   ├── fetcher.py             # 重构：单标的获取 + 空结果显式状态（不再静默返回空 DataFrame）
│   ├── models.py              # 新增：结果载体 dataclass 与枚举（FetchOutcome/BatchFetchReport 等）
│   ├── sync.py                # 新增：DataSyncService 增量区间计算、批量编排、新鲜度提示、审计
│   └── calibration.py         # 新增：DataCalibrator 质量校验、重叠窗口校准、漂移识别、校准报告
├── storage/database.py        # 新增 StockDaily/DataFetchLog/TradeCalendar/DataSource/DataCalibrationLog
│                              # 模型与 upsert、断点查询方法（保留旧模型兼容）
├── infrastructure/scheduler.py# ext：注册每日数据同步任务（复用既有调度器；ext 改动理由见 3.1）
├── scripts/data_download.py   # CLI：full / incremental / calibrate / status（供系统级定时调用）
└── config.yaml                # 新增 data.fetch 段（三处同步，见第九节）
```

### 2.2 依赖方向

- `infrastructure`（ext，含调度器）→ `data`（core）：调度器只负责“到点调用”，业务编排在 core，不反向依赖。
- `data` → `storage`：落库与断点查询走 `storage` 公共导出；`data` 不直接访问 `storage` 私有符号。
- 数据流维持单向：`data → strategies → backtest → risk → execution`，本设计不引入反向依赖。
- 交易日历统一使用 `quant.utils.calendar`（后续升级为 `trade_calendar` 表数据源），禁止业务模块自行实现日历逻辑。

### 2.3 同步链路总览

```text
定时触发 / CLI 调用
  → 解析目标区间（断点 + 重叠窗口 + 期望最新交易日）
  → fetch（单标的，重试/超时/限流）
  → normalize（列映射、单位换算、symbol 加后缀）
  → validate（硬校验，违规段判 failed 不落库）
  → calibrate（重叠窗口与本地对比 + 漂移识别 + 决策）
  → upsert（INSERT ... ON CONFLICT DO UPDATE，幂等）
  → audit（写 data_fetch_log）
  → freshness（新鲜度检查，缺数据返回 stale/empty 提示）
  → report（BatchFetchReport 汇总 + 日志 + 失败清单）
```

---

## 三、定时执行设计（需求 1）

### 3.1 双通道方案

| 通道 | 实现 | 适用场景 | 说明 |
|------|------|---------|------|
| A. 进程内调度器 | 扩展 `infrastructure/scheduler.py`，注册每日数据同步任务 | 本地常驻、开发调试、与 API 服务同进程 | ext 模块改动理由：定时执行是既有 `TaskScheduler` 的职责，属预留/实验基础设施；核心同步逻辑全部在 core，本处仅做“到点调用 + 补跑 + 互斥”薄封装 |
| B. 系统级定时 | CLI `python -m quant.scripts.data_download incremental` + Windows 计划任务 / crontab | 生产环境、进程退出后仍可靠 | 推荐正式环境使用，调度与业务进程解耦，天然具备重启持久性 |

### 3.2 任务注册与触发配置

`DataSyncJob`（放在 `infrastructure/scheduler.py` 或独立 `data_jobs.py`）职责：

1. 从配置读取 `data.fetch.schedule`（`enabled` / `time` / `weekdays`），用 `add_daily_task` 注册每日任务；
2. 到点调用 `DataSyncService.run_incremental()`；
3. 执行前检查“当日是否已成功同步过”（依据 `data_fetch_log` 中当日 `fetched_at` 的成功记录），避免重复执行；
4. 进程内互斥：`Event`/标志位防止上一个任务未结束又触发下一次；
5. 补跑（`catch_up: true`）：若进程启动时已过当日触发时间且当日未同步，则立即补跑一次。

### 3.3 补跑与互斥规则

- 幂等：每次运行前先查“当日成功断点”，已成功则 `skipped` 并记日志，不重复拉取。
- 互斥：同一进程内加运行锁；跨进程场景由系统级调度器保证单实例（或使用 `data_fetch_log` 当日成功记录作为分布式幂等依据）。
- 时区：统一 `Asia/Shanghai`，日期边界以交易日历为准（周末/节假日自动顺延到下一交易日触发或跳过）。
- 失败处理：单次运行失败不阻塞下次；连续失败进入 `data_fetch_log`（`status=failed`），供人工/告警追踪。

---

## 四、增量获取设计（需求 2）

### 4.1 增量断点

断点唯一来源为 `data_fetch_log`：对每个 `(symbol, adjust_type, source)` 取最近一次 `status in (success, partial)` 的 `end_date`。

### 4.2 区间计算规则

```text
若断点不存在（首次）：
  start = data.fetch.backfill_start          # 默认 20000101
否则：
  start = 断点 end_date - data.fetch.lookback_days（自然日，重叠窗口，用于校准）
  start = max(start, backfill_start)
end = resolve_target_end()                    # 见第六节，默认最近交易日
若 start > end：本轮跳过（skipped，记日志，不写 failed）
```

说明：

- 重叠窗口（默认 10 个自然日）用于重新拉取尾部数据，覆盖三类修正：除权除息复权价更新、数据源回补/修订、前日快照错误。
- 区间边界对齐交易日历：`start` 落到交易日，非交易日自动取下一交易日。
- 增量模式下 `end` 不允许超过“今天”，防止未来数据（呼应回测红线：禁止未来函数）。
- 首次全量回填量较大，`batch_size`（默认 20）分片提交，每片完成后写 `data_fetch_log`，中断后可续拉。

### 4.3 幂等落库

- `stock_daily` 唯一键 `(symbol, trade_date, adjust_type)`，写入统一走 `INSERT ... ON CONFLICT DO UPDATE`（SQLite upsert）。
- 同一区间重复执行不产生重复行；校准后新值覆盖旧值并更新 `updated_at`。
- 停牌日无 K 线行：**禁止补造数据行**；缺失行由交易日历对比识别为“停牌/未上市”，不视为异常（见 12.2）。

### 4.4 批量编排与失败隔离

- 默认单标的串行（`max_workers=1`），避免触发 AKShare 限流；如需提速再按配置调大并发。
- 单标的失败不影响其他标的：失败进入 `failures` 清单并写 `data_fetch_log(status=failed)`，整批返回 `BatchFetchReport`。
- 请求间隔 `request_interval_seconds`（默认 0.5s）做礼貌限流。

---

## 五、数据校准设计（需求 3）

校准分三层，职责严格分离：

| 层级 | 名称 | 内容 | 违规处理 |
|------|------|------|---------|
| L1 | 规范校准（normalize） | 原始列 → 规范列显式映射；单位统一（成交额=元、成交量=手、涨跌幅/振幅/换手 ÷100 转小数）；symbol 加后缀；date 转 `date` | 列缺失/单位无法识别 → 该段判 failed，抛 `DataFetchError` |
| L2 | 质量硬校验（validate） | OHLC 关系、价格 > 0、volume/amount 非负、日期唯一且为交易日 | 违规行不落库，整段 `status=failed`，记录错误详情 |
| L3 | 修正校准（calibrate） | 重叠窗口与本地数据逐字段对比；复权漂移识别；决策自动覆盖或保留+告警 | 超差且不在白名单 → 保留本地，写 `data_calibration_log` 并告警 |

### 5.1 L2 硬校验规则

- `high >= max(open, close)` 且 `low <= min(open, close)`；
- `open/high/low/close > 0`，`volume >= 0`、`amount >= 0`；
- `trade_date` 落在交易日历内且区间内无重复日期；
- 涨跌停/一字板日 `amplitude=0、change_pct=0` 属合法，不得误删（呼应上游文档口径）。

### 5.2 L3 修正校准规则与决策矩阵

对比对象：增量请求中的重叠窗口（新拉数据）与库中同 `(symbol, trade_date, adjust_type)` 的存量数据。

| 对比结果 | 判定 | 决策 |
|---------|------|------|
| 差异均在容差内（价格 `price_tolerance` 默认 0.001、量 `volume_tolerance` 默认 0.01） | 一致 | 正常 upsert，记 `calibration_ok` |
| 全区间所有价格列同比例系统性偏移（qfq/hfq 复权因子更新） | 复权漂移 | `auto_correct_drift=true` 时自动采纳新数据并逐行记录；否则仅告警 |
| 本地缺行、源有行 | 数据回补（含停牌补录） | 正常 upsert 补入 |
| 源缺行、本地有行（除已确认停牌/退市） | 源侧缺失 | 保留本地，标记 `discrepancy` 并告警，禁止删除 |
| 单日少数列超差（价格/量不符） | 疑似源修订或错误 | 保留本地 + 写 `data_calibration_log` + 告警人工复核（`alert_on_discrepancy=true`） |

### 5.3 校准报告与落库

- `DataCalibrationReport`（dataclass）：检查项、通过数、自动修正数、discrepancy 数、建议；
- 逐条差异写 `data_calibration_log` 表（见 8.3），支持追责与回滚审计；
- 校准摘要写入当日 `data_fetch_log` 的 `detail`（JSON 扩展字段）。

---

## 六、默认获取时间与数据可用性提示（需求 4）

### 6.1 配置语义

| 配置键 | 语义 |
|--------|------|
| `data.fetch.default_time`（默认 `17:30`） | 全局默认数据获取时间：每日定时任务的默认触发时间，同时是“期望数据截至时点”的基准（A 股日线一般在收盘后一段时间发布） |
| `data.fetch.target_date_mode`（默认 `last_trade_date`） | 期望最新数据日解析方式：`last_trade_date`=日历中 ≤ 今天的最近交易日；`today`=今天（非交易日时回退上一交易日） |
| `data.fetch.stale_tolerance_trading_days`（默认 1） | 数据源最新数据滞后容忍度（交易日） |

### 6.2 新鲜度检查与提示

每次同步结束后执行：

```text
expected = 目标模式下期望的最新交易日（来自交易日历）
actual   = 本次/库中该 (symbol, adjust_type) 的最大 trade_date
若 actual 不存在        → status=empty，提示“数据源无该区间数据”
若 actual < expected    → status=stale，提示“数据源尚未发布 expected 的数据，最新数据截至 actual”
若 actual >= expected   → status=success/partial
```

提示落地方式（非静默，满足“没有对应时间的数据给出提示”）：

1. 返回结果携带 `message` 字段（结构化文本，含 symbol、expected、actual）；
2. `logger.warning` 输出带上下文的提示；
3. `data_fetch_log.status = stale/empty`，可选接入 `AlertManager` 通知；
4. `stale/empty` 不计为失败（不触发重试风暴），但会写入审计供日报展示。

典型场景示例：`default_time=17:30`，但数据源 18:30 才更新当日数据 → 17:30 同步返回 `stale`，提示“600519.SH 期望数据截至 2026-08-19，数据源最新 2026-08-18”；用户可调整 `default_time` 或在 `stale_tolerance_trading_days` 内容忍。

---

## 七、关键流程与状态定义

### 7.1 增量同步流程

```text
run_incremental()
 1. 读取配置（default_time / incremental / lookback_days / calibration）
 2. 解析标的池（config.data.stock_pool，可被 CLI --symbols 覆盖）
 3. 对每个 symbol：
    a. 查 data_fetch_log 断点 → 计算 [start, end]
    b. start > end → skipped，继续下一个
    c. DataFetcher 拉取（重试/超时）
    d. normalize → validate
    e. calibrate（重叠窗口对比）
    f. upsert_stock_daily
    g. 写 data_fetch_log（含 duration_ms / row_count / detail）
 4. freshness 检查 → 汇总 BatchFetchReport
 5. 日志输出 + 失败清单 + 可选告警
```

### 7.2 获取状态枚举

```text
success   成功（达到期望最新交易日）
partial   部分成功（含 stale/校准差异，但已写入可用的最新数据）
failed    硬失败（网络/校验，未落库）
empty     数据源无该区间数据
stale     数据源未发布期望交易日数据（有提示文本）
skipped   断点已覆盖目标区间，无需拉取
```

---

## 八、数据模型与存储变更

### 8.1 表清单

| 表 | 来源 | 说明 |
|----|------|------|
| `stock_daily` | 上游文档 | 日线行情（唯一键 symbol+trade_date+adjust_type） |
| `stock_basic` | 上游文档 | 股票基础信息 |
| `trade_calendar` | 上游文档 | 交易日历（同步任务的前置依赖） |
| `data_fetch_log` | 上游文档 | 拉取审计（增量断点 + 失败追踪），新增 `detail` JSON 扩展字段 |
| `data_source` | 上游文档 | 数据源登记（akshare/tushare） |
| `data_calibration_log` | **本设计新增** | 校准明细（差异追责与回滚依据） |

### 8.2 `data_fetch_log` 增量扩展

```sql
ALTER TABLE data_fetch_log ADD COLUMN detail TEXT;  -- JSON：校准摘要、stale 提示、行数明细
CREATE INDEX idx_fetch_log_breakpoint
    ON data_fetch_log (symbol, adjust_type, status, end_date);
```

### 8.3 新增 `data_calibration_log`

```sql
CREATE TABLE data_calibration_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT    NOT NULL,
    trade_date    DATE    NOT NULL,
    adjust_type   TEXT    NOT NULL,
    field         TEXT    NOT NULL,          -- 差异字段，如 close / volume
    old_value     REAL,
    new_value     REAL,
    diff_ratio    REAL,                      -- 相对偏差
    decision      TEXT    NOT NULL,          -- auto_correct / keep_local / backfill / drift
    message       TEXT,
    checked_at    DATETIME NOT NULL
);
CREATE INDEX idx_calib_log_symbol ON data_calibration_log (symbol, trade_date);
```

### 8.4 `Database` 新增方法（建议签名）

```python
def upsert_stock_daily(self, bars: list[DailyBar]) -> int: ...
def get_latest_success_fetch(self, symbol: str, adjust_type: str, source: str) -> DataFetchLog | None: ...
def insert_fetch_log(self, log: DataFetchLog) -> int: ...
def get_stock_daily(self, symbol: str, start: date, end: date,
                    adjust_type: str = "qfq") -> pd.DataFrame: ...
def get_latest_trade_date(self, symbol: str, adjust_type: str) -> date | None: ...
def save_calibration_logs(self, issues: list[CalibrationIssue]) -> int: ...
```

说明：保留旧 `StockData`/JSON 路径仅作兼容，不再新增写入；新链路统一走 SQLite。

---

## 九、配置变更（三处同步，呼应 AGENTS.md 4.4）

### 9.1 `config.yaml` 新增

```yaml
data:
  adjust: "qfq"                 # 默认复权类型："" / qfq / hfq
  storage:
    format: "sqlite"            # sqlite（当前）| parquet（预留）
  fetch:
    default_time: "17:30"       # 全局默认获取时间（HH:MM）
    target_date_mode: "last_trade_date"   # last_trade_date | today
    stale_tolerance_trading_days: 1
    retry: 3                    # 失败重试次数
    timeout_seconds: 20         # 单请求超时
    backoff_base_seconds: 1     # 指数退避基数
    incremental: true           # 是否增量续拉
    lookback_days: 10           # 增量尾部重叠窗口（自然日），校准用
    backfill_start: "20000101"  # 首次全量回填起点
    batch_size: 20              # 每批标的数
    max_workers: 1              # 并发请求数（默认 1 防限流）
    request_interval_seconds: 0.5
    schedule:
      enabled: true
      weekdays: [1, 2, 3, 4, 5] # 周一至周五
      catch_up: true            # 错过触发时间后补跑
    calibration:
      enabled: true
      price_tolerance: 0.001
      volume_tolerance: 0.01
      auto_correct_drift: true
      alert_on_discrepancy: true
```

### 9.2 `ConfigManager._init_default_config` 同步

`data` 段默认值加入 `adjust`、`storage.format`、`fetch.*`（与 yaml 一致），保证无配置文件时行为相同。

### 9.3 `_validate_required_keys` 纳入必填

```text
data.adjust
data.storage.format
data.fetch.default_time
data.fetch.retry
data.fetch.incremental
data.fetch.backfill_start
```

---

## 十、命令与接口

### 10.1 CLI（`quant/scripts/data_download.py`）

```bash
python -m quant.scripts.data_download incremental [--symbols 600519.SH,000001.SZ] [--adjust qfq]
python -m quant.scripts.data_download full        [--start 20000101] [--end 20260819]
python -m quant.scripts.data_download calibrate   [--symbols ...] [--window 10]
python -m quant.scripts.data_download status      [--symbols ...]
```

- 输出：`BatchFetchReport` 结构化汇总（总数/成功/失败/跳过/stale 提示/失败清单）到日志与 stdout；
- 退出码：0=全部成功或按预期跳过；1=存在 failed；2=配置/参数错误；
- `--dry-run` 仅打印计划区间不实际拉取。

### 10.2 API 边界

本设计**不新增 HTTP 接口**。若后续要在 `/api/v1` 暴露“手动触发同步/查看同步状态”，必须先改 `docs/api-integration.md` 契约（统一响应/分页/错误码基线）再实现，当前不展开。

---

## 十一、错误处理与失败清单

- 网络/接口错误：重试 `retry` 次（指数退避 `backoff_base_seconds`），全部失败抛 `DataFetchError` 并入失败清单，**禁止静默返回空 DataFrame**；
- 数据为空：返回 `FetchOutcome(status=empty, message=...)` 而非空 DataFrame 静默通过；
- 硬校验失败：该段 `status=failed`，错误详情写 `data_fetch_log.error`；
- 批量运行：`stop_on_error` 默认 False，失败隔离，汇总清单返回调用方；
- 日志：一律 `quant.utils.logger`，错误带 `symbol/task_id/区间` 上下文，禁止 print/裸 except。

---

## 十二、其他注意事项（需求 5）

1. **akshare 12 列修复**：`AkshareAdapter.get_stock_history` 必须按“原始列 → 规范列”映射字典重命名，修复上游文档第六节列错位问题；`stock_zh_a_daily` 备用接口单位差异（volume=股、turnover=小数）在 normalize 层统一。
2. **网络与限流**：配置化超时/重试/请求间隔/并发；本机代理环境下东财接口偶发断连，重试后成功（沿用上游实测结论）；禁止硬编码。
3. **停牌与缺失行**：停牌日无 K 线属正常，禁止补造；用 `trade_calendar` 对比判定“缺行原因=停牌/未上市”，不误报、不误删。
4. **复权因子漂移**：qfq/hfq 历史价随最新除权除息变化，增量重叠窗口 + L3 校准自动识别并覆盖，避免策略使用过时复权价。
5. **时区与日期**：统一 `Asia/Shanghai`；所有日期解析以交易日历为准；`end` 不超过今天，杜绝未来数据。
6. **幂等与并发**：唯一键 upsert 保证重复执行安全；调度器与 CLI 均可重复触发而不产生脏数据。
7. **审计可观测**：每次拉取写 `data_fetch_log`，校准差异写 `data_calibration_log`，增量断点、失败追踪、新鲜度提示全部可查。
8. **存储演进兼容**：新模型 `StockDaily` 与旧 `StockData` 并存，迁移决策由技术负责人确认后另行任务；JSON 路径不再新增写入。
9. **交易日历前置**：首次同步前先初始化 `trade_calendar`（`ak.tool_trade_date_hist_sina()`），日历拉取失败时禁止进行“期望最新交易日”判定（降级为提示而非静默）。
10. **依赖与配置**：新增依赖须评估并纳入 `pyproject.toml`；配置变更三处同步；提交遵循 conventional commits，一个功能一个 commit。

---

## 十三、测试计划

| 测试对象 | 用例 |
|---------|------|
| 适配器 | 12 列映射、单位换算（手/元/小数）、symbol 后缀、空返回、超时/重试后失败 |
| 增量断点 | 空库首拉全量、有断点续拉、断点被 `lookback` 前移、start>end 跳过、部分失败后续拉 |
| 幂等 | 同区间重复写入不产生重复行、upsert 覆盖更新 `updated_at` |
| 校准 | OHLC 非法行拦截、涨跌停 0 振幅不误删、重叠窗口一致/漂移/单日超差/源缺行/本地缺行决策 |
| 新鲜度提示 | 数据源无当天数据→stale+提示文本；无任何数据→empty；非交易日→目标回退上一交易日 |
| 定时 | 到点触发、错过补跑、当日已成功不重复执行、互斥锁生效 |
| CLI | full/incremental/calibrate/status 退出码、--dry-run 不落库、参数错误码 |
| 配置 | 三处同步一致、必填键缺失告警、默认值生效 |
| 回归 | `pytest` 全量绿 + 存量用例无回归；新代码 `ruff check` 0 error + `ruff format --check` |

---

## 十四、实施拆分与验收标准

### 14.1 Commit 拆分（建议顺序）

1. `docs: AKShare 数据获取功能技术实现设计`（本文档）
2. `refactor: AkshareAdapter 列映射与单位换算、重试超时`（修复 12 列问题）
3. `feat: 新增数据模型与 upsert/断点查询`（StockDaily/DataFetchLog/TradeCalendar/DataCalibrationLog）
4. `feat: DataSyncService 增量区间计算与批量同步`
5. `feat: DataCalibrator 数据校准与报告`
6. `feat: 默认获取时间与数据新鲜度提示`
7. `feat: 定时任务接入与 CLI`
8. `test: 数据同步全链路测试`

### 14.2 验收标准

1. 定时任务按 `default_time` 配置触发，错过可补跑，重复触发互斥且幂等；
2. 增量从 `data_fetch_log` 断点续拉，首次自动全量回填，重叠窗口校准生效，`stock_daily` 唯一键无重复；
3. 数据源无对应时间数据时返回 `stale/empty` 并给出明确提示（message+日志+审计），非静默；
4. 硬校验违规不落库，校准差异有 `data_calibration_log` 可追溯；
5. `pytest` 全量通过、存量用例无回归、`ruff check` 0 error、`ruff format --check` 通过；
6. 配置 `config.yaml`、`ConfigManager` 默认值、必填键三处同步。
