# P0 级问题与解决方案（阻断级）

> 版本 v0.0.1 ｜ 2026-08-20
> 说明：P0 为阻断级——不修复则框架不可用或存在回归，应最先处理（建议 0.5–1 天完成）。

---

## P0-01 storage/database.py 丢失 JSON 导入，存储模块整体无法导入

> 复检状态（2026-08-20）：**已修复**。SQLAlchemy 导入已恢复 `JSON`，`quant.storage` 可导入，pytest 可正常收集。

### 问题

- `backend/quant/storage/database.py` 修改 SQLAlchemy 导入时删掉了 `JSON`，但存量模型 `SignalRecord.parameters` 与 `BacktestResult.parameters/metrics` 仍使用 `Column(JSON)`（database.py 约 202/234/235 行）。
- 实测：`pytest` 收集阶段即抛 `NameError: name 'JSON' is not defined`，`quant.storage` 包无法导入。
- HEAD 版本中该导入存在（`from sqlalchemy import ..., JSON`），本次改动属引入回归，违反"存量用例不得回归"。

### 影响

所有依赖 `quant.storage` 的模块（data/sync、backtest、risk、CLI、scheduler）全部不可用；全量 pytest 无法运行。这是阻断合入的第一问题。

### 解决方案

1. 恢复 SQLAlchemy 导入：

```python
from sqlalchemy import (
    create_engine,
    Column,
    Float,
    Index,
    Integer,
    String,
    Text,
    DateTime,
    Date,
    JSON,
)
```

2. 修复后立即验证：

```powershell
conda activate quant_project
cd backend
python -c "import quant.storage; print('ok')"
python -m pytest quant/tests/test_storage.py -q
```

3. 长期：旧模型中的 `Column(JSON)` 显式使用 `sqlalchemy.JSON`，避免因导入调整再次遗漏（见 P2-06）。

### 验收标准

`quant.storage` 及全项目模块可导入；`pytest` 可正常收集。

---

## P0-02 pytest 无法运行，新增测试用例覆盖不足且可能污染真实数据目录

### 问题

- P0-01 未修复前，pytest 全量在收集阶段崩溃。
- `tests/test_data_sync.py` 中 `TestDatabaseUpsert` 直接 `Database()`，默认落到配置数据目录（`d:/desk/code/personal/data`，当前不存在）；SQLAlchemy 建库失败后会静默降级到 JSON 简化存储，既无法验证真实 SQLite upsert，又可能污染用户数据目录。

### 影响

"测试全绿"底线失效；upsert 幂等、断点查询等核心能力未被真实验证，静默降级会掩盖 SQLAlchemy 路径缺陷。

### 解决方案

1. 修复 P0-01 后先恢复全量收集与存量用例（`python -m pytest -q`）。
2. 数据库相关测试注入临时 SQLite：

```python
def test_upsert_idempotent(tmp_path):
    db = Database(db_url=f"sqlite:///{tmp_path / 'test.db'}")
    ...
```

3. 新增冒烟用例（详细清单见 P2-05）：upsert 幂等（重复写入行数不变、updated_at 更新）、断点查询、fetch_log 写入。

> 复检状态（2026-08-20）：**部分修复**。pytest 现可收集，但 `test_data_sync.py` 仍有 13 个失败，根因如下：
>
> 1. P0-04：`get_config()` 无参调用导致 `Database()` / `TradingCalendar()` / `DataSyncService()` 全部无法构造（6 个校准用例 + 4 个数据库用例因此失败）；
> 2. 测试未随实现更新：`normalize` 用例仍断言 `date` 是列（实现已改为 index）、缺失列用例仍期望 `RuntimeError`（实现已改抛 `DataFetchError`）、`test_calibrate_full_flow` 仍期望返回单个 report（实现已改为返回 `(df, report)` 元组）；
> 3. `TestDatabaseUpsert` 仍直接 `Database()`，未注入临时 SQLite。
>
> 另注：`test_paths.py` 5 个用例报 `PermissionError`，为沙箱 Temp 目录（`C:\Users\27895\AppData\Local\Temp\pytest-of-27895`）权限所致，属环境问题而非代码回归；正常用户环境应可运行。

### 验收标准

`pytest` 全量收集通过；数据库测试使用临时库且不触碰真实数据目录；`pytest quant/tests/test_data_sync.py` 全绿。

---

## P0-03 新代码 Ruff 不达标

### 问题

实测（仅新增/修改文件）：

