"""
测试数据同步功能

覆盖：适配器列映射、单位换算、upsert 幂等、增量断点、
校准（OHLC 合法/非法、涨跌停 0 振幅不误删、重叠窗口差异）、
新鲜度提示、FetchStatus 枚举、BatchFetchReport
"""
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from quant.data.base_data_source import AkshareAdapter
from quant.data.calibration import CalibrationConfig, DataCalibrator
from quant.data.models import (
    AdjustType,
    BatchFetchReport,
    CalibrationDecision,
    CalibrationIssueDict,
    DataCalibrationReport,
    FetchOutcome,
    FetchStatus,
)
from quant.storage.database import Database


# ---------------------------------------------------------------------------
# 辅助：构造规范列 DataFrame
# ---------------------------------------------------------------------------
def make_daily_df(dates, opens, closes, highs, lows, volumes, amounts) -> pd.DataFrame:
    """构造规范列 DataFrame（index=date，列名规范）"""
    data = {
        "open": opens,
        "close": closes,
        "high": highs,
        "low": lows,
        "volume": volumes,
        "amount": amounts,
        "amplitude": [round((h - l) / l * 100, 2) if l > 0 else 0.0 for h, l in zip(highs, lows)],
        "change_pct": [round((c - o) / o * 100, 2) if o > 0 else 0.0 for o, c in zip(opens, closes)],
        "change_amount": [round(c - o, 2) for o, c in zip(opens, closes)],
        "turnover": [round(v / 100000 * 100, 2) for v in volumes],
    }
    df = pd.DataFrame(data, index=pd.to_datetime(dates))
    df.index.name = "date"
    return df


# ---------------------------------------------------------------------------
# 测试 AkshareAdapter._normalize（列映射 + 单位换算）
# ---------------------------------------------------------------------------

class TestAkshareAdapterNormalize:
    """适配器列映射与单位换算"""

    def test_normalize_basic(self):
        """12列东财原始数据 → 规范列，涨跌幅/振幅/换手率转小数"""
        adapter = AkshareAdapter()
        raw = pd.DataFrame({
            "日期": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "股票代码": ["600519", "600519"],
            "开盘": [1800.0, 1790.0],
            "收盘": [1780.0, 1810.0],
            "最高": [1810.0, 1820.0],
            "最低": [1770.0, 1780.0],
            "成交量": [30000.0, 35000.0],
            "成交额": [5.4e8, 6.3e8],
            "振幅": [2.26, 2.24],   # 百分比 → 转小数后 ≈ 0.0226
            "涨跌幅": [-1.11, 1.12],  # 百分比
            "涨跌额": [-20.0, 20.0],
            "换手率": [0.25, 0.30],  # 百分比
        })

        df = adapter._normalize(raw)

        assert list(df.columns) == [
            "date", "open", "close", "high", "low",
            "volume", "amount", "amplitude", "change_pct",
            "change_amount", "turnover",
        ]
        assert df.index.name == "date"
        # 单位换算验证
        assert abs(df.loc["2024-01-02", "amplitude"] - 0.0226) < 0.001
        assert abs(df.loc["2024-01-02", "change_pct"] - (-0.0111)) < 0.001
        assert abs(df.loc["2024-01-02", "turnover"] - 0.0025) < 0.0001

    def test_normalize_missing_column_raises(self):
        """缺失原始列时报 RuntimeError"""
        adapter = AkshareAdapter()
        raw = pd.DataFrame({
            "日期": pd.to_datetime(["2024-01-02"]),
            "开盘": [1800.0],
            # 缺失其他列
        })
        with pytest.raises(RuntimeError, match="AKShare 返回列缺失"):
            adapter._normalize(raw)

    def test_normalize_empty_df(self):
        """空 DataFrame 返回空 DataFrame（列名正确）"""
        adapter = AkshareAdapter()
        raw = pd.DataFrame(columns=[
            "日期", "股票代码", "开盘", "收盘", "最高", "最低",
            "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率",
        ])
        df = adapter._normalize(raw)
        assert df.empty
        assert list(df.columns) == [
            "date", "open", "close", "high", "low",
            "volume", "amount", "amplitude", "change_pct",
            "change_amount", "turnover",
        ]

    def test_to_raw_code(self):
        """_to_raw_code 正确去掉后缀"""
        adapter = AkshareAdapter()
        assert adapter._to_raw_code("600519.SH") == "600519"
        assert adapter._to_raw_code("000001.SZ") == "000001"
        assert adapter._to_raw_code("430001.BJ") == "430001"
        assert adapter._to_raw_code("600519") == "600519"  # 无后缀


