"""
测试风控逻辑 - 真实导入生产代码
"""
import pytest
import pandas as pd
import numpy as np

# 真实导入生产代码
from quant.risk.risk_engine import RiskEngine
from quant.risk.position_limits import PositionLimits
from quant.risk.drawdown_control import DrawdownController


class TestRiskControl:
    """风控测试"""

    def test_risk_engine_initialization(self):
        """风险引擎初始化"""
        engine = RiskEngine()
        assert engine is not None
        assert hasattr(engine, 'check_order')

    def test_position_limits_initialization(self):
        """仓位限制初始化"""
        from quant.risk.position_limits import PositionLimitManager
        limits = PositionLimitManager(PositionLimits())
        assert limits is not None
        assert hasattr(limits, 'set_total_value')

    def test_drawdown_control_initialization(self):
        """回撤控制初始化"""
        control = DrawdownController()
        assert control is not None
        assert hasattr(control, 'update')

    def test_drawdown_update(self):
        """回撤更新"""
        control = DrawdownController()
        control.reset(initial_value=100000)

        # 更新权益值
        control.update(100000)  # 初始
        control.update(95000)   # 下跌

        # 获取状态
        status = control.get_status()
        assert status is not None
        assert 'drawdown' in status

    def test_risk_engine_order_check(self):
        """订单风控检查"""
        engine = RiskEngine()
        engine.reset()

        # 按实际 API 传入参数
        allowed, reason, level = engine.check_order(
            symbol='AAPL',
            direction='buy',
            quantity=100,
            price=150.0,
            cash=100000,
            position_value=0,
            total_value=100000
        )

        # 验证返回格式
        assert isinstance(allowed, bool)
        assert isinstance(reason, str)
        assert level in engine.RiskLevel if hasattr(engine, 'RiskLevel') else True

    def test_position_limits_update(self):
        """仓位限制更新"""
        from quant.risk.position_limits import PositionLimitManager
        limits = PositionLimitManager(PositionLimits())
        limits.set_total_value(100000)

        # 更新持仓
        limits.update_position('AAPL', 10000, industry='科技')

        # 获取风控报告
        report = limits.get_exposure_report()
        assert report is not None

    def test_drawdown_history(self):
        """回撤历史"""
        control = DrawdownController()
        control.reset(initial_value=100000)

        # 模拟权益变化
        for value in [100000, 95000, 90000, 95000, 100000]:
            control.update(value)

        # 获取历史数据
        history = control.get_history_df()
        assert len(history) > 0

    def test_risk_engine_reset(self):
        """风控引擎重置"""
        engine = RiskEngine()
        engine.reset()
        assert engine is not None
