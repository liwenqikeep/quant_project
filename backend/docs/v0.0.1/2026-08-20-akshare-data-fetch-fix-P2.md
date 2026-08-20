# P2 级问题与解决方案（完善项）

> 版本 v0.0.1 ｜ 2026-08-20
> 说明：P2 不影响主线正确性，但影响可维护性、工程化与使用体验（建议 2 天完成）。

---

## P2-01 fetcher.py 未按设计重构

### 问题

- 设计 2.1 要求重构 `fetcher.py`（单标的获取 + 空结果显式状态，不再静默返回空 DataFrame），git 显示该文件未修改；
- 实际链路 `DataSyncService` 直接调用 adapter，`DataFetcher` 未参与新链路。

### 解决方案（二选一，建议 A）

- 方案 A（推荐）：`DataFetcher.get_stock_history` 增加显式空态语义——空结果抛 `DataFetchError`（带明确消息），保留 `get_stock_batch` 失败清单；`DataSyncService` 维持 adapter 直连，避免重试逻辑双份维护。
- 方案 B：`DataSyncService` 改为经 `DataFetcher` 拉取，统一重试 / 超时 / 空态处理；代价是 fetcher 需支持区间、复权透传与 config 注入。
- 无论哪种方案，删除 `scripts/data_download.py` 中的 `sys.path.insert`（包安装后无需），一并消除 E402。

### 验收标准

fetcher 不再静默返回空 DataFrame；`data/__init__.py` 导出保持稳定；E402 / I001 清零。

> 复检状态（2026-08-20）：**未完成**。仅完成了 `DataFetchError` 导入去重；`get_stock_history` 仍 `if df.empty: return df` 静默返回空；`data_download.py` 的 `sys.path` 补丁与 E402 仍在。

---

## P2-02 超时与退避配置未生效

### 问题

- `_fetch_once` 定义了 `signal` 超时处理器但从未调用（Windows 无 SIGALRM，本就无效）；
- `timeout_seconds` 实际未约束请求时长；`backoff_base_seconds` 配置未读入，退避硬编码 `1.0 * 2 ** attempt`。

### 解决方案

1. 用线程 + future 超时实现（跨平台）：

```python
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

with ThreadPoolExecutor(max_workers=1) as ex:
    future = ex.submit(self._fetch_once, code, start_date, end_date, adjust)
    df = future.result(timeout=self._timeout_seconds)
```

2. `AkshareAdapter.__init__` 增加 `backoff_base_seconds`（从 config 读取），重试退避 `backoff = self._backoff_base_seconds * (2 ** attempt)`；
3. 文档注明取舍：future 超时后底层 akshare 线程仍可能继续执行至完成（守护线程随进程退出），对 CLI / 调度场景可接受。

### 验收标准

mock 拉取函数 sleep 超过 timeout → 触发重试并最终抛 DataFetchError；退避间隔与配置一致。

> 复检状态（2026-08-20）：**部分完成**。`backoff_base_seconds` 已接入配置与重试逻辑；`timeout_seconds` 仍未生效（`_fetch_once` 中 signal 死代码保留、未改用线程超时）。

---

## P2-03 batch_size / max_workers 配置未使用

### 问题

`DataSyncConfig` 读入 `batch_size`、`max_workers`，但 `run_incremental / run_full` 始终单标的串行循环。

### 解决方案

1. `max_workers > 1` 时用 `ThreadPoolExecutor` 并发拉取（默认 1 保持防限流）；
2. `batch_size` 按标的切片分批编排，每片完成后统一写 `data_fetch_log` 摘要；并发下保证每个标的的状态独立写入；
3. 请求间隔在并发场景改为配置化节流（如每 worker 内 sleep）。

### 验收标准

`max_workers=4` 并发执行结果与串行一致（幂等）；`batch_size` 生效且 fetch_log 完整。

> 复检状态（2026-08-20）：**未完成**。`run_incremental / run_full` 仍为单标的串行循环，`batch_size / max_workers` 读入后未使用。

---

## P2-04 CLI 细节与设计不符

### 问题

