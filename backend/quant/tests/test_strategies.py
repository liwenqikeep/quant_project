"""
测试策略信号 - 真实导入生产代码
"""
import pytest
import pandas as pd
import numpy as np

# 真实导入生产代码
from quant.strategies.ma_strategy import MAStrategy
from quant.strategies.rsi_strategy import RSIStrategy
from quant.strategies.macd_strategy import MACDStrategy


class TestSignalGeneration:
    """信号生成测试"""

    def test_ma_golden_cross(self):
        """MA金叉买入信号 - 测试真实策略"""
        # 创建上涨的价格序列，会产生金叉
        dates = pd.date_range(start='2024-01-01', periods=30, freq='D')
        prices = pd.Series(
            [100, 98, 96, 95, 97, 99, 102, 105, 108, 110,
             108, 106, 107, 109, 112, 115, 118, 120, 122, 125,
             123, 121, 122, 124, 127, 130, 133, 135, 132, 130],
            index=dates
        )

        strategy = MAStrategy(short_window=5, long_window=10)
        df = prices.to_frame(name='close')
        df = strategy.generate_signals(df)

        # 检查是否有金叉信号
        golden_crosses = df[df['signal'] == 1]
        assert len(golden_crosses) > 0, "应产生金叉买入信号"

    def test_ma_death_cross(self):
        """MA死叉卖出信号 - 测试真实策略"""
        # 创建下跌的价格序列
        dates = pd.date_range(start='2024-01-01', periods=30, freq='D')
        prices = pd.Series(
            [130, 128, 126, 125, 123, 121, 118, 115, 112, 110,
             112, 114, 113, 111, 108, 105, 102, 100, 98, 95,
             97, 99, 98, 96, 93, 90, 87, 85, 87, 89],
            index=dates
        )

        strategy = MAStrategy(short_window=5, long_window=10)
        df = prices.to_frame(name='close')
        df = strategy.generate_signals(df)

        # 检查是否有死叉信号
        death_crosses = df[df['signal'] == -1]
        assert len(death_crosses) > 0, "应产生死叉卖出信号"

    def test_rsi_oversold_buy(self):
        """RSI超卖买入信号 - 测试真实策略"""
        dates = pd.date_range(start='2024-01-01', periods=30, freq='D')
        # 构造持续下跌的价格（RSI会很低）
        prices = pd.Series(
            [100 - i * 2 for i in range(30)],
            index=dates
        )

        strategy = RSIStrategy(rsi_period=14, oversold=30, overbought=70)
        df = prices.to_frame(name='close')
        df = strategy.generate_signals(df)

        # RSI超卖区域应产生买入信号
        oversold_signals = df[(df['signal'] == 1)]
        assert len(oversold_signals) > 0, "RSI超卖时应产生买入信号"

    def test_rsi_overbought_sell(self):
        """RSI超买卖出信号 - 测试真实策略"""
        dates = pd.date_range(start='2024-01-01', periods=30, freq='D')
        # 构造持续上涨的价格（RSI会很高）
        prices = pd.Series(
            [100 + i * 2 for i in range(30)],
            index=dates
        )

        strategy = RSIStrategy(rsi_period=14, oversold=30, overbought=70)
        df = prices.to_frame(name='close')
        df = strategy.generate_signals(df)

        # RSI超买区域应产生卖出信号
        overbought_signals = df[(df['signal'] == -1)]
        assert len(overbought_signals) > 0, "RSI超买时应产生卖出信号"

    def test_signal_with_nan(self):
        """NaN值处理 - 测试真实策略"""
        dates = pd.date_range(start='2024-01-01', periods=10, freq='D')
        prices = pd.Series([100, np.nan, 102, 103, np.nan, 105, 106, np.nan, 108, 109], index=dates)

        strategy = MAStrategy()
        df = prices.to_frame(name='close')

        # 策略应能处理NaN值，不崩溃
        try:
            result = strategy.generate_signals(df)
            assert result is not None
        except Exception as e:
            pytest.fail(f"策略处理NaN值时崩溃: {e}")

    def test_signal_insufficient_window(self):
        """窗口不足时的处理 - 测试真实策略"""
        dates = pd.date_range(start='2024-01-01', periods=3, freq='D')
        prices = pd.Series([100, 102, 105], index=dates)

        strategy = MAStrategy(short_window=5, long_window=10)  # 窗口大于数据
        df = prices.to_frame(name='close')
        result = strategy.generate_signals(df)

        # 窗口不足时，signal应为NaN或0，不应崩溃
        assert result is not None

    def test_macd_signal(self):
        """MACD信号 - 测试真实策略"""
        dates = pd.date_range(start='2024-01-01', periods=50, freq='D')
        np.random.seed(42)
        prices = pd.Series(
            100 + np.cumsum(np.random.randn(50) * 2),
            index=dates
        )

        strategy = MACDStrategy()
        df = prices.to_frame(name='close')
        df = strategy.generate_signals(df)

        # MACD策略应产生一些信号
        assert 'signal' in df.columns
        # 不应全是NaN
        assert df['signal'].notna().any(), "MACD应产生信号"

    def test_strategy_with_flat_prices(self):
        """价格走平时策略行为"""
        dates = pd.date_range(start='2024-01-01', periods=30, freq='D')
        prices = pd.Series([100] * 30, index=dates)

        strategy = MAStrategy()
        df = prices.to_frame(name='close')
        df = strategy.generate_signals(df)

        # 价格走平时，不应频繁交易
        signal_changes = df['signal'].diff().abs().sum()
        # 30天内信号变化应该很少
        assert signal_changes < 10, "价格走平时信号不应频繁变化"
