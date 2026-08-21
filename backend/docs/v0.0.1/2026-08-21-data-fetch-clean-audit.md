# 后端数据获取与清洗功能审查报告

> **版本：** v0.0.1  
> **审查日期：** 2026-08-21  
> **审查范围：** `backend/quant/data/`、`backend/quant/storage/database.py`、`backend/quant/utils/calendar.py`  
> **审查依据：** `quant-backend` 技能规范（AGENTS.md 第 3/4/5 节红线）  
> **审查结论：** 发现 P0 级红线违反 5 项、P1 级问题 6 项、P2 级问题 4 项，须立即整改后方可进行回测验证

---

## 一、审查结论总览

| 优先级 | 问题数 | 核心风险 |
|--------|--------|----------|
| P0 — 必须立即修复 | 5 | 时间序列行被删除，直接破坏回测正确性 |
| P1 — 重要（影响可靠性） | 6 | 列名不一致、浮点容差过严、节假日硬编码 |
| P2 — 优化（代码质量） | 4 | 性能、测试覆盖、降级提示缺失 |

**最严重问题：** `DataProcessor.clean_data` 和 `DataCalibrator.validate` 在多处通过 `dropna()` / 布尔索引过滤方式**删除了时间序列行**，直接违反 AGENTS.md 第 4.6 节红线——"数据清洗禁止删除时间行（破坏序列连续性）"。量化回测要求全量日期索引连续无断裂，删行会导致信号对齐错误、指标计算偏差。

---

## 二、P0 级问题（破坏正确性，必须立即修复）

### P0-01：`DataProcessor.clean_data` 使用 `dropna()` 删除时间序列行

**文件：** `backend/quant/data/processor.py:154`  
**红线违反：** AGENTS.md 4.6 — "数据清洗禁止删除时间行"

```python
# processor.py:153-155 — 违规代码
df = df.dropna()
logger.info(f"删除缺失值: {initial_len} -> {len(df)}")
```

**问题分析：**  
`dropna()` 会删除含任意 NaN 的行。在 `process_stock_data` 流程中（`processor.py:240-252`），当前顺序为 `add_technical_indicators → clean → add_price_features → add_volume_features`。一旦前面有 NaN（如停牌日数据缺失），`dropna()` 删除后造成日期不连续，破坏量化时间序列完整性。

**整改方案：**  
1. `clean_data` 移除 `dropna()`，改为列级过滤/前向填充；
2. 将 `clean` 步骤移至 `add_technical_indicators` **之前**，确保清洗不影响后续指标计算；
3. 明确 `clean_data` 职责：**仅做列级非法值过滤（价格 ≤ 0 → NaN，成交量 < 0 → NaN），不删任何行**；
4. 增加测试用例：验证清洗前后 DataFrame **行数不变、index 不变**。

---

### P0-02：`DataProcessor.clean_data` 对非法价格/成交量直接删行

**文件：** `backend/quant/data/processor.py:159-170`  
**红线违反：** AGENTS.md 4.6 — "数据清洗禁止删除时间行"

```python
# processor.py:159-170 — 违规代码
if "close" in df.columns:
    invalid_close = (df["close"] <= 0) | df["close"].isna()
    if invalid_close.any():
        logger.warning(f"发现 {invalid_close.sum()} 条非法收盘价")
        df = df[~invalid_close]   # ← 删除时间序列行

if "volume" in df.columns:
    invalid_volume = (df["volume"] < 0) | df["volume"].isna()
    if invalid_volume.any():
        logger.warning(f"发现 {invalid_volume.sum()} 条非法成交量")
        df = df[~invalid_volume]  # ← 删除时间序列行
```

**问题分析：** 与 P0-01 同根因，将非法值处理方式从"删行"误写为"替换为 NaN"即可。

**整改方案：** 将非法值替换为 NaN，保留行位置：
```python
if "close" in df.columns:
    invalid_close = (df["close"] <= 0) | df["close"].isna()
    if invalid_close.any():
        logger.warning(f"发现 {invalid_close.sum()} 条非法收盘价，替换为 NaN")
        df.loc[invalid_close, "close"] = np.nan

if "volume" in df.columns:
    invalid_volume = (df["volume"] < 0) | df["volume"].isna()
    if invalid_volume.any():
        logger.warning(f"发现 {invalid_volume.sum()} 条非法成交量，替换为 NaN")
        df.loc[invalid_volume, "volume"] = np.nan
```