- `ruff check` 159 处。其中真实问题 34 处：F401 未用导入 ×12、UP045 非 PEP 604 注解 ×9、B905 zip 缺 strict ×3、E402 导入位置 ×3、E741 变量名 ×2、RUF059 未用解构 ×2、F821 未定义名 ×1（sync.py:453 `DataCalibrationReport`）、F841 未用变量 ×1（sync.py:179 `start_time`）、I001 导入排序 ×1。
- 其余 125 处为 RUF001/2/3 中文标点（`，：（）`）误报类，与仓库既有中文 docstring 风格冲突，建议项目级统一处理（见 P2-06）。
- `ruff format --check`：新增/修改 10 个文件全部需要重排。

### 影响

违反 AGENTS.md 与 `quant-backend` 技能"新代码 ruff check 0 error + format --check 通过"的强制要求。

### 解决方案

1. 本轮清零非标点类问题：
   - 删除 F401 未用导入（含测试文件中的 `timedelta / MagicMock / patch / np / CalibrationIssueDict`）；
   - `sync.py` 导入 `DataCalibrationReport` 或改用字符串前向引用消除 F821；
   - `Optional[X]` → `X | None`（UP045），`Dict / List` → `dict / list`（UP006）；
   - `zip(..., strict=True)`（B905）；`run_full` 的 `start_time` 实际使用或删除（F841）；
   - E741 变量 `l` 改名；RUF059 解构用 `_` 占位；
   - E402：删除 `scripts/data_download.py` 的 `sys.path.insert`（backend 已为包结构，安装后无需补丁）。
2. 执行 `ruff format .`，再 `ruff format --check .` 验证。
3. 中文标点 RUF001/2/3 项目级决策（二选一，由技术负责人拍板）：
   - 方案 A（推荐）：`pyproject.toml` 的 `[tool.ruff.lint]` 增加 `extend-ignore = ["RUF001", "RUF002", "RUF003"]`，与仓库中文文档风格一致；
   - 方案 B：保留规则，成立代码卫生任务将全库中文标点替换为英文标点。

### 验收标准

`ruff check .` 0 error（或仅剩已登记的卫生任务项）；`ruff format --check .` 通过。

> 复检状态（2026-08-20）：**未修复**。对新增/修改的 10 个相关文件复检：`ruff check` 409 处（含存量文件历史问题；新增代码中仍有 F401×24、UP045×31、UP006×19、UP035×7、B905×3、E402×3、F821×2、F841×1 等真实问题），`ruff format --check` 9/10 未通过。建议先执行 `ruff check --fix` + `ruff format`，再人工清理非自动修复项。

---

## P0 总体验收

1. `quant.storage` 及全项目模块可导入；
2. `pytest` 全量可收集、运行，存量用例无回归；
3. 新代码 `ruff check` / `ruff format --check` 达标；
4. 数据库测试不触碰真实数据目录。

---

## P0-04 get_config() 签名不匹配，DataSyncService() 无法构造（复检新增）

### 问题

- `quant/config.py` 的 `get_config(key: str, default=None)` 要求必传 `key`；
- 但以下位置均无参调用 `get_config()`，运行时抛 `TypeError: get_config() missing 1 required positional argument: 'key'`：
  - `quant/utils/paths.py:44`（存量代码，HEAD 即存在；`Database()`、`TradingCalendar()` 因此全部不可用）；
  - `quant/data/sync.py`（`DataSyncConfig.from_config`，新增代码）；
  - `quant/infrastructure/scheduler.py`（`DataSyncJob.register`，新增代码）；
  - `quant/scripts/data_download.py`（`cmd_status`，新增代码）。
- 实测：`from quant.data.sync import DataSyncService; DataSyncService()` 抛 TypeError，整条同步链路（CLI / 调度器 / 服务）运行时不可用。

### 影响

即使修复 P0-01，新链路仍无法启动；这是复检发现的**新阻断项**，须与 P0-01 一并修复。

### 解决方案

1. 统一配置访问语义：无参"拿配置管理器"用 `get_config_manager()`，有参"取配置值"用 `get_config(key, default)`；
2. `quant/utils/paths.py:get_data_paths` 改为：

```python
from quant.config import get_config

data_dir = _resolve(get_config("data.data_dir", "data"))
tmp = _join_sub(data_dir, get_config("data.tmp_dir", "tmp"))
...
```

3. `sync.py` / `scheduler.py` / `data_download.py` 中所有无参 `get_config()` 改为 `get_config_manager()` 或带默认值的 `get_config(key, default)`；
4. 补充冒烟测试：`DataSyncService()` 可构造，`Database()` 可连接临时 SQLite。

### 验收标准

`DataSyncService()` / `Database()` 可正常构造；CLI `--dry-run` 可执行；`test_paths.py` 与数据库用例不再抛 TypeError。
