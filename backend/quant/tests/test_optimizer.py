"""
测试组合优化器 - 真实导入生产代码
"""
import pytest
import pandas as pd
import numpy as np

# 真实导入生产代码
from quant.portfolio.optimizer import PortfolioOptimizer, OptimizationConfig, OptimizationMethod


class TestPortfolioOptimizer:
    """组合优化器测试"""

    def test_equal_weight_optimization(self):
        """等权组合优化"""
        symbols = ["AAPL", "GOOGL", "MSFT"]
        returns = pd.DataFrame(
            np.random.randn(100, 3) * 0.02,
            columns=symbols
        )

        optimizer = PortfolioOptimizer(
            OptimizationConfig(method=OptimizationMethod.EQUAL_WEIGHT)
        )
        result = optimizer.optimize(returns)

        # 验证权重
        assert len(result.weights) == 3
        assert all(symbol in result.weights for symbol in symbols)
        # 等权应为 1/3
        for w in result.weights.values():
            assert abs(w - 1/3) < 0.01

    def test_min_variance_optimization(self):
        """最小方差优化"""
        symbols = ["A", "B", "C"]
        returns = pd.DataFrame(
            np.random.randn(100, 3) * 0.01,
            columns=symbols
        )

        optimizer = PortfolioOptimizer(
            OptimizationConfig(method=OptimizationMethod.MIN_VARIANCE)
        )
        result = optimizer.optimize(returns)

        # 验证权重和为1
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 0.01

    def test_risk_parity_optimization(self):
        """风险平价优化"""
        symbols = ["A", "B", "C"]
        # 构造一个简单的收益率矩阵
        np.random.seed(42)
        returns = pd.DataFrame(
            np.random.randn(252, 3) * 0.015,
            columns=symbols
        )

        optimizer = PortfolioOptimizer(
            OptimizationConfig(method=OptimizationMethod.RISK_PARITY)
        )
        result = optimizer.optimize(returns)

        # 验证权重
        assert len(result.weights) == 3
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 0.01

        # 验证风险平价：各资产风险贡献应接近相等
        weights = np.array(list(result.weights.values()))
        cov = returns.cov() * 252
        cov_matrix = cov.values

        # 计算风险贡献
        portfolio_vol = np.sqrt(weights @ cov_matrix @ weights)
        marginal_contrib = cov_matrix @ weights
        risk_contrib = weights * marginal_contrib / portfolio_vol
        total_risk = portfolio_vol

        # 各资产风险贡献比例应接近相等
        risk_ratios = risk_contrib / total_risk
        assert risk_ratios.std() < 0.15, "风险贡献应大致相等"

    def test_weight_bounds(self):
        """权重边界约束"""
        symbols = ["A", "B", "C", "D"]
        returns = pd.DataFrame(
            np.random.randn(100, 4) * 0.02,
            columns=symbols
        )

        config = OptimizationConfig(
            method=OptimizationMethod.MIN_VARIANCE,
            min_weight=0.05,
            max_weight=0.4
        )
        optimizer = PortfolioOptimizer(config)
        result = optimizer.optimize(returns)

        # 验证权重边界
        for w in result.weights.values():
            assert 0.04 <= w <= 0.42, f"权重 {w} 超出边界 [0.05, 0.4]"

    def test_weights_sum_to_one(self):
        """优化后权重应归一化"""
        symbols = ["A", "B", "C"]
        returns = pd.DataFrame(
            np.random.randn(100, 3) * 0.01,
            columns=symbols
        )

        for method in [OptimizationMethod.EQUAL_WEIGHT,
                       OptimizationMethod.MIN_VARIANCE,
                       OptimizationMethod.MAX_SHARPE]:
            optimizer = PortfolioOptimizer(OptimizationConfig(method=method))
            result = optimizer.optimize(returns)
            total = sum(result.weights.values())
            assert abs(total - 1.0) < 0.01, f"权重和方法 {method} 总和应接近1"

    def test_empty_returns_error(self):
        """空收益率数据应抛出错误"""
        optimizer = PortfolioOptimizer()

        with pytest.raises(ValueError):
            optimizer.optimize(pd.DataFrame())

    def test_single_asset(self):
        """单资产优化"""
        returns = pd.DataFrame({"A": np.random.randn(100) * 0.01})

        optimizer = PortfolioOptimizer(
            OptimizationConfig(method=OptimizationMethod.EQUAL_WEIGHT)
        )
        result = optimizer.optimize(returns)

        assert result.weights["A"] == 1.0
