# A 股数据获取：字段与表设计（默认数据源 AKShare）

> 版本：v0.0.1 ｜ 2026-08-19 ｜ 适用：`backend/quant/data` + `backend/quant/storage` 改造
> 目标：以默认数据源 AKShare 真实跑通 A 股日线数据「获取 → 规范化 → 校验 → 落库 → 读回」全链路
> 依据：本机 `quant_project` 环境（Python 3.12.13 / akshare 1.18.92 / pandas 3.0.5）实测返回 + AKShare 1.18.92 源码核对

---

## 一、背景与结论摘要

1. 默认数据源为 AKShare，日线接口 `ak.stock_zh_a_hist`（东方财富），已在 `quant_project` 环境实测跑通（见第七节验证记录）。
2. AKShare 1.18.92 实际返回 **12 列**：日期、股票代码、开盘、收盘、最高、最低、成交量、成交额、振幅、涨跌幅、涨跌额、换手率；当前 `AkshareAdapter.get_stock_history` 用 11 个列名做整体替换，**必然报错且映射错位**，必须按映射字典重构（见第六节整改点）。
3. 字段设计核心决策：交易日（`trade_date`）+ 标的（`symbol`）+ **复权类型（`adjust_type`）** 三要素作为日线唯一键；成交量统一为「手」、成交额统一为「元」、涨跌幅/振幅/换手率统一为「小数」（0.01 = 1%）。
4. 表设计共 5 张：`stock_daily`（日线行情）、`stock_basic`（股票基础信息）、`trade_calendar`（交易日历）、`data_fetch_log`（拉取审计/断点续拉）、`data_source`（数据源登记）。

---

## 二、真实接口核对（akshare 1.18.92 实测）

### 2.1 主接口：东方财富日线 `stock_zh_a_hist`

```python
ak.stock_zh_a_hist(symbol="600519", period="daily", start_date="20231201",
                   end_date="20231231", adjust="qfq")  # adjust: "" | "qfq" | "hfq"
```

返回列（顺序固定，全部实测）：

| # | 原始列 | 类型（实测） | 单位 | 样例（600519，2023-12-01） |
|---|--------|--------------|------|------------------------------|
| 1 | 日期 | date | - | 2023-12-01 |
| 2 | 股票代码 | str | 6 位数字 | 600519 |
| 3 | 开盘 | float64 | 元 | 1789.31 |
| 4 | 收盘 | float64 | 元 | 1760.28 |
| 5 | 最高 | float64 | 元 | 1789.70 |
| 6 | 最低 | float64 | 元 | 1748.00 |
| 7 | 成交量 | float64 | 手（1 手 = 100 股） | 33051 |
| 8 | 成交额 | float64 | 元 | 5830850000 |
| 9 | 振幅 | float64 | 百分比数值（2.33 表示 2.33%） | 2.33 |
| 10 | 涨跌幅 | float64 | 百分比数值（-1.74 表示 -1.74%） | -1.74 |
| 11 | 涨跌额 | float64 | 元 | -31.22 |
| 12 | 换手率 | float64 | 百分比数值（0.26 表示 0.26%） | 0.26 |

要点：

- `adjust=""` 不复权、`adjust="qfq"` 前复权、`adjust="hfq"` 后复权；**同一只股票不同复权方式价格不同**，因此复权类型必须作为数据维度持久化。
- `market_code` 逻辑：`6` 开头走沪市（secid=1.xxx），其余走深市（secid=0.xxx）；北交所代码需单独验证后纳入。
- 涨跌停日等极端行情下价格合法但振幅/涨跌幅可能为 0，校验时不得误删。

### 2.2 备用接口：新浪日线 `stock_zh_a_daily`

```python
ak.stock_zh_a_daily(symbol="sh600519", start_date="20231201", end_date="20231215", adjust="")
```

返回 9 列：`date / open / high / low / close / volume / amount / outstanding_share / turnover`。
与主接口口径差异（规范化时必须统一）：

- `volume` 单位是**股**（3305131），主接口是**手**（33051）；
- `turnover` 是**小数**（0.002631），主接口是**百分比数值**（0.26）；
- 多出 `outstanding_share`（流通股本，股）；
- symbol 需带交易所前缀（`sh600519` / `sz000001`）。