---

### P0-03：`DataCalibrator.validate` L2 校验失败后通过集合过滤删行

**文件：** `backend/quant/data/calibration.py:279-286`  
**红线违反：** AGENTS.md 4.6 — "数据清洗禁止删除时间行"

```python
# calibration.py:279-286 — 违规代码
failed_dates = {issue["trade_date"] for issue in issues if issue["decision"] == "failed"}
clean_dates = [d for d in dates if d not in failed_dates]
df_clean = df.loc[df.index[: len(clean_dates)]]  # ← 位置索引删行（危险）
date_set = set(clean_dates)
mask = pd.Series([d in date_set for d in dates], index=df.index)
df_clean = df[mask]
```

**问题分析：** L2 硬校验失败行（OHLC 违法、负值等）通过 `failed_dates` 集合在 DataFrame 中过滤剔除，违反不删行红线。`sync.py:344` 已正确通过 `has_l2_failed` 判断在库外拦截失败的整段数据，清洗器本身不应再删行。

**整改方案：**  
1. `validate` 方法不再操作 DataFrame，改为返回 `(valid_mask: pd.Series, issues: list)`；
2. 调用方（`sync.py:341`）在获取 `clean_df` 后通过 `valid_mask` 过滤出可通过校验的行，**不在清洗器内删行**；
3. 或者 `calibrate` 方法直接返回全量 `df` + issues 列表，由 `sync._fetch_and_save` 决定是否使用 `has_l2_failed` 拒绝整段。

---

### P0-04：`DataCalibrator._calibrate_overlap` 重复设置索引导致双重索引

**文件：** `backend/quant/data/calibration.py:341-342`  
**红线违反：** AGENTS.md 4.5 — "禁止裸 except 与 except: pass"

```python
# calibration.py:340-343 — 危险代码
if "trade_date" in df_local.columns:
    df_local = df_local.set_index("trade_date")  # 重复设索引
```

**问题分析：** `Database.get_stock_daily` 返回的 DataFrame index 已经是 `trade_date`（date 类型，见 `database.py:645`：`df.set_index("trade_date", inplace=True)`）。再次调用 `set_index("trade_date")` 会将现有 index 降为普通列，形成两层级联索引（MultiIndex），导致后续 `df_local.loc[d]` 查询位置错位或失败。

**整改方案：**
```python
if "trade_date" in df_local.columns and df_local.index.name != "trade_date":
    df_local = df_local.set_index("trade_date")
```

---

### P0-05：`DataCalibrator.validate` 非交易日校验误判停牌日为失败

**文件：** `backend/quant/data/calibration.py:171-194`  
**红线违反：** AGENTS.md 4.6 — "数据清洗禁止删除时间行"

```python
# calibration.py:175-179 — 误判代码
all_dates = set(dates)
for d in all_dates:
    if cal.trading_days and d not in set(cal.trading_days):
        non_trading_dates.append(d)  # 停牌日会被错误标记为 failed
```

**问题分析：** 股票停牌期间无交易数据属**合法状态**，日历中不存在该日期是正常的。L2 校验目标是拦截"数据源返回了错误的非交易日期行"（如数据错误插入了非交易日），而非"合法存在的停牌日期"。当前逻辑会将停牌日标记为 `failed`，配合 P0-03 的删行逻辑会导致本地合法数据被错误删除。

**整改方案：** 移除非交易日校验（或降级为 WARN 级日志）。真正的非交易日入侵应由数据源质量保证，校验器不应二次过滤停牌日期。

---

## 三、P1 级问题（影响可靠性，须尽快整改）

### P1-01：`add_volume_features` 依赖未计算的 `VOL_MA5`

**文件：** `backend/quant/data/processor.py:127`  
**问题：** `add_volume_features` 中 `df["vol_ratio"] = df["volume"] / df["VOL_MA5"]` 假设 `VOL_MA5` 已存在。如果用户单独调用 `add_volume_features`（不经过 `process_stock_data`），会产生全 NaN 列。

