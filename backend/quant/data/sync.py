"""
数据同步服务

提供 DataSyncService：增量区间计算、批量编排、新鲜度检查、审计写入。
定时执行通过 infrastructure/scheduler.py 注册任务。
"""
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from quant.config import get_config
from quant.data.base_data_source import AkshareAdapter
from quant.data.calibration import CalibrationConfig, DataCalibrator
from quant.data.errors import DataFetchError
from quant.data.models import (
    BatchFetchReport,
    DailyBarDict,
    FetchLogDict,
    FetchOutcome,
    FetchStatus,
)
from quant.storage.database import Database
from quant.utils.logger import logger


@dataclass
class DataSyncConfig:
    """同步配置（从 config.yaml 读取）"""

    default_time: str = "17:30"
    target_date_mode: str = "last_trade_date"
    stale_tolerance_trading_days: int = 1
    retry: int = 3
    timeout_seconds: float = 20.0
    backoff_base_seconds: float = 1.0
    incremental: bool = True
    lookback_days: int = 10  # 重叠窗口（自然日）
    backfill_start: str = "20000101"
    batch_size: int = 20
    max_workers: int = 1  # 默认串行，防限流
    request_interval_seconds: float = 0.5
    adjust: str = "qfq"
    stock_pool: list[str] = field(default_factory=list)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)

    @classmethod
    def from_config(cls) -> "DataSyncConfig":
        """从 config.yaml 加载"""
        cfg = get_config()
        calib_cfg = CalibrationConfig(
            enabled=cfg.get("data.fetch.calibration.enabled", True),
            price_tolerance=cfg.get("data.fetch.calibration.price_tolerance", 0.001),
            volume_tolerance=cfg.get("data.fetch.calibration.volume_tolerance", 0.01),
            auto_correct_drift=cfg.get("data.fetch.calibration.auto_correct_drift", True),
            alert_on_discrepancy=cfg.get("data.fetch.calibration.alert_on_discrepancy", True),
        )
        return cls(
            default_time=cfg.get("data.fetch.default_time", "17:30"),
            target_date_mode=cfg.get("data.fetch.target_date_mode", "last_trade_date"),
            stale_tolerance_trading_days=cfg.get("data.fetch.stale_tolerance_trading_days", 1),
            retry=cfg.get("data.fetch.retry", 3),
            timeout_seconds=cfg.get("data.fetch.timeout_seconds", 20.0),
            backoff_base_seconds=cfg.get("data.fetch.backoff_base_seconds", 1.0),
            incremental=cfg.get("data.fetch.incremental", True),
            lookback_days=cfg.get("data.fetch.lookback_days", 10),
            backfill_start=cfg.get("data.fetch.backfill_start", "20000101"),
            batch_size=cfg.get("data.fetch.batch_size", 20),
            max_workers=cfg.get("data.fetch.max_workers", 1),
            request_interval_seconds=cfg.get("data.fetch.request_interval_seconds", 0.5),
            adjust=cfg.get("data.adjust", "qfq"),
            stock_pool=cfg.get("data.stock_pool", []),
            calibration=calib_cfg,
        )