### 2.3 辅助接口

| 接口 | 返回 | 用途 |
|------|------|------|
| `ak.tool_trade_date_hist_sina()` | 1 列 `trade_date`，实测 8797 行（1990-12-19 起） | 交易日历表 |
| `ak.stock_info_a_code_name()` | 2 列 `code` / `name`，实测 5547 只 | 股票基础信息表（交易所由代码前缀推导） |

### 2.4 数据源一览（akshare / tushare）

| 数据源 | 适配器类 | 状态 | 默认 | token | 主要接口 | 关键口径 | 备注 |
|--------|----------|------|------|-------|----------|----------|------|
| akshare | `AkshareAdapter` | 启用 | 是 | 无需 | `stock_zh_a_hist`（东财日线）、`stock_zh_a_daily`（新浪备用）、`tool_trade_date_hist_sina`（日历）、`stock_info_a_code_name`（列表） | 东财：成交量=手、成交额=元、涨跌幅/振幅/换手率=百分比数值；新浪：成交量=股、换手率=小数 | 免费开源、接口丰富；偶发反爬断连，适配器须带重试与超时（见第六节整改点 5） |
| tushare | `TushareAdapter` | 未启用（规划） | 否 | 需要（config.yaml `data.sources.tushare.token`） | `pro.daily`（日线，未复权）、`pro.adj_factor`（复权因子） | 成交量=手、成交额=**千元**（入库须 ×1000 换算为元）、涨跌幅=百分比数值；复权需自行用复权因子计算 | 积分制、接口规范稳定；未启用前不承诺数据可用性，token 仅存 config，不落库 |

说明：

- 数据源注册信息（source_key / 适配器 / 启用状态 / 默认标记）由 `data_source` 表持久化（见 4.5 节）；启用与默认标记应与 `config.yaml` 的 `data.sources` 段保持一致。
- `stock_daily.source` 等表的 `source` 字段记录具体接口标记（如 `akshare-em`、`akshare-sina`、`tushare-pro`），其归属数据源见 `data_source.source_key`。

---

## 三、字段设计（内部规范列）

### 3.1 日线行情规范列（`stock_daily` 行）

| 规范列 | 类型 | 单位/取值 | 来源（东财原始列） | 必填 | 说明 |
|--------|------|-----------|---------------------|------|------|
| `symbol` | str | `600519.SH` | 股票代码 + 交易所后缀 | 是 | 内部统一带后缀，与 config `stock_pool` 一致 |
| `trade_date` | date | YYYY-MM-DD | 日期 | 是 | 交易日 |
| `adjust_type` | str | `""` / `qfq` / `hfq` | 请求参数 | 是 | 复权维度，参与唯一键 |
| `open` | float | 元 | 开盘 | 是 | |
| `high` | float | 元 | 最高 | 是 | |
| `low` | float | 元 | 最低 | 是 | |
| `close` | float | 元 | 收盘 | 是 | 回测信号基准价 |
| `volume` | float | 手 | 成交量 | 是 | 规范化后仍为手（1 手 = 100 股）；执行层换算股数 |
| `amount` | float | 元 | 成交额 | 是 | 可用于流动性/成本估算 |
| `amplitude` | float | 小数 | 振幅 ÷ 100 | 否 | 0.0233 表示 2.33% |
| `change_pct` | float | 小数 | 涨跌幅 ÷ 100 | 否 | 0.0174 表示 +1.74% |
| `change_amount` | float | 元 | 涨跌额 | 否 | |
| `turnover` | float | 小数 | 换手率 ÷ 100 | 否 | 0.0026 表示 0.26% |
| `source` | str | `akshare-em` / `akshare-sina` / `tushare-pro` | 适配器标记 | 是 | 数据溯源；归属数据源见 `data_source.source_key` |
| `created_at` / `updated_at` | datetime | - | 落库时间 | 是 | 审计 |

口径说明：