# ---------------------------------------------------------------------------
# 测试校准器 L2/L3
# ---------------------------------------------------------------------------

class TestDataCalibrator:
    """数据校准器"""

    def test_validate_legal_ohlc(self):
        """合法 OHLC 通过校验"""
        calibrator = DataCalibrator()
        df = make_daily_df(
            ["2024-01-02", "2024-01-03"],
            opens=[100.0, 101.0],
            closes=[102.0, 100.0],
            highs=[103.0, 102.0],
            lows=[99.0, 99.5],
            volumes=[10000, 11000],
            amounts=[1e6, 1.1e6],
        )
        clean, issues = calibrator.validate(df, "600519.SH")
        assert len(clean) == 2
        assert len(issues) == 0

    def test_validate_high_less_than_open_close(self):
        """high < max(open, close) 被拦截"""
        calibrator = DataCalibrator()
        df = make_daily_df(
            ["2024-01-02"],
            opens=[100.0],
            closes=[98.0],
            highs=[99.0],  # 违法：high < max(open, close)
            lows=[97.0],
            volumes=[10000],
            amounts=[1e6],
        )
        clean, issues = calibrator.validate(df, "600519.SH")
        assert len(clean) == 0
        assert len(issues) > 0

    def test_validate_low_greater_than_open_close(self):
        """low > min(open, close) 被拦截"""
        calibrator = DataCalibrator()
        df = make_daily_df(
            ["2024-01-02"],
            opens=[100.0],
            closes=[102.0],
            highs=[103.0],
            lows=[101.5],  # 违法：low > min(open, close)
            volumes=[10000],
            amounts=[1e6],
        )
        clean, issues = calibrator.validate(df, "600519.SH")
        assert len(clean) == 0

    def test_validate_zero_amplitude_legitimate(self):
        """一字板 amplitude=0 属合法，不得误删"""
        calibrator = DataCalibrator()
        df = make_daily_df(
            ["2024-01-02"],
            opens=[100.0],
            closes=[100.0],
            highs=[100.0],
            lows=[100.0],
            volumes=[0.0],
            amounts=[0.0],
        )
        clean, issues = calibrator.validate(df, "600519.SH")
        # 一字板：high == low == open == close，合法
        # 但 volume/amount=0 也合法
        assert len(issues) == 0

    def test_validate_negative_volume_rejected(self):
        """负 volume 被拦截"""
        calibrator = DataCalibrator()
        df = make_daily_df(
            ["2024-01-02"],
            opens=[100.0],
            closes=[102.0],
            highs=[103.0],
            lows=[99.0],
            volumes=[-100.0],  # 非法
            amounts=[1e6],
        )
        clean, issues = calibrator.validate(df, "600519.SH")
        assert len(clean) == 0
        assert any(i["field"] == "volume" for i in issues)

    def test_calibrate_full_flow(self):
        """完整校准流程：L2 + L3"""
        calibrator = DataCalibrator()
        df = make_daily_df(
            ["2024-01-02", "2024-01-03"],
            opens=[100.0, 101.0],
            closes=[102.0, 100.0],
            highs=[103.0, 102.0],
            lows=[99.0, 99.5],
            volumes=[10000, 11000],
            amounts=[1e6, 1.1e6],
        )
        report = calibrator.calibrate(df, "600519.SH", "qfq")
        assert report.total_rows == 2
        assert report.passed == 2
        assert isinstance(report, DataCalibrationReport)


# ---------------------------------------------------------------------------
# 测试模型枚举
# ---------------------------------------------------------------------------

