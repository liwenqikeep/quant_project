"""
数据获取模块的数据载体

定义 FetchOutcome / BatchFetchReport / DataCalibrationReport 等 dataclass，
以及 AdjustType / FetchStatus 等枚举。禁止公共接口返回裸 dict。
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Literal, NotRequired, TypedDict


class AdjustType(str, Enum):
    """复权类型"""

    NONE = ""  # 不复权
    QFQ = "qfq"  # 前复权（默认）
    HFQ = "hfq"  # 后复权


class FetchStatus(str, Enum):
    """单标的获取状态"""

    SUCCESS = "success"  # 成功（达到期望最新交易日）
    PARTIAL = "partial"  # 部分成功（含 stale/校准差异）
    FAILED = "failed"  # 硬失败（网络/校验，未落库）
    EMPTY = "empty"  # 数据源无该区间数据
    STALE = "stale"  # 数据源未发布期望交易日数据
    SKIPPED = "skipped"  # 断点已覆盖目标区间，无需拉取
    DRY_RUN = "dry_run"  # dry_run 模式，仅打印计划区间


class CalibrationDecision(str, Enum):
    """校准决策"""

    CALIBRATION_OK = "calibration_ok"  # 差异在容差内，正常 upsert
    AUTO_CORRECT_DRIFT = "auto_correct_drift"  # 复权漂移自动修正
    KEEP_LOCAL = "keep_local"  # 保留本地，告警
    BACKFILL = "backfill"  # 本地缺行、源有行，正常 upsert
    DISCREPANCY = "discrepancy"  # 源缺行、本地有行，保留+告警


# TypedDict 定义（供 Database 层字典交互）
class DailyBarDict(TypedDict, total=False):
    """日线行情字典（供 upsert 使用）"""

    symbol: str
    trade_date: date
    adjust_type: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    amplitude: float | None
    change_pct: float | None
    change_amount: float | None
    turnover: float | None
    source: str
    created_at: datetime
    updated_at: datetime


class FetchLogDict(TypedDict, total=False):
    """拉取审计日志字典"""

    symbol: str
    adjust_type: str
    start_date: date
    end_date: date
    status: str
    row_count: int
    error: str | None
    detail: str | None
    duration_ms: int | None
    fetched_at: datetime


class CalibrationIssueDict(TypedDict, total=False):
    """校准差异字典"""

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
class FetchOutcome:
    """单标的获取结果"""

    symbol: str
    adjust_type: str
    status: FetchStatus
    row_count: int = 0
    start_date: date | None = None
    end_date: date | None = None
    message: str | None = None  # stale/empty 时提示文本
    error: str | None = None
    duration_ms: int = 0
    calibration_report: "DataCalibrationReport | None" = None


@dataclass
class DataCalibrationReport:
    """数据校准报告"""

    symbol: str
    adjust_type: str
    total_rows: int = 0
    passed: int = 0
    auto_corrected: int = 0
    discrepancies: int = 0
    l2_failed_count: int = 0  # P1-01: L2 违规行数（整段 failed 依据）
    issues: list[CalibrationIssueDict] = field(default_factory=list)
    suggestion: str | None = None

    @property
    def has_l2_failed(self) -> bool:
        """是否有 L2 硬校验失败"""
        return self.l2_failed_count > 0


@dataclass
class BatchFetchReport:
    """批量获取汇总报告"""

    total: int
    success: int = 0
    partial: int = 0
    failed: int = 0
    empty: int = 0
    stale: int = 0
    skipped: int = 0
    total_rows: int = 0
    total_duration_ms: int = 0
    failures: list[FetchOutcome] = field(default_factory=list)
    stale_symbols: list[FetchOutcome] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为字典（供日志/CLI 输出）"""
        return {
            "total": self.total,
            "success": self.success,
            "partial": self.partial,
            "failed": self.failed,
            "empty": self.empty,
            "stale": self.stale,
            "skipped": self.skipped,
            "total_rows": self.total_rows,
            "total_duration_ms": self.total_duration_ms,
            "failures": [
                {
                    "symbol": f.symbol,
                    "adjust_type": f.adjust_type,
                    "status": f.status.value,
                    "error": f.error,
                }
                for f in self.failures
            ],
            "stale_symbols": [
                {
                    "symbol": s.symbol,
                    "message": s.message,
                }
                for s in self.stale_symbols
            ],
            "suggestions": self.suggestions,
        }