- `calibrate --symbols` 被设为 `required=True`，设计为可选（默认取 stock_pool）；
- `status` 对"无记录"的退出码语义未明确（当前返回 0）；`calibrate` 未指定标的时静默返回 0，与设计退出码约定不完全一致。

### 解决方案

1. `--symbols` 改为可选，缺省取 `data.stock_pool`；仍为空时打印提示并返回 0（按预期跳过）或 2（参数错误），与技术负责人确认后固定；
2. `status` 无任何记录时返回 0（可查看态），并在 `scripts/README.md` 记录退出码约定；
3. 可选增强：`--dry-run` 扩展到 full / calibrate。

### 验收标准

四种子命令在空 / 正常 / 失败场景下退出码符合约定；`--dry-run` 不写库。

> 复检状态（2026-08-20）：**已修复**。`calibrate --symbols` 已改可选，缺省取 `stock_pool`，空池返回 2；退出码约定写入 `scripts/README.md` 一项仍未做。

---

## P2-05 测试覆盖补齐（设计第十三节）

### 问题

`tests/test_data_sync.py` 仅覆盖适配器映射、部分校准、枚举、空参数边界；设计第十三节的以下用例缺失：增量断点续拉、断点被 lookback 前移、start>end 跳过、upsert 幂等（真实 SQLite）、stale/empty 新鲜度、定时任务（到点 / 补跑 / 去重 / 互斥）、CLI 退出码与 dry-run、配置三处同步一致性。

### 解决方案

新增 / 补齐（全部使用 mock adapter 与 tmp sqlite，不碰网络与真实数据目录）：

| 用例 | 要点 |
|------|------|
| 首拉全量 | 无断点 → start=backfill_start |
| 断点续拉 | 有 success 断点 → start=end-lookback |
| start>end 跳过 | 断点已覆盖 → skipped 不拉取 |
| upsert 幂等 | 同区间写两次 → 行数不变、updated_at 更新 |
| 新鲜度 | 数据源缺当天 → stale/empty + 提示；非交易日回退 |
| 调度 | 到点触发、当日去重、互斥、catch_up（mock 时钟） |
| CLI | full/incremental/calibrate/status 退出码、--dry-run 不落库 |
| 配置 | config.yaml / 默认值 / 必填键三处一致性（比对字典） |

### 验收标准

新增用例全绿；`pytest` 全量通过且不写真实数据目录。

> 复检状态（2026-08-20）：**未完成**。测试文件未随实现更新，且未注入临时 SQLite，导致 13 个用例失败（详见 P0-02 复检记录）；P2-05 列出的增量断点 / 幂等 / 调度 / CLI / 配置一致性用例均未补齐。

---

## P2-06 提交拆分与代码卫生

### 问题

- 当前 6 个修改文件 + 5 个未跟踪新文件全部未提交，与设计 14.1 的 8 个 commit 拆分不符；
- RUF001/2/3 中文标点规则对中文 docstring 全库误报，无项目级决策。

### 解决方案

1. 按设计 14.1 顺序提交（每项一个 conventional commit）：
   1. `refactor: AkshareAdapter 列映射与单位换算、重试超时`；
   2. `feat: 数据模型与 upsert/断点查询（含 JSON 导入修复）`；
   3. `feat: DataSyncService 增量区间计算与批量同步`；
   4. `feat: DataCalibrator 数据校准与报告（含 L2 落库修复）`；
   5. `feat: 数据新鲜度提示（stale/empty）`；
   6. `feat: 定时任务接入与 CLI`；
   7. `test: 数据同步全链路测试`；
   8. `style: ruff format + lint 清零`。
2. RUF001/2/3 决策（二选一）：`pyproject.toml` 增加 `extend-ignore`（推荐），或成立卫生任务统一改英文标点；决策写入本文档或 AGENTS.md。

### 验收标准

提交记录与设计 14.1 一一对应；每个提交通过 `pytest` 全量 + `ruff` 检查；无日志 / 缓存 / 数据文件入库。

> 复检状态（2026-08-20）：**未完成**。全部改动仍停留在工作区（7 个修改文件 + 9 个未跟踪文件），无任何新提交；RUF001/2/3 项目级决策未定。
