"""
数据校准模块

L2 质量硬校验（OHLC 合法性 + 日期去重 + 非交易日校验）。
L3 修正校准（重叠窗口对比 + 漂移识别 + 决策矩阵）。
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import TypedDict

import numpy as np
import pandas as pd

from quant.data.models import (
    CalibrationDecision,
    CalibrationIssueDict,
    DataCalibrationReport,
)
from quant.utils.logger import logger


class CalibrationIssue(TypedDict, total=False):
    """校准差异（内存中流转）"""

    symbol: str
    trade_date: date
    adjust_type: str
    field: str
    old_value: float | None
    new_value: float | None
    diff_ratio: float | None
    decision: str
    message: str | None
    checked_at: datetime


@dataclass
class CalibrationConfig:
    """校准配置"""

    enabled: bool = True
    price_tolerance: float = 0.001
    volume_tolerance: float = 0.01
    auto_correct_drift: bool = True
    alert_on_discrepancy: bool = True


class DataCalibrator:
    """
    数据校准器

    L2 硬校验：OHLC 关系、价格 > 0、volume/amount 非负、日期唯一。
    L3 修正校准：重叠窗口与本地对比、复权漂移识别、决策矩阵。
    """

    def __init__(self, config: CalibrationConfig | None = None):
        self.config = config or CalibrationConfig()

    def calibrate(
        self,
        df: pd.DataFrame,
        symbol: str,
        adjust_type: str,
    ) -> tuple[pd.DataFrame, DataCalibrationReport]:
        """
        完整校准流程（L2 + L3）

        Args:
            df: 从 AKShare 拉取的 DataFrame（规范列，index=date）
            symbol: 标的代码（带后缀）
            adjust_type: 复权类型

        Returns:
            (clean_df, report)
            - clean_df: L2 校验通过的 DataFrame（可落库）
            - report: DataCalibrationReport（含违规数、差异数、决策）
        """
        from quant.storage.database import Database  # noqa: F401

        # L2 硬校验
        valid_mask, l2_issues = self.validate(df, symbol)
        l2_failed_count = len(l2_issues)
        total = len(df)
        passed = valid_mask.sum()

        df_valid = df[valid_mask]

        if df_valid.empty:
            report = DataCalibrationReport(
                symbol=symbol,
                adjust_type=adjust_type,
                total_rows=total,
                passed=passed,
                l2_failed_count=l2_failed_count,
                issues=[CalibrationIssueDict(**i) for i in l2_issues],
                suggestion="所有行 L2 校验失败，请检查数据源",
            )
            return df_valid, report

        # L3 修正校准（重叠窗口与本地对比）
        issues = list(l2_issues)
        issues.extend(self._calibrate_overlap(df_valid, symbol, adjust_type))

        # 统计
        auto_corrected = sum(
            1 for i in issues if i["decision"] == CalibrationDecision.AUTO_CORRECT_DRIFT.value
        )
        discrepancies = sum(1 for i in issues if i["decision"] == CalibrationDecision.DISCREPANCY.value)

        report = DataCalibrationReport(
            symbol=symbol,
            adjust_type=adjust_type,
            total_rows=total,
            passed=passed,
            auto_corrected=auto_corrected,
            discrepancies=discrepancies,
            l2_failed_count=l2_failed_count,
            issues=[CalibrationIssueDict(**i) for i in issues],
            suggestion=self._make_suggestion(issues),
        )
        return df_valid, report

    def validate(
        self,
        df: pd.DataFrame,
        symbol: str,
    ) -> tuple[pd.Series, list[CalibrationIssue]]:
        """
        L2 硬校验（不删行）

        Args:
            df: 待校验 DataFrame
            symbol: 标的代码

        Returns:
            (valid_mask, issues)
            - valid_mask: 布尔 Series，True 表示该行通过校验
            - issues: 记录违规行（不落库）
        """
        issues: list[CalibrationIssue] = []
        df = df.copy()
        now = datetime.now()

        # 获取所有行索引（trade_date）
        dates = []
        for idx in df.index:
            d = idx.date() if hasattr(idx, "date") else idx
            dates.append(d)

        # 日期去重校验
        seen: set = set()
        dup_dates: list = []
        for d in dates:
            if d in seen:
                dup_dates.append(d)
            seen.add(d)
        for d in dup_dates:
            issues.append(
                CalibrationIssue(
                    symbol=symbol,
                    trade_date=d,
                    adjust_type="",
                    field="trade_date",
                    old_value=None,
                    new_value=None,
                    diff_ratio=None,
                    decision="failed",
                    message=f"重复日期: {d}",
                    checked_at=now,
                )
            )

        # 非交易日校验降级为 WARN（停牌日无行属正常，不误判为 failed）
        from quant.utils.calendar import get_calendar

        cal = get_calendar()
        non_trading_dates = []
        all_dates = set(dates)
        for d in all_dates:
            if cal.trading_days and d not in set(cal.trading_days):
                non_trading_dates.append(d)
        if non_trading_dates:
            logger.warning(f"发现 {len(non_trading_dates)} 个非交易日日期，可能为停牌日：{non_trading_dates[:5]}")

        # OHLC 关系校验（向量化 + 逐行记录违规）
        # 向量化：一次计算所有违规行
        price_cols_data = df[["open", "close", "high", "low"]].astype(float)
        o = price_cols_data["open"]
        c = price_cols_data["close"]
        h = price_cols_data["high"]
        l_ = price_cols_data["low"]

        # 价格列 <= 0
        price_invalid = (price_cols_data <= 0).any(axis=1)
        for idx in df.index[price_invalid]:
            trade_date = idx.date() if hasattr(idx, "date") else idx
            row = df.loc[idx]
            for col in ["open", "close", "high", "low"]:
                val = row.get(col, np.nan)
                if isinstance(val, (int, float)) and val <= 0:
                    issues.append(
                        CalibrationIssue(
                            symbol=symbol,
                            trade_date=trade_date,
                            adjust_type="",
                            field=col,
                            old_value=None,
                            new_value=float(val),
                            diff_ratio=None,
                            decision="failed",
                            message=f"{col}={val} 非法（须 > 0）",
                            checked_at=now,
                        )
                    )

        # high < max(open, close) 容忍度 1e-6
        high_invalid = h < np.maximum(o, c) - 1e-6
        for idx in df.index[high_invalid]:
            trade_date = idx.date() if hasattr(idx, "date") else idx
            row = df.loc[idx]
            issues.append(
                CalibrationIssue(
                    symbol=symbol,
                    trade_date=trade_date,
                    adjust_type="",
                    field="high",
                    old_value=float(row["high"]),
                    new_value=None,
                    diff_ratio=None,
                    decision="failed",
                    message=f"high({row['high']:.2f}) < max(open({row['open']:.2f}), close({row['close']:.2f}))",
                    checked_at=now,
                )
            )

        # low > min(open, close) 容忍度 1e-6
        low_invalid = l_ > np.minimum(o, c) + 1e-6
        for idx in df.index[low_invalid]:
            trade_date = idx.date() if hasattr(idx, "date") else idx
            row = df.loc[idx]
            issues.append(
                CalibrationIssue(
                    symbol=symbol,
                    trade_date=trade_date,
                    adjust_type="",
                    field="low",
                    old_value=None,
                    new_value=float(row["low"]),
                    diff_ratio=None,
                    decision="failed",
                    message=f"low({row['low']:.2f}) > min(open({row['open']:.2f}), close({row['close']:.2f}))",
                    checked_at=now,
                )
            )

        # volume/amount 负值
        vol = df["volume"].astype(float)
        amt = df["amount"].astype(float)
        volume_invalid = (vol < 0) | (amt < 0)
        for idx in df.index[volume_invalid]:
            trade_date = idx.date() if hasattr(idx, "date") else idx
            row = df.loc[idx]
            for col, val in [("volume", row["volume"]), ("amount", row["amount"])]:
                if isinstance(val, (int, float)) and val < 0:
                    issues.append(
                        CalibrationIssue(
                            symbol=symbol,
                            trade_date=trade_date,
                            adjust_type="",
                            field=col,
                            old_value=None,
                            new_value=float(val),
                            diff_ratio=None,
                            decision="failed",
                            message=f"{col} 负值: {val}",
                            checked_at=now,
                        )
                    )

        # 构建 valid_mask（不删行）
        failed_dates = {issue["trade_date"] for issue in issues if issue["decision"] == "failed"}
        valid_mask = pd.Series([d not in failed_dates for d in dates], index=df.index)

        if issues:
            logger.warning(f"L2 校验发现 {len(issues)} 个违规，失败日期 {len(failed_dates)} 个")

        return valid_mask, issues

    def _calibrate_overlap(
        self,
        df_new: pd.DataFrame,
        symbol: str,
        adjust_type: str,
    ) -> list[CalibrationIssue]:
        """
        L3：重叠窗口与本地数据对比

        决策矩阵：
        - BACKFILL: 本地缺行、源有行 → 正常 upsert
        - DISCREPANCY: 源缺行、本地有行 → 保留本地
        - KEEP_LOCAL: 单日少数列超差 → 保留本地 + 告警
        - AUTO_CORRECT_DRIFT: 全区间同比例系统性偏移 → 自动采纳或告警
        """
        from quant.storage.database import Database

        issues: list[CalibrationIssue] = []
        if df_new.empty:
            return issues

        db = Database()
        start = df_new.index.min().date() if hasattr(df_new.index.min(), "date") else df_new.index.min()
        end = df_new.index.max().date() if hasattr(df_new.index.max(), "date") else df_new.index.max()
        df_local = db.get_stock_daily(symbol, start, end, adjust_type)

        # 构建本地数据日期集合
        if df_local.empty:
            # 全是新行 → BACKFILL
            for idx, row in df_new.iterrows():
                trade_date = idx.date() if hasattr(idx, "date") else idx
                issues.append(
                    CalibrationIssue(
                        symbol=symbol,
                        trade_date=trade_date,
                        adjust_type=adjust_type,
                        field="",
                        old_value=None,
                        new_value=None,
                        diff_ratio=None,
                        decision=CalibrationDecision.BACKFILL.value,
                        message="本地缺行，源有行，正常 upsert",
                        checked_at=datetime.now(),
                    )
                )
            return issues

        # index 可能已是 date 列，避免重复设索引产生 MultiIndex
        if "trade_date" in df_local.columns and df_local.index.name != "trade_date":
            df_local = df_local.set_index("trade_date")
        local_dates = set(df_local.index)

        new_dates = set()
        for idx in df_new.index:
            d = idx.date() if hasattr(idx, "date") else idx
            new_dates.add(d)

        # 共同日期（重叠窗口）
        overlap = new_dates & local_dates
        # 本地缺行（源有，本地无）
        backfill_dates = new_dates - local_dates
        # 源缺行（本地有，源无）
        discrepancy_dates = local_dates - new_dates

        # BACKFILL
        for d in backfill_dates:
            issues.append(
                CalibrationIssue(
                    symbol=symbol,
                    trade_date=d,
                    adjust_type=adjust_type,
                    field="",
                    old_value=None,
                    new_value=None,
                    diff_ratio=None,
                    decision=CalibrationDecision.BACKFILL.value,
                    message="本地缺行、源有行",
                    checked_at=datetime.now(),
                )
            )

        # DISCREPANCY
        for d in discrepancy_dates:
            issues.append(
                CalibrationIssue(
                    symbol=symbol,
                    trade_date=d,
                    adjust_type=adjust_type,
                    field="",
                    old_value=None,
                    new_value=None,
                    diff_ratio=None,
                    decision=CalibrationDecision.DISCREPANCY.value,
                    message="源缺行、本地有行",
                    checked_at=datetime.now(),
                )
            )
            if self.config.alert_on_discrepancy:
                logger.warning(f"{symbol} {d}: 源缺行，本地有，保留本地")

        # 重叠窗口逐列对比
        price_cols = ["open", "high", "low", "close"]
        volume_cols = ["volume", "amount"]

        drift_ratios: list[dict] = []
        for d in overlap:
            local_row = df_local.loc[d]
            new_row = df_new.loc[d]
            for col in price_cols:
                old_v = local_row.get(col)
                new_v = new_row.get(col)
                if old_v is None or new_v is None or old_v == 0:
                    continue
                ratio = new_v / old_v
                drift_ratios.append({"date": d, "col": col, "ratio": ratio, "old_v": old_v, "new_v": new_v})

        # P1-03: 漂移识别（全区间同比例系统性偏移）
        if drift_ratios:
            ratios = [r["ratio"] for r in drift_ratios]
            mean_ratio = np.mean(ratios)
            std_ratio = np.std(ratios)
            # 标准差 < 0.001 且均值偏离 1 显著 → 复权漂移
            if std_ratio < 0.001 and abs(mean_ratio - 1.0) > 0.001:
                for r in drift_ratios:
                    decision = (
                        CalibrationDecision.AUTO_CORRECT_DRIFT.value
                        if self.config.auto_correct_drift
                        else CalibrationDecision.KEEP_LOCAL.value
                    )
                    msg = f"复权漂移: {r['col']} 全区间均值 {mean_ratio:.6f}"
                    if self.config.alert_on_discrepancy:
                        logger.warning(f"{symbol}: {msg}")
                    issues.append(
                        CalibrationIssue(
                            symbol=symbol,
                            trade_date=r["date"],
                            adjust_type=adjust_type,
                            field=r["col"],
                            old_value=float(r.get("old_v")),
                            new_value=float(r.get("new_v")),
                            diff_ratio=float(abs(mean_ratio - 1.0)),
                            decision=decision,
                            message=msg,
                            checked_at=datetime.now(),
                        )
                    )
                return issues  # 漂移行不再逐列对比

        # 逐列超差对比
        for d in overlap:
            local_row = df_local.loc[d]
            new_row = df_new.loc[d]
            for col in price_cols:
                old_v = local_row.get(col)
                new_v = new_row.get(col)
                if old_v is None or new_v is None:
                    continue
                if old_v == 0:
                    ratio = abs(new_v - old_v) if new_v != 0 else 0.0
                else:
                    ratio = abs(new_v - old_v) / abs(old_v)
                if ratio > self.config.price_tolerance:
                    decision = CalibrationDecision.KEEP_LOCAL.value
                    msg = f"{col} 差异 {ratio:.4%}，保留本地"
                    if self.config.alert_on_discrepancy:
                        logger.warning(f"{symbol} {d}: {msg}")
                    issues.append(
                        CalibrationIssue(
                            symbol=symbol,
                            trade_date=d,
                            adjust_type=adjust_type,
                            field=col,
                            old_value=float(old_v),
                            new_value=float(new_v),
                            diff_ratio=float(ratio),
                            decision=decision,
                            message=msg,
                            checked_at=datetime.now(),
                        )
                    )

            for col in volume_cols:
                old_v = local_row.get(col)
                new_v = new_row.get(col)
                if old_v is None or new_v is None:
                    continue
                if old_v == 0:
                    ratio = abs(new_v - old_v) / 1.0 if new_v != 0 else 0.0
                else:
                    ratio = abs(new_v - old_v) / abs(old_v)
                if ratio > self.config.volume_tolerance:
                    decision = CalibrationDecision.KEEP_LOCAL.value
                    msg = f"{col} 差异 {ratio:.4%}，保留本地"
                    if self.config.alert_on_discrepancy:
                        logger.warning(f"{symbol} {d}: {msg}")
                    issues.append(
                        CalibrationIssue(
                            symbol=symbol,
                            trade_date=d,
                            adjust_type=adjust_type,
                            field=col,
                            old_value=float(old_v),
                            new_value=float(new_v),
                            diff_ratio=float(ratio),
                            decision=decision,
                            message=msg,
                            checked_at=datetime.now(),
                        )
                    )

        if issues:
            logger.info(f"L3 校准发现 {len(issues)} 个差异")

        return issues

    def _make_suggestion(self, issues: list[CalibrationIssue]) -> str | None:
        """根据 issue 列表生成建议文本"""
        if not issues:
            return None
        failed = sum(1 for i in issues if i["decision"] == "failed")
        discrepancies = sum(1 for i in issues if i["decision"] == CalibrationDecision.DISCREPANCY.value)
        if failed > 0:
            return f"L2 校验失败 {failed} 行，建议检查数据源接口是否正常"
        if discrepancies > 0:
            return f"存在 {discrepancies} 个数据差异，建议人工复核 data_calibration_log 表"
        return None