class DataSyncService:
    """
    数据同步服务

    职责：日历初始化 -> 解析目标区间 -> 调用适配器获取 -> 规范化 -> 校验校准 ->
    upsert -> 写审计 -> 新鲜度检查 -> 汇总报告
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        adapter: Optional[AkshareAdapter] = None,
        config: Optional[DataSyncConfig] = None,
    ):
        self.db = db or Database()
        self.config = config or DataSyncConfig.from_config()
        adapter_cfg = {
            "data.fetch.retry": self.config.retry,
            "data.fetch.timeout_seconds": self.config.timeout_seconds,
            "data.fetch.backoff_base_seconds": self.config.backoff_base_seconds,
        }
        self.adapter = adapter or AkshareAdapter(config=adapter_cfg)
        self.calibrator = DataCalibrator(config=self.config.calibration)
        self._calendar_ready = True  # 日历是否可用

    # -------------------------------------------------------------------------
    # 公共接口
    # -------------------------------------------------------------------------

    def run_incremental(
        self,
        symbols: Optional[list[str]] = None,
        adjust: Optional[str] = None,
        dry_run: bool = False,
    ) -> BatchFetchReport:
        """
        增量同步

        Args:
            symbols: 标的列表，None 时用配置中 stock_pool
            adjust: 复权类型，None 时用配置中 adjust
            dry_run: True 则只打印计划区间，不实际拉取

        Returns:
            BatchFetchReport
        """
        symbols = symbols or self.config.stock_pool
        adjust = adjust or self.config.adjust

        if not symbols:
            logger.warning("标的池为空，跳过同步")
            return BatchFetchReport(total=0)

        # P1-05: 日历初始化（前置依赖）
        self._ensure_calendar()

        report = BatchFetchReport(total=len(symbols))
        t_start = datetime.now()

        for symbol in symbols:
            outcome = self._sync_single(symbol, adjust, dry_run)
            report.total_rows += outcome.row_count
            report.total_duration_ms += outcome.duration_ms

            if outcome.status == FetchStatus.SUCCESS:
                report.success += 1
            elif outcome.status == FetchStatus.PARTIAL:
                report.partial += 1
            elif outcome.status == FetchStatus.FAILED:
                report.failures.append(outcome)
                report.failed += 1
            elif outcome.status == FetchStatus.EMPTY:
                report.empty += 1
            elif outcome.status == FetchStatus.STALE:
                report.stale += 1
                report.stale_symbols.append(outcome)
            elif outcome.status == FetchStatus.SKIPPED:
                report.skipped += 1

            # 礼貌限流
            if not dry_run:
                time.sleep(self.config.request_interval_seconds)

        elapsed = (datetime.now() - t_start).total_seconds() * 1000
        logger.info(
            f"批量同步完成: 成功 {report.success}/{len(symbols)}, "
            f"失败 {report.failed}, 跳过 {report.skipped}, "
            f"stale {report.stale}, 耗时 {elapsed:.0f}ms"
        )
        return report

    def run_full(
        self,
        symbols: Optional[list[str]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        adjust: Optional[str] = None,
    ) -> BatchFetchReport:
        """
        全量同步（忽略断点，从指定起点拉取）

        Args:
            symbols: 标的列表
            start: 开始日期 YYYYMMDD，默认配置 backfill_start
            end: 结束日期 YYYYMMDD，默认今天
            adjust: 复权类型
        """
        symbols = symbols or self.config.stock_pool
        adjust = adjust or self.config.adjust
        start_date = start or self.config.backfill_start
        end_date = end or date.today().strftime("%Y%m%d")

        if not symbols:
            return BatchFetchReport(total=0)

        self._ensure_calendar()

        report = BatchFetchReport(total=len(symbols))
        t_start = datetime.now()

        for symbol in symbols:
            outcome = self._fetch_and_save(symbol, start_date, end_date, adjust)
            report.total_rows += outcome.row_count
            report.total_duration_ms += outcome.duration_ms

            if outcome.status == FetchStatus.SUCCESS:
                report.success += 1
            elif outcome.status == FetchStatus.PARTIAL:
                report.partial += 1
            else:
                report.failures.append(outcome)
                report.failed += 1

            time.sleep(self.config.request_interval_seconds)

        return report

    # -------------------------------------------------------------------------
    # 内部方法
    # -------------------------------------------------------------------------

    def _ensure_calendar(self) -> None:
        """
        P1-05: 确保交易日历已初始化

        日历为空或最新日期早于今天前一年时自动拉取。
        拉取失败降级提示，不抛异常。
        """
        from quant.utils.calendar import TradingCalendar

        cal = TradingCalendar()
        today = date.today()
        cutoff = today - timedelta(days=365)

        # 检查日历是否需要更新
        if not cal.trading_days or (cal.trading_days and max(cal.trading_days) < cutoff):
            try:
                logger.info("交易日历过期或为空，自动从 AKShare 更新...")
                cal.update_calendar()
                logger.info(f"日历已更新，最新交易日: {max(cal.trading_days)}")
            except Exception as e:
                self._calendar_ready = False
                logger.warning(
                    f"交易日历更新失败，降级处理（当天数为基准）: {e}"
                )

    def _sync_single(
        self,
        symbol: str,
        adjust: str,
        dry_run: bool,
    ) -> FetchOutcome:
        """单标的增量同步，返回 FetchOutcome"""
        t0 = time.time()
        # 1. 计算区间
        start_str, end_str, skipped = self._resolve_interval(symbol, adjust)
        if skipped:
            duration_ms = int((time.time() - t0) * 1000)
            return FetchOutcome(
                symbol=symbol,
                adjust_type=adjust,
                status=FetchStatus.SKIPPED,
                duration_ms=duration_ms,
            )

        if dry_run:
            logger.info(f"[dry_run] {symbol}: 计划区间 [{start_str}, {end_str}]")
            duration_ms = int((time.time() - t0) * 1000)
            return FetchOutcome(
                symbol=symbol,
                adjust_type=adjust,
                status=FetchStatus.SKIPPED,
                start_date=self._parse_date(start_str),
                end_date=self._parse_date(end_str),
                duration_ms=duration_ms,
                message=f"[dry_run] 计划区间 [{start_str}, {end_str}]",
            )

        # 2. 拉取 + 规范化 + 校验
        return self._fetch_and_save(symbol, start_str, end_str, adjust)

    def _fetch_and_save(
        self,
        symbol: str,
        start_str: str,
        end_str: str,
        adjust: str,
    ) -> FetchOutcome:
        """拉取数据并落库，返回 FetchOutcome"""
        t0 = time.time()
        # P1-06: 优先捕获 DataFetchError
        try:
            df = self.adapter.get_stock_history(symbol, start_str, end_str, adjust)
        except DataFetchError as e:
            duration_ms = int((time.time() - t0) * 1000)
            logger.error(f"获取 {symbol} 失败: {e}")
            self._write_fetch_log(
                symbol, adjust, start_str, end_str, "failed", 0,
                f"DataFetchError: {e}"
            )
            return FetchOutcome(
                symbol=symbol,
                adjust_type=adjust,
                status=FetchStatus.FAILED,
                start_date=self._parse_date(start_str),
                end_date=self._parse_date(end_str),
                error=str(e),
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - t0) * 1000)
            logger.error(f"获取 {symbol} 失败: {e}")
            self._write_fetch_log(
                symbol, adjust, start_str, end_str, "failed", 0, str(e)
            )
            return FetchOutcome(
                symbol=symbol,
                adjust_type=adjust,
                status=FetchStatus.FAILED,
                start_date=self._parse_date(start_str),
                end_date=self._parse_date(end_str),
                error=str(e),
                duration_ms=duration_ms,
            )

        if df.empty:
            duration_ms = int((time.time() - t0) * 1000)
            self._write_fetch_log(
                symbol, adjust, start_str, end_str, "empty", 0,
                f"数据源无 [{start_str}, {end_str}] 数据"
            )
            return FetchOutcome(
                symbol=symbol,
                adjust_type=adjust,
                status=FetchStatus.EMPTY,
                start_date=self._parse_date(start_str),
                end_date=self._parse_date(end_str),
                message=f"数据源无 [{start_str}, {end_str}] 数据",
                duration_ms=duration_ms,
            )

        # P1-01: calibrate 返回 (clean_df, report)
        clean_df, calibration_report = self.calibrator.calibrate(df, symbol, adjust)

        # P1-01: L2 违规整段 failed，不落库
        if calibration_report.has_l2_failed:
            duration_ms = int((time.time() - t0) * 1000)
            error_msg = f"L2 校验失败 {calibration_report.l2_failed_count} 行"
            logger.warning(f"{symbol}: {error_msg}")
            self._write_fetch_log(
                symbol, adjust, start_str, end_str, "failed", 0, error_msg
            )
            return FetchOutcome(
                symbol=symbol,
                adjust_type=adjust,
                status=FetchStatus.FAILED,
                start_date=self._parse_date(start_str),
                end_date=self._parse_date(end_str),
                error=error_msg,
                duration_ms=duration_ms,
                calibration_report=calibration_report,
            )

        # P1-03: L3 校准决策，生成 upsert bars
        bars, calibration_issues = self._apply_calibration(
            clean_df, symbol, adjust, calibration_report
        )

        # 4. upsert（只有 bars 非空时才落库）
        row_count = 0
        if bars:
            try:
                row_count = self.db.upsert_stock_daily(bars)
            except Exception as e:
                duration_ms = int((time.time() - t0) * 1000)
                logger.error(f"upsert {symbol} 失败: {e}")
                self._write_fetch_log(
                    symbol, adjust, start_str, end_str, "failed", 0, str(e)
                )
                return FetchOutcome(
                    symbol=symbol,
                    adjust_type=adjust,
                    status=FetchStatus.FAILED,
                    start_date=self._parse_date(start_str),
                    end_date=self._parse_date(end_str),
                    error=str(e),
                    duration_ms=duration_ms,
                    calibration_report=calibration_report,
                )

        # 5. 写校准日志
        if calibration_issues:
            self.db.save_calibration_logs(calibration_issues)

        # 6. P1-02: 新鲜度检查（actual = 本次拉取最大日期）
        actual_date = clean_df.index.max().date() if len(clean_df) else None
        expected_date = self._resolve_target_date()
        status, message = self._check_freshness(actual_date, expected_date)

        # 7. 写审计日志
        detail = self._build_detail(calibration_report, status, expected_date, actual_date)
        duration_ms = int((time.time() - t0) * 1000)
        self._write_fetch_log(
            symbol, adjust, start_str, end_str, status, row_count, None, detail
        )

        return FetchOutcome(
            symbol=symbol,
            adjust_type=adjust,
            status=FetchStatus(status),
            row_count=row_count,
            start_date=self._parse_date(start_str),
            end_date=actual_date,
            message=message,
            duration_ms=duration_ms,
            calibration_report=calibration_report,
        )

    def _apply_calibration(
        self,
        df: pd.DataFrame,
        symbol: str,
        adjust: str,
        report: "DataCalibrationReport",
    ) -> tuple[list[DailyBarDict], list]:
        """
        P1-03: 根据 L3 校准决策生成 upsert bars

        - AUTO_CORRECT_DRIFT: 新数据 upsert
        - KEEP_LOCAL / DISCREPANCY: 跳过（不覆盖本地）
        - BACKFILL: 正常 upsert
        """
        bars: list[DailyBarDict] = []
        issues: list = []
        now = datetime.now()

        for idx, row in df.iterrows():
            trade_date = idx.date() if hasattr(idx, "date") else idx
            decision = None
            # 查找该行在校准报告中的决策
            for issue in report.issues:
                if issue.get("trade_date") == trade_date:
                    decision = issue.get("decision", "")
                    break

            # KEEP_LOCAL / DISCREPANCY：不覆盖，跳过
            if decision in ("keep_local", "discrepancy"):
                continue

            bars.append(
                DailyBarDict(
                    symbol=symbol,
                    trade_date=trade_date,
                    adjust_type=adjust,
                    open=float(row.get("open", 0)),
                    high=float(row.get("high", 0)),
                    low=float(row.get("low", 0)),
                    close=float(row.get("close", 0)),
                    volume=float(row.get("volume", 0)),
                    amount=float(row.get("amount", 0)),
                    amplitude=float(row["amplitude"]) if pd.notna(row.get("amplitude")) else None,
                    change_pct=float(row["change_pct"]) if pd.notna(row.get("change_pct")) else None,
                    change_amount=float(row["change_amount"]) if pd.notna(row.get("change_amount")) else None,
                    turnover=float(row["turnover"]) if pd.notna(row.get("turnover")) else None,
                    source="akshare-em",
                    created_at=now,
                    updated_at=now,
                )
            )

        return bars, issues

    def _check_freshness(
        self,
        actual: Optional[date],
        expected: date,
    ) -> tuple[str, Optional[str]]:
        """
        P1-02: 新鲜度检查

        容忍度语义：
        - 无数据 → empty
        - actual < expected 且滞后 > tolerance → stale
        - actual < expected 但在容忍度内 → partial
        - actual >= expected → success
        """
        if actual is None:
            return "empty", f"数据源无 [{expected}] 数据"

        if actual < expected:
            from quant.utils.calendar import get_calendar

            cal = get_calendar()
            lag_days = len(cal.get_trading_days_between(actual, expected))
            if lag_days > self.config.stale_tolerance_trading_days:
                msg = f"期望最新 {expected}，数据源实际 {actual}（滞后 {lag_days} 个交易日）"
                logger.warning(f"stale: {msg}")
                return "stale", msg
            else:
                msg = f"数据源尚未发布 {expected}，最新截至 {actual}"
                return "partial", msg

        return "success", None

    def _resolve_interval(
        self,
        symbol: str,
        adjust: str,
    ) -> tuple[str, str, bool]:
        """
        计算增量区间

        Returns:
            (start_str, end_str, skipped)
            skipped=True 表示断点已覆盖目标，无需拉取
        """
        end_str = self._resolve_target_date().strftime("%Y%m%d")

        if not self.config.incremental:
            start_str = self.config.backfill_start
            return start_str, end_str, False

        # 查断点
        bp = self.db.get_latest_success_fetch(symbol, adjust)
        if bp is None:
            start_str = self.config.backfill_start
            return start_str, end_str, False

        # 有断点：start = 断点 end_date - lookback_days
        bp_end: date = bp["end_date"]
        lookback = bp_end - timedelta(days=self.config.lookback_days)
        start_str = max(lookback, self._parse_date(self.config.backfill_start)).strftime("%Y%m%d")
        end_date = self._resolve_target_date()
        # start > end → 跳过
        if self._parse_date(start_str) > end_date:
            logger.info(f"{symbol}: 断点已覆盖目标 {end_date}，跳过")
            return start_str, end_str, True

        return start_str, end_str, False

    def _resolve_target_date(self) -> date:
        """
        P1-05: 解析期望最新数据日（日历不可用时降级返回今天）

        - last_trade_date：日历中 <= 今天 的最近交易日
        - today：今天（非交易日回退上一交易日）
        """
        if not self._calendar_ready:
            logger.warning("日历不可用，期望日期降级为今天")
            return date.today()

        from quant.utils.calendar import get_calendar

        cal = get_calendar()
        today = date.today()

        if self.config.target_date_mode == "today":
            if cal.is_trading_day(today):
                return today
            return cal.get_previous_trading_day(today)
        else:
            # last_trade_date：取 <= today 的最近交易日
            trading_days = [d for d in cal.trading_days if d <= today]
            if not trading_days:
                return today
            return max(trading_days)

    def _write_fetch_log(
        self,
        symbol: str,
        adjust: str,
        start_str: str,
        end_str: str,
        status: str,
        row_count: int,
        error: Optional[str],
        detail: Optional[str] = None,
    ) -> None:
        """写拉取审计日志"""
        try:
            log: FetchLogDict = {
                "symbol": symbol,
                "adjust_type": adjust,
                "start_date": self._parse_date(start_str),
                "end_date": self._parse_date(end_str),
                "status": status,
                "row_count": row_count,
                "error": error,
                "detail": detail,
                "fetched_at": datetime.now(),
            }
            self.db.insert_fetch_log(log)
        except Exception as e:
            logger.error(f"写 fetch_log 失败: {e}")

    def _build_detail(
        self,
        calibration_report: "DataCalibrationReport | None",
        status: str,
        expected: date,
        actual: Optional[date],
    ) -> Optional[str]:
        """构建 detail JSON 字符串"""
        import json

        d: dict = {}
        if calibration_report:
            d["calibration"] = {
                "total_rows": calibration_report.total_rows,
                "passed": calibration_report.passed,
                "auto_corrected": calibration_report.auto_corrected,
                "discrepancies": calibration_report.discrepancies,
            }
        if status in ("stale", "partial", "empty"):
            d["freshness"] = {
                "expected": str(expected),
                "actual": str(actual) if actual else None,
            }
        if not d:
            return None
        return json.dumps(d, ensure_ascii=False)

    @staticmethod
    def _parse_date(s: str) -> date:
        """解析 YYYYMMDD / YYYY-MM-DD 为 date"""
        s = s.replace("-", "")
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