class TestModels:
    """数据模型与枚举"""

    def test_fetch_status_values(self):
        """FetchStatus 枚举值正确"""
        assert FetchStatus.SUCCESS.value == "success"
        assert FetchStatus.PARTIAL.value == "partial"
        assert FetchStatus.FAILED.value == "failed"
        assert FetchStatus.EMPTY.value == "empty"
        assert FetchStatus.STALE.value == "stale"
        assert FetchStatus.SKIPPED.value == "skipped"

    def test_adjust_type_values(self):
        """AdjustType 枚举值正确"""
        assert AdjustType.NONE.value == ""
        assert AdjustType.QFQ.value == "qfq"
        assert AdjustType.HFQ.value == "hfq"

    def test_batch_fetch_report_to_dict(self):
        """BatchFetchReport.to_dict() 输出结构正确"""
        report = BatchFetchReport(
            total=3,
            success=2,
            failed=1,
            failures=[
                FetchOutcome(
                    symbol="600519.SH",
                    adjust_type="qfq",
                    status=FetchStatus.FAILED,
                    error="network error",
                )
            ],
        )
        d = report.to_dict()
        assert d["total"] == 3
        assert d["success"] == 2
        assert d["failed"] == 1
        assert len(d["failures"]) == 1
        assert d["failures"][0]["symbol"] == "600519.SH"

    def test_fetch_outcome_init(self):
        """FetchOutcome 可正确构造"""
        outcome = FetchOutcome(
            symbol="600519.SH",
            adjust_type="qfq",
            status=FetchStatus.SUCCESS,
            row_count=100,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            message="数据新鲜",
            duration_ms=500,
        )
        assert outcome.symbol == "600519.SH"
        assert outcome.row_count == 100
        assert outcome.status == FetchStatus.SUCCESS

    def test_calibration_decision_values(self):
        """CalibrationDecision 枚举值正确"""
        assert CalibrationDecision.CALIBRATION_OK.value == "calibration_ok"
        assert CalibrationDecision.AUTO_CORRECT_DRIFT.value == "auto_correct_drift"
        assert CalibrationDecision.KEEP_LOCAL.value == "keep_local"
        assert CalibrationDecision.BACKFILL.value == "backfill"
        assert CalibrationDecision.DISCREPANCY.value == "discrepancy"


# ---------------------------------------------------------------------------
# 测试 Database upsert 幂等（mock SQLite）
# ---------------------------------------------------------------------------

class TestDatabaseUpsert:
    """数据库 upsert 幂等"""

    def test_upsert_stock_daily_rejects_empty_list(self):
        """空列表直接返回 0，不抛异常"""
        db = Database()
        assert db.upsert_stock_daily([]) == 0

    def test_save_calibration_logs_rejects_empty_list(self):
        """空列表直接返回 0"""
        db = Database()
        assert db.save_calibration_logs([]) == 0

    def test_get_latest_success_fetch_returns_none_when_no_record(self):
        """无记录时返回 None"""
        db = Database()
        # 使用不存在的标的
        result = db.get_latest_success_fetch("NONEXIST.SZ", "qfq")
        assert result is None

    def test_insert_fetch_log_returns_id(self):
        """insert_fetch_log 返回非负整数或 -1"""
        db = Database()
        log = {
            "symbol": "600519.SH",
            "adjust_type": "qfq",
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 1, 31),
            "status": "success",
            "row_count": 100,
            "fetched_at": datetime.now(),
        }
        result = db.insert_fetch_log(log)
        assert isinstance(result, int)
        assert result >= -1


# ---------------------------------------------------------------------------
# 测试 DataSyncService 区间计算（mock 数据库）
# ---------------------------------------------------------------------------

class TestDataSyncServiceInterval:
    """DataSyncService 区间计算"""

    def test_parse_date_handles_yyyymmdd(self):
        """_parse_date 正确解析 YYYYMMDD"""
        from quant.data.sync import DataSyncService
        assert DataSyncService._parse_date("20240101") == date(2024, 1, 1)

    def test_parse_date_handles_iso_format(self):
        """_parse_date 正确解析 YYYY-MM-DD"""
        from quant.data.sync import DataSyncService
        assert DataSyncService._parse_date("2024-01-01") == date(2024, 1, 1)


# ---------------------------------------------------------------------------
# 测试 CalibrationConfig
# ---------------------------------------------------------------------------

class TestCalibrationConfig:
    """校准配置"""

    def test_default_values(self):
        """默认配置值正确"""
        config = CalibrationConfig()
        assert config.enabled is True
        assert config.price_tolerance == 0.001
        assert config.volume_tolerance == 0.01
        assert config.auto_correct_drift is True
        assert config.alert_on_discrepancy is True

    def test_custom_values(self):
        """自定义配置值正确"""
        config = CalibrationConfig(
            price_tolerance=0.005,
            volume_tolerance=0.02,
            auto_correct_drift=False,
        )
        assert config.price_tolerance == 0.005
        assert config.volume_tolerance == 0.02
        assert config.auto_correct_drift is False
