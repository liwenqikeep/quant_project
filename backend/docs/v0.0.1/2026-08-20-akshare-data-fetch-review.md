# AKShare 数据获取实现审查结论与修复路线（总览）

> 版本 v0.0.1 ｜ 2026-08-20
> 适用：`backend/quant/data` + `backend/quant/storage` + `backend/quant/infrastructure/scheduler` + `backend/quant/scripts`
> 上游基线：[2026-08-19-akshare-data-fetch-design.md](./2026-08-19-akshare-data-fetch-design.md)
> 状态：实现未完成、验收不通过；本总览与 P0/P1/P2 三份方案文档为整改依据
> 复检记录（2026-08-20）：实现已按方案部分修复，但复检新增 P0-04（`get_config()` 签名不匹配，`DataSyncService()` 无法构造），pytest / ruff 仍不达标。

---

## 一、审查范围与结论

- 范围：对照设计文档第十四节验收标准的 6 条要求，逐项核验实现代码与运行证据。
- 实现载体：设计文档已提交（`1cb713a`），实现代码为工作区未提交改动（6 个修改文件 + 5 个未跟踪新文件）。
- 结论：**实现未完成，验收不通过**。存在阻断性回归（`quant.storage` 模块无法导入），全链路不可运行；需求 1（定时）、需求 3（校准）、需求 4（新鲜度提示）的核心语义未真正落地。

---

## 二、评审证据（实测）

| 检查项 | 结果 | 证据 |
|--------|------|------|
| 模块导入 | 复检通过 | `JSON` 导入已恢复，pytest 可正常收集 |
| DataSyncService 构造 | 复检失败（新增 P0-04） | `quant/utils/paths.py:44` 与 `sync.py` 等多处无参调用 `get_config()`，抛 `TypeError: get_config() missing 1 required positional argument: 'key'` |
| pytest 全量 | 复检失败 | `test_data_sync.py` 13 failed（含 P0-04 根因、测试未随实现更新、Database 测试未注入 tmp 库）；`test_paths.py` 5 errors 为沙箱 Temp 目录权限问题（环境性，非代码回归） |
| ruff check（相关文件） | 复检失败 | 409 处（含存量文件历史问题；新增代码中 F401×24、UP045×31、UP006×19、UP035×7、B905×3、E402×3、F821×2、F841×1 等） |
| ruff format --check | 复检失败 | 相关 10 文件中 9 个需重排 |
| 配置三处同步 | 通过 | `config.yaml` / `ConfigManager` 默认值 / 必填键均含 `data.fetch.*` |

---

## 三、问题优先级矩阵

| 编号 | 优先级 | 问题 | 涉及文件 |
|------|--------|------|----------|
| P0-01 | P0 | SQLAlchemy 导入丢失 `JSON`，storage 模块无法导入（回归） | storage/database.py |
| P0-02 | P0 | pytest 无法收集运行；新增测试依赖真实数据目录 | tests/test_data_sync.py |
| P0-03 | P0 | 新代码 ruff check / format 不达标 | 新增与修改文件 |
| P0-04 | P0 | `get_config()` 签名不匹配，`DataSyncService()` 无法构造（复检新增） | utils/paths.py、data/sync.py、scheduler.py、scripts/data_download.py |
| P1-01 | P1 | L2 硬校验违规行仍落库（数据红线） | data/sync.py、data/calibration.py |
| P1-02 | P1 | 新鲜度检查失效，stale/empty 提示不触发（需求 4） | data/sync.py |
| P1-03 | P1 | L3 决策矩阵未实现（漂移识别 / 保留本地 / 配置接入） | data/calibration.py、data/sync.py |
| P1-04 | P1 | 定时任务 DataSyncJob 未实现（需求 1） | infrastructure/scheduler.py、storage/database.py |
| P1-05 | P1 | 交易日历前置未实现，目标日期解析错误（2026 数据缺失） | data/sync.py、utils/calendar.py |
| P1-06 | P1 | 新链路未使用 DataFetchError | data/base_data_source.py、data/fetcher.py |
| P2-01 | P2 | fetcher.py 未按设计重构 | data/fetcher.py |
| P2-02 | P2 | 超时 / 退避配置未生效 | data/base_data_source.py |
| P2-03 | P2 | batch_size / max_workers 配置未使用 | data/sync.py |
| P2-04 | P2 | CLI calibrate --symbols 必填等细节与设计不符 | scripts/data_download.py |
| P2-05 | P2 | 测试覆盖不足（设计第十三节用例缺失） | backend/quant/tests/ |
| P2-06 | P2 | 提交未拆分、RUF001/2/3 中文标点规则待项目级决策 | 仓库工程规范 |

---

## 四、文档索引

- [P0 阻断级问题与解决方案](./2026-08-20-akshare-data-fetch-fix-P0.md)
- [P1 核心功能缺口与解决方案](./2026-08-20-akshare-data-fetch-fix-P1.md)
- [P2 完善项与解决方案](./2026-08-20-akshare-data-fetch-fix-P2.md)

---

## 五、修复路线图

1. 阶段一（P0，约 0.5–1 天）：恢复模块导入 → pytest 可运行 → ruff 达标。达到"可合入前置条件"。
2. 阶段二（P1，约 2–3 天）：L2 落库红线 → 新鲜度 → L3 决策 → 定时任务 → 交易日历 → DataFetchError。
3. 阶段三（P2，约 2 天）：fetcher 重构 / 取舍 → 超时退避 → 批量参数 → CLI 细节 → 测试补齐 → 提交拆分与代码卫生。

每阶段结束前跑 `pytest` 全量 + `ruff check`，确保无新回归。

---

## 六、总体验收标准

1. `pytest` 全量通过，存量用例无回归；
2. `ruff check .` 0 error、`ruff format --check .` 通过（新代码）；
3. incremental / full / calibrate / status 四条 CLI 路径可运行，退出码符合设计；
4. L2 违规不落库且整段 failed；校准差异有 `data_calibration_log` 可追溯；
5. 数据源缺当日数据时返回 stale/empty 提示（message + 日志 + 审计），非静默；
6. 定时任务按 `schedule` 配置触发、当日去重、进程内互斥、错过补跑；
7. 提交按设计 14.1 拆分，遵循 conventional commits。

---

## 七、复检记录（2026-08-20）

对上一版方案逐项复检，结论：

1. 已修复：P0-01（JSON 导入）、P1-01 主体（L2 违规不落库）、P1-02（新鲜度判定）、P1-06（DataFetchError）、P2-04（CLI calibrate 可选）。
2. 部分修复（存在残留）：P1-03（校准日志不落库、`calibration.enabled` 未生效）、P1-04（weekday 偏移 1：周一被跳过、周六会执行）、P1-05（日历更新吞异常导致降级不触发、空日历死循环风险）、P2-02（backoff 已接，timeout 仍无效）。
3. 未修复：P0-02、P0-03、P2-01、P2-03、P2-05、P2-06。
4. 复检新增：P0-04（`get_config()` 无参调用，整条链路运行时不可用）；另有测试与实现不同步（normalize 列断言、异常类型、`calibrate` 返回元组）导致 13 个用例失败。
