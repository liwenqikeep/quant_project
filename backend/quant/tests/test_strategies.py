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
        # 创建足够长的价格序列，包含金叉
        dates = pd.date_range(start='2024-01-01', periods=50, freq='D')
        # 先下跌（短期均线在长期均线下方），再上涨穿越
        prices = pd.Series(
            [100, 98, 96, 94, 92, 90, 88, 86, 84, 82,  # 下跌
             85, 88, 91, 94, 97, 100, 103, 106, 109, 112,  # 开始上涨
             115, 118, 121, 124, 127, 130, 133, 136, 139, 142,  # 继续上涨
             145, 148, 151, 154, 157, 160, 163, 166, 169, 172,  # 持续上涨
             170, 168, 166, 164, 162, 160, 158, 156, 154, 152],  # 回调
            index=dates
        )

        strategy = MAStrategy(short_window=5, long_window=10)
        df = prices.to_frame(name='close')
        df = strategy.generate_signals(df)

        # 检查是否有金叉信号（需要足够的数据才能产生）
        golden_crosses = df[df['signal'] == 1]
        assert len(golden_crosses) > 0, f"应产生金叉买入信号（实际信号分布: {df['signal'].value_counts().to_dict()}）"

    def test_ma_death_cross(self):
        """MA死叉卖出信号 - 测试真实策略"""
        # 创建足够长的价格序列，包含死叉
        dates = pd.date_range(start='2024-01-01', periods=50, freq='D')
        # 先上涨（短期均线在长期均线上方），再下跌穿越
        prices = pd.Series(
            [80, 82, 84, 86, 88, 90, 92, 94, 96, 98,  # 上涨
             100, 102, 104, 106, 108, 105, 102, 99, 96, 93,  # 开始下跌
             90, 87, 84, 81, 78, 75, 72, 69, 66, 63,  # 持续下跌
             60, 57, 54, 51, 48, 45, 42, 39, 36, 33,  # 继续下跌
             35, 37, 39, 41, 43, 45, 47, 49, 51, 53],  # 反弹
            index=dates
        )

        strategy = MAStrategy(short_window=5, long_window=10)
        df = prices.to_frame(name='close')
        df = strategy.generate_signals(df)

        # 检查是否有死叉信号
        death_crosses = df[df['signal'] == -1]
        assert len(death_crosses) > 0, f"应产生死叉卖出信号（实际信号分布: {df['signal'].value_counts().to_dict()}）"

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