- 涨跌幅等统一存**小数**，与 `close.pct_change()` 收益率口径一致，避免各模块换算各算一套（呼应 AGENTS.md 4.5 指标口径统一红线）。
- `symbol` 后缀推导：`6` → `.SH`；`0/3` → `.SZ`；`4/8/920` → `.BJ`。适配器请求时去掉后缀。
- 停牌日没有 K 线行，**禁止补造数据行**；序列对齐交由交易日历表完成。

### 3.2 股票基础信息规范列（`stock_basic` 行）

| 规范列 | 类型 | 说明 |
|--------|------|------|
| `symbol` | str | 带后缀，主键 |
| `name` | str | 股票名称 |
| `exchange` | str | `SH` / `SZ` / `BJ`，由代码前缀推导 |
| `source` | str | 数据来源 |
| `updated_at` | datetime | 更新时间 |

上市日期、行业、总股本等扩展字段留待后续接口补充，不阻塞当前主表。

### 3.3 交易日历规范列（`trade_calendar` 行）

| 规范列 | 类型 | 说明 |
|--------|------|------|
| `trade_date` | date | 主键，A 股交易日 |
| `source` | str | 数据来源（默认 sina） |

### 3.4 拉取审计规范列（`data_fetch_log` 行）

| 规范列 | 类型 | 说明 |
|--------|------|------|
| `id` | int | 主键自增 |
| `symbol` / `adjust_type` | str | 拉取对象 |
| `start_date` / `end_date` | date | 请求区间 |
| `status` | str | `success` / `failed` / `partial` |
| `row_count` | int | 成功行数 |
| `error` | str | 失败原因（截断） |
| `duration_ms` | int | 耗时 |
| `fetched_at` | datetime | 拉取完成时间 |

用途：增量断点续拉（`max(fetched_at)` / `max(end_date)` 续拉）、失败清单追溯（呼应「数据获取失败必须抛 `DataFetchError` 或返回失败清单」红线）。

---

## 四、表设计

存储载体：SQLite（沿用 `quant/storage/database.py` 的 SQLAlchemy 引擎，默认 `processed/quant.db`），SQLite 无需分库分表，满足个人周/日频框架量级。

### 4.1 `stock_daily`（日线行情表）

```sql
CREATE TABLE stock_daily (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol       TEXT    NOT NULL,             -- 600519.SH
    trade_date   DATE    NOT NULL,
    adjust_type  TEXT    NOT NULL DEFAULT 'qfq', -- '' / qfq / hfq
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    volume       REAL,                          -- 手
    amount       REAL,                          -- 元
    amplitude    REAL,                          -- 小数
    change_pct   REAL,                          -- 小数
    change_amount REAL,
    turnover     REAL,                          -- 小数
    source       TEXT    NOT NULL,
    created_at   DATETIME NOT NULL,
    updated_at   DATETIME NOT NULL,
    UNIQUE (symbol, trade_date, adjust_type)    -- 幂等 upsert 依据
);
CREATE INDEX idx_stock_daily_date ON stock_daily (trade_date, symbol);
CREATE INDEX idx_stock_daily_symbol ON stock_daily (symbol, trade_date);
```

### 4.2 `stock_basic`（股票基础信息表）

```sql
CREATE TABLE stock_basic (
    symbol     TEXT PRIMARY KEY,                -- 600519.SH
    name       TEXT NOT NULL,
    exchange   TEXT NOT NULL,                   -- SH / SZ / BJ
    source     TEXT NOT NULL,
    updated_at DATETIME NOT NULL
);
```

### 4.3 `trade_calendar`（交易日历表）

```sql
CREATE TABLE trade_calendar (
    trade_date DATE PRIMARY KEY,
    source     TEXT NOT NULL
);
```

### 4.4 `data_fetch_log`（拉取审计表）

```sql
CREATE TABLE data_fetch_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    adjust_type TEXT NOT NULL,
    start_date  DATE,
    end_date    DATE,
    status      TEXT NOT NULL,                  -- success / failed / partial
    row_count   INTEGER DEFAULT 0,
    error       TEXT,
    duration_ms INTEGER,
    fetched_at  DATETIME NOT NULL
);
CREATE INDEX idx_fetch_log_symbol ON data_fetch_log (symbol, fetched_at);
```

### 4.5 `data_source`（数据源登记表）

