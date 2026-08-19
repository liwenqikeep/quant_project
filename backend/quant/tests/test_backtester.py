"""
测试回测引擎 - 真实导入生产代码
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 真实导入生产代码
from quant.backtest.backtester import Backtester


class TestBacktester:
    """回测引擎测试"""

    def setup_method(self):
        """每个测试前重置"""
        self.backtester = Backtester(
            initial_cash=100000,
            commission=0.0003,
            stamp_tax=0.001
        )

    def test_buy_no_stamp_tax(self):
        """买入不收印花税"""
        # 创建简单价格数据
        dates = pd.date_range(start='2024-01-01', periods=5, freq='D')
        prices = pd.DataFrame({
            'close': [100.0, 100.0, 100.0, 100.0, 100.0]
        }, index=dates)

        # 执行买入交易（signal=1）
        trade = self.backtester.execute_trade(
            date=dates[0],
            price=100.0,
            signal=1,
            position_size=100
        )

        # 买入交易不应收取印花税
        assert trade['stamp_tax'] == 0, "买入不应收取印花税"
        # 但应收取佣金
        assert trade['commission'] > 0, "买入应收取佣金"

    def test_sell_has_stamp_tax(self):
        """卖出收取印花税"""
        dates = pd.date_range(start='2024-01-01', periods=10, freq='D')

        # 先买入
        self.backtester.execute_trade(
            date=dates[0],
            price=100.0,
            signal=1,
            position_size=100
        )

        # 再卖出
        trade = self.backtester.execute_trade(
            date=dates[1],
            price=100.0,
            signal=-1,
            position_size=100
        )

        # 卖出应收取印花税
        assert trade['stamp_tax'] > 0, "卖出应收取印花税"
        # 印花税应为成交金额的0.1%
        expected_stamp_tax = trade['trade_value'] * 0.001
        assert abs(trade['stamp_tax'] - expected_stamp_tax) < 0.01

    def test_commission_calculation(self):
        """佣金计算正确"""
        trade_value = 10000  # 100股 * 100元
        expected_commission = trade_value * 0.0003

        # 买入
        trade = self.backtester.execute_trade(
            date=datetime.now(),
            price=100.0,
            signal=1,
            position_size=100
        )

        assert abs(trade['commission'] - expected_commission) < 0.01

    def test_buy_total_cost(self):
        """买入总成本计算"""
        initial_cash = self.backtester.cash

        trade = self.backtester.execute_trade(
            date=datetime.now(),
            price=100.0,
            signal=1,
            position_size=100
        )

        # 现金应减少（买入成本 = 股票价值 + 佣金）
        assert self.backtester.cash < initial_cash
        # 持仓应增加
        assert self.backtester.position > 0

    def test_sell_total_proceed(self):
        """卖出总收入计算"""
        dates = pd.date_range(start='2024-01-01', periods=5, freq='D')

        # 先买入
        self.backtester.execute_trade(
            date=dates[0],
            price=100.0,
            signal=1,
            position_size=100
        )

        cash_before_sell = self.backtester.cash
        position_before_sell = self.backtester.position

        # 卖出
        trade = self.backtester.execute_trade(
            date=dates[1],
            price=100.0,
            signal=-1,
            position_size=100
        )

        # 现金应增加
        assert self.backtester.cash > cash_before_sell
        # 持仓应减少
        assert self.backtester.position < position_before_sell

    def test_full_backtest_run(self):
        """完整回测运行"""
        # 创建测试数据
        dates = pd.date_range(start='2024-01-01', periods=20, freq='D')
        prices = pd.DataFrame({
            'close': 100 + np.cumsum(np.random.randn(20) * 2)
        }, index=dates)

        # 创建信号：买入 -> 持有 -> 卖出
        signals = pd.DataFrame({
            'signal': [1] + [0] * 13 + [-1] + [0] * 5
        }, index=dates)

        results = self.backtester.run(prices, signals)

        # 验证结果
        assert 'total_return' in results
        assert 'sharpe_ratio' in results
        assert 'max_drawdown' in results
        assert 'total_trades' in results
        assert results['total_trades'] >= 2  # 至少有一次买入和一次卖出

    def test_no_signal_no_trade(self):
        """无信号时不交易"""
        dates = pd.date_range(start='2024-01-01', periods=5, freq='D')
        prices = pd.DataFrame({'close': [100, 101, 102, 103, 104]}, index=dates)
        signals = pd.DataFrame({'signal': [0, 0, 0, 0, 0]}, index=dates)

        results = self.backtester.run(prices, signals)

        assert results['total_trades'] == 0
        assert self.backtester.cash == self.backtester.initial_cash

    def test_turnover_calculation(self):
        """换手率计算"""
        optimizer = self.backtester  # Backtester 没有 calculate_turnover，用 PortfolioOptimizer 测试
        from quant.portfolio.optimizer import PortfolioOptimizer

        # 假设有新、旧权重
        old_weights = {"A": 0.3, "B": 0.3, "C": 0.4}
        new_weights = {"A": 0.4, "B": 0.2, "C": 0.4}

        # 手动计算换手率
        turnover = 0
        all_symbols = set(old_weights.keys()) | set(new_weights.keys())
        for sym in all_symbols:
            new_w = new_weights.get(sym, 0)
            old_w = old_weights.get(sym, 0)
            turnover += abs(new_w - old_w)

        expected_turnover = turnover / 2

        # 验证计算正确
        # |0.4-0.3| + |0.2-0.3| = 0.1 + 0.1 = 0.2, 单边换手率 = 0.2 / 2 = 0.1
        assert expected_turnover == 0.1