**整改方案：** 内部自检并按需计算：
```python
if "VOL_MA5" not in df.columns:
    df["VOL_MA5"] = df["volume"].rolling(window=5).mean()
```

---

### P1-02：`process_stock_data` 中 `clean` 在指标计算之后

**文件：** `backend/quant/data/processor.py:240-252`  
**问题：** 当前顺序为 `add_indicators → add_price_features → add_volume_features → clean`。若 `clean` 后续改为不删行（整改 P0-01/02），则指标列中因停牌/非法值产生的 NaN 不会被处理；若仍执行删行，则会误删已计算好的指标行。

**整改方案：** 调整顺序为 `clean → add_indicators → add_price_features → add_volume_features`，且 `clean` 仅做列级非法值过滤（不删行）。

---

### P1-03：`TushareAdapter.get_stock_history` 未实现列规范化

**文件：** `backend/quant/data/base_data_source.py:242-268`  
**问题：** Tushare 分支直接返回原始 tushare DataFrame（列名 `trade_date/open/close/high/low/vol/amount`），与 Akshare 规范化列名（`date/open/close/high/low/volume/amount/amplitude/change_pct/change_amount/turnover`）不一致，下游模块无法统一处理。

**整改方案：** TushareAdapter 返回前调用 `_normalize` 方法（或新增方法）将列名映射为规范列名。

---

### P1-04：OHLC 浮点精度容差 1e-9 过严

**文件：** `backend/quant/data/calibration.py:226-227`  
**问题：** `h >= max(o, c) - 1e-9` 容差仅 1e-9，AKShare 返回数据在涨跌停附近可能因浮点精度出现极微小超出被误判为 failed。

**整改方案：** 将容差放宽至 `1e-6`，或用 `np.isclose()` 相对容差判断。

---

### P1-05：`TradingCalendar._generate_default_calendar` 节假日硬编码

**文件：** `backend/quant/utils/calendar.py:83-98`  
**问题：** 春节、中秋节等农历节日用固定日期硬编码（如 `(6, 22): "端午节"`），与实际不符，会导致非交易日被错误当作交易日（反之亦然），进而影响增量区间计算和新鲜度判断。

**整改方案：** 默认日历直接使用 `akshare.tool_trade_date_hist_sina()` 获取真实交易日历；无网络时使用更保守的"全部工作日"逻辑（节假日由用户手动配置）。

---

### P1-06：dry_run 模式使用 `SKIPPED` 状态与真实跳过混淆

**文件：** `backend/quant/data/sync.py:264-275`  
**问题：** dry_run 返回 `FetchStatus.SKIPPED`，与"断点已覆盖目标无需拉取"的真实 skip 状态无法区分，审计日志语义混乱。

**整改方案：** 在 `FetchStatus` 枚举中新增 `DRY_RUN = "dry_run"` 值，区分业务含义。

---

## 四、P2 级问题（优化项）

### P2-01：`validate` 逐行 iterrows 性能差

**文件：** `backend/quant/data/calibration.py:197-276`  
**问题：** 对每一行调用 `iterrows()` 检查 OHLC 关系，数据量上万行时性能差。

**整改方案：** 用向量化布尔索引一次完成所有行检查：
```python
high_invalid = df["high"] < df[["open", "close"]].max(axis=1)
low_invalid = df["low"] > df[["open", "close"]].min(axis=1)
price_invalid = (df[["open", "close", "high", "low"]] <= 0).any(axis=1)
volume_invalid = df["volume"] < 0
```

---

### P2-02：`DataFetchError` 不进入重试逻辑

**文件：** `backend/quant/data/fetcher.py:123-130`  
**问题：** `except DataFetchError: raise` 立即上抛，但某些 DataFetchError（如"网络超时"）实际上可重试，被跳过重试机会。

**整改方案：** 区分可重试（超时、临时不可用）和不可重试（列缺失、数据为空）的 DataFetchError 子类；或统一让所有 DataFetchError 进入重试循环。

---

### P2-03：缺少 `processor.py` 和 `sync.py` 的单元测试

**文件：** `backend/quant/data/processor.py`、`backend/quant/data/sync.py`  
**问题：** `test_data_sync.py` 仅覆盖适配器和校准器，未覆盖 `DataProcessor` 边界行为（空数据、一字板、全 NaN）和 `DataSyncService._resolve_interval` 各场景（skip/breakpoint/overlap）。