描述数据来源及其适配器、启用状态；**token 等密钥不落库**（AGENTS.md 密钥不入库红线），tushare token 仅存于 config.yaml。

```sql
CREATE TABLE data_source (
    source_key  TEXT PRIMARY KEY,           -- akshare / tushare
    name        TEXT NOT NULL,              -- 数据源名称
    adapter     TEXT NOT NULL,              -- 适配器类全限定名
    enabled     INTEGER NOT NULL DEFAULT 1, -- 是否启用（与 config data.sources.*.enabled 对齐）
    is_default  INTEGER NOT NULL DEFAULT 0, -- 是否默认数据源
    description TEXT,                       -- 适用场景/口径说明
    updated_at  DATETIME NOT NULL
);
```

初始化数据：

| source_key | name | adapter | enabled | is_default | description |
|------------|------|---------|---------|------------|-------------|
| akshare | AKShare | `quant.data.base_data_source.AkshareAdapter` | 1 | 1 | 免费开源默认数据源；日线走东方财富、备用新浪；无需 token |
| tushare | Tushare | `quant.data.base_data_source.TushareAdapter` | 0 | 0 | 需 token（config 配置），积分制；成交额单位千元、复权需复权因子接口 |

### 4.6 与现有模型的兼容

- 现有 `StockData`（`storage/database.py`）只有 symbol/trade_date/OHLCV，**无复权维度与派生字段**；本设计为演进目标，实施时建议新增 `StockDaily` 模型并保留旧模型不破坏存量（或在确认无依赖后迁移，迁移决策由技术负责人定）。
- `trade_records` / `signal_records` / `backtest_results` 与行情表无结构冲突，不改。

---

## 五、数据载体与枚举

遵循「数据载体优先 dataclass、枚举用 enum、禁止公共接口返回裸 dict」：

```python
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class AdjustType(str, Enum):
    NONE = ""        # 不复权
    QFQ = "qfq"      # 前复权（默认）
    HFQ = "hfq"      # 后复权


class Exchange(str, Enum):
    SH = "SH"
    SZ = "SZ"
    BJ = "BJ"


@dataclass
class DailyBar:
    symbol: str
    trade_date: date
    adjust_type: AdjustType
    open: float
    high: float
    low: float
    close: float
    volume: float            # 手
    amount: float            # 元
    amplitude: float | None = None   # 小数
    change_pct: float | None = None  # 小数
    change_amount: float | None = None
    turnover: float | None = None    # 小数
    source: str = "akshare-em"
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

接口层仍返回 DataFrame（列名 = 规范列、`trade_date` 为 index），供策略/回测向量化使用；落库时逐行转为 `DailyBar`。

---

## 六、当前代码差异与整改点

| # | 现状 | 问题 | 整改要求 |
|---|------|------|----------|
| 1 | `AkshareAdapter.get_stock_history` 对 12 列数据整体赋 11 个列名 | 报 `Length mismatch`，且即使不报错也会把「股票代码」错位成 open | 按「原始列 → 规范列」映射字典显式取列并重命名，见第三节映射表 |
| 2 | 涨跌幅/振幅/换手率按百分比数值原样保存 | 与收益率/费率（小数）口径不一致 | 规范化时 ÷100 转小数 |
| 3 | 无复权维度 | 前复权/后复权/不复权数据互相覆盖 | `adjust_type` 入唯一键 |
| 4 | `save_stock_data` 逐行 `bulk_save_objects`，重复写入报唯一约束冲突 | 无法幂等增量更新 | 改为 `INSERT ... ON CONFLICT DO UPDATE`（SQLite upsert） |
| 5 | 无拉取审计 | 增量断点与失败追溯缺失 | 每次拉取写 `data_fetch_log` |
| 6 | symbol 直接去掉后缀传接口 | 北交所等边界未验证 | 代码前缀推导交易所，主表统一带后缀 |
| 7 | `SimpleDatabase` 路径下仍用 JSON 文件 | 与 SQLite 双轨并存 | 统一到 SQLite；JSON 路径仅作旧兼容，不再新增写入 |

---

## 七、验证记录（2026-08-19 实测）

环境：`conda activate quant_project`（Python 3.12.13），`pip install -e ".[dev]"` 后 akshare 1.18.92。

1. **日线拉取**：`ak.stock_zh_a_hist(symbol="600519", start_date="20231201", end_date="20231231", adjust="")` 成功返回 11 行 × 12 列，样例：

   | 日期 | 股票代码 | 开盘 | 收盘 | 最高 | 最低 | 成交量 | 成交额 | 振幅 | 涨跌幅 | 涨跌额 | 换手率 |
   |------|----------|------|------|------|------|--------|--------|------|--------|--------|--------|
   | 2023-12-01 | 600519 | 1789.31 | 1760.28 | 1789.70 | 1748.00 | 33051 | 5.83e9 | 2.33 | -1.74 | -31.22 | 0.26 |

2. **备用接口**：`ak.stock_zh_a_daily(symbol="sh600519")` 返回 11 行 × 9 列，volume=3305131（股）、turnover=0.002631（小数）——与主接口单位差异已确认。
3. **交易日历**：`ak.tool_trade_date_hist_sina()` 返回 8797 行，首日 1990-12-19。
4. **股票列表**：`ak.stock_info_a_code_name()` 返回 5547 只（code/name）。
5. 网络备注：东财接口经本机代理（127.0.0.1:1080）偶发断连，重试后成功；新浪接口稳定。适配器需保留重试与超时配置。

---

## 八、数据管道流程（目标态）

```text
fetch(akshare, symbol, 区间, adjust)
  -> normalize(原始列 -> 规范列, 单位统一, symbol 加后缀)
  -> validate(OHLC 合法性、重复日期、空数据抛 DataFetchError)
  -> upsert(SQLite stock_daily, ON CONFLICT 更新)
  -> audit(写 data_fetch_log)
  -> read back(按 symbol+区间+adjust_type 查询，返回规范列 DataFrame)
```

增量策略：按 `data_fetch_log` 中该 symbol 最近成功 `end_date` 的下一个交易日续拉；单次失败不阻塞批次，失败清单返回并记 `status=failed`。

---

## 九、配置变更清单（三处同步）

`config.yaml` 新增：

```yaml
data:
  adjust: "qfq"            # 默认复权类型："" / qfq / hfq
  storage:
    format: "sqlite"       # sqlite（当前）| parquet（预留）
  fetch:
    retry: 3               # 失败重试次数
    timeout: 20            # 单请求超时（秒）
    incremental: true      # 是否增量续拉
```

同步点：

1. `backend/quant/config.yaml`；
2. `ConfigManager._init_default_config` 的 data 段默认值；
3. `ConfigManager._validate_required_keys` 必填键（建议把 `data.adjust`、`data.storage.format`、`data.fetch.retry` 纳入）。

禁止在代码中硬编码复权类型、重试次数、超时（呼应 AGENTS.md 4.4 配置驱动）。

---

## 十、验收标准

1. 在 `quant_project` 环境内，`DataFetcher.get_stock_history("600519.SH", ..., adjust="qfq")` 真实拉取成功且返回规范列（12 字段，无列数错位）。
2. `stock_daily` 唯一键 `(symbol, trade_date, adjust_type)` 生效；同一区间重复写入不产生重复行（幂等）。
3. 复权维度隔离：同股票 qfq 与不复权数据并存互不覆盖。
4. 数据校验：OHLC 关系（`high >= max(open, close)`、`low <= min(open, close)`）、volume/amount 非负；空数据抛 `DataFetchError`；停牌缺行不补造。
5. 失败路径：模拟断网/接口报错时返回失败清单并写 `data_fetch_log(status=failed)`。
6. 配套测试：适配器列映射、单位换算、upsert 幂等、增量续拉、交易日历对齐，全部纳入 pytest 且存量用例无回归。

---

## 十一、后续实施建议（不在本文档范围）

1. 重构 `base_data_source.py` 的 `AkshareAdapter`（映射字典 + 单位换算 + 重试/超时接配置），补 `tests/test_data_akshare.py`。
2. `storage/database.py` 新增 `StockDaily` 模型与 upsert 方法，补双路径测试。
3. 增量拉取脚本（`quant/scripts/`）与交易日历初始化任务。
4. 北交所代码与复权因子校验，通过后再扩充 `stock_pool`。