**整改方案：** 补充测试用例：清洗前后行数/索引不变、一字板合法不删行、winsorize 截尾行为、区间计算 skip/breakpoint/overlap/dry_run 场景。

---

### P2-04：`Database.get_stock_daily` 在 simple_db 模式下静默返回空

**文件：** `backend/quant/storage/database.py:607-608`  
**问题：** `simple_db` 路径直接返回空 DataFrame，无日志警告，用户无法判断是数据不存在还是不兼容。

**整改方案：** 增加日志警告：
```python
if self.simple_db:
    logger.warning("SimpleDatabase 不支持 get_stock_daily，返回空 DataFrame")
    return pd.DataFrame()
```

---

## 五、问题汇总表

| 优先级 | 编号 | 文件 | 行号 | 问题描述 | 整改方案 | 状态 |
|--------|------|------|------|----------|----------|------|
| **P0** | P0-01 | `processor.py` | 154 | `clean_data` 用 `dropna()` 删时间序列行 | 改用列级 NaN 替换；调整 `process_stock_data` 顺序 | 待整改 |
| **P0** | P0-02 | `processor.py` | 159-170 | 非法价格/成交量直接 `df[~mask]` 删行 | 改为 `df.loc[mask, col] = np.nan` | 待整改 |
| **P0** | P0-03 | `calibration.py` | 279-286 | L2 失败行通过集合过滤删 DataFrame 行 | 清洗器不删行，通过 valid_mask 在调用方过滤 | 待整改 |
| **P0** | P0-04 | `calibration.py` | 341-342 | 重复设索引导致双重索引，破坏 loc 查询 | 加条件判断避免重复设索引 | 待整改 |
| **P0** | P0-06 | `calibration.py` | 171-194 | 非交易日校验误判停牌日为 failed | 移除或降级为 WARN | 待整改 |
| **P1** | P1-01 | `processor.py` | 127 | `add_volume_features` 依赖未计算的 `VOL_MA5` | 内部自检并按需计算 | 待整改 |
| **P1** | P1-02 | `processor.py` | 240-252 | `clean` 在指标计算之后（顺序错误） | 调整为先清洗后计算指标 | 待整改 |
| **P1** | P1-03 | `base_data_source.py` | 242-268 | TushareAdapter 未规范化列名 | 实现 `_normalize` 方法 | 待整改 |
| **P1** | P1-04 | `calibration.py` | 226 | OHLC 浮点容差 1e-9 过严 | 放宽至 1e-6 | 待整改 |
| **P1** | P1-05 | `calendar.py` | 83-98 | 节假日硬编码与实际不符 | 用 akshare 获取真实日历 | 待整改 |
| **P1** | P1-06 | `sync.py` | 264-275 | dry_run 用 SKIPPED 与真实 skip 混淆 | 新增 DRY_RUN 枚举值 | 待整改 |
| **P2** | P2-01 | `calibration.py` | 197 | 逐行 iterrows 性能差 | 向量化布尔索引替代 | 待优化 |
| **P2** | P2-02 | `fetcher.py` | 123-130 | DataFetchError 不进入重试逻辑 | 区分可重试/不可重试错误 | 待优化 |
| **P2** | P2-03 | `processor.py`/`sync.py` | — | 缺少单元测试 | 补充边界场景测试 | 待优化 |
| **P2** | P2-04 | `database.py` | 607 | simple_db 下 get_stock_daily 静默返回空 | 增加日志警告 | 待优化 |

---

## 六、整改顺序建议

1. **第一轮（P0 修复）：** 整改 P0-01 ~ P0-06，确保时间序列不删行、数据不因校验误判被删除。完成后运行 `pytest` 全量回归。
2. **第二轮（P1 修复）：** 整改 P1-01 ~ P1-06，确保数据规范化、浮点容差合理、日历准确。
3. **第三轮（P2 优化）：** 性能优化、测试补全、dry_run 枚举分离。

> **警告：** 在 P0 修复完成之前，任何基于当前数据链路的回测结果均不可信——时间序列的断裂会直接导致信号漂移、指标失真、夏普/回撤等核心指标计算错误。
