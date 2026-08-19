"""
组合优化器
支持均值方差优化、风险平价、的最大 Diversification 等算法
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from quant.utils.logger import logger

try:
    from scipy.optimize import minimize
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logger.warning("scipy未安装，优化功能受限")


class OptimizationMethod(Enum):
    """优化方法"""
    MEAN_VARIANCE = "mean_variance"        # 均值方差
    MIN_VARIANCE = "min_variance"          # 最小方差
    RISK_PARITY = "risk_parity"           # 风险平价
    MAX_SHARPE = "max_sharpe"             # 最大夏普
    MAX_DIVERSIFICATION = "max_div"       # 最大分散化
    EQUAL_WEIGHT = "equal_weight"         # 等权


@dataclass
class PortfolioResult:
    """组合优化结果"""
    weights: Dict[str, float]              # 权重 {symbol: weight}
    expected_return: float                # 预期收益
    expected_volatility: float            # 预期波动率
    sharpe_ratio: float                   # 夏普比率
    max_weight: float                    # 最大权重
    min_weight: float                    # 最小权重
    turnover: float = 0                  # 换手率
    diversification_ratio: float = 0      # 分散化比率


@dataclass
class OptimizationConfig:
    """优化配置"""
    method: OptimizationMethod = OptimizationMethod.MEAN_VARIANCE
    risk_aversion: float = 1.0          # 风险厌恶系数
    target_return: Optional[float] = None  # 目标收益
    target_volatility: Optional[float] = None  # 目标波动率
    
    # 权重约束
    min_weight: float = 0.0              # 最小权重
    max_weight: float = 0.3              # 最大权重
    min_total_weight: float = 0.8        # 最小总权重
    max_total_weight: float = 1.0        # 最大总权重
    
    # 行业/风格约束
    sector_limits: Dict[str, float] = field(default_factory=dict)
    
    # 优化参数
    allow_short: bool = False            # 允许做空
    constraints_penalty: float = 1000     # 违反约束的惩罚系数


class PortfolioOptimizer:
    """组合优化器"""
    
    def __init__(self, config: Optional[OptimizationConfig] = None):
        """
        初始化优化器
        
        Args:
            config: 优化配置
        """
        self.config = config or OptimizationConfig()
        
        if not SCIPY_AVAILABLE:
            logger.warning("scipy未安装，将使用简化优化方法")
        
        logger.info(f"组合优化器初始化: 方法={self.config.method.value}")
    
    def optimize(
        self,
        returns: pd.DataFrame,           # 列: 股票, 行: 日期
        prices: Optional[pd.DataFrame] = None,  # 用于计算相关矩阵
        market_returns: Optional[pd.Series] = None  # 市场收益
    ) -> PortfolioResult:
        """
        执行组合优化
        
        Args:
            returns: 收益率矩阵
            prices: 价格数据（可选）
            market_returns: 市场收益（可选）
        
        Returns:
            优化结果
        """
        symbols = returns.columns.tolist()
        n_assets = len(symbols)
        
        if n_assets == 0:
            raise ValueError("没有可优化的资产")
        
        # 检查约束可行性：n * max_weight >= 1（否则权重和无法达到1）
        effective_max = self._get_effective_max_weight(n_assets)
        
        # 计算收益率统计
        mean_returns = returns.mean() * 252  # 年化
        cov_matrix = returns.cov() * 252      # 年化协方差
        
        # 选择优化方法
        if self.config.method == OptimizationMethod.EQUAL_WEIGHT:
            return self._optimize_equal_weight(symbols)
        elif self.config.method == OptimizationMethod.MIN_VARIANCE:
            return self._optimize_min_variance(symbols, cov_matrix, effective_max)
        elif self.config.method == OptimizationMethod.MAX_SHARPE:
            return self._optimize_max_sharpe(symbols, mean_returns, cov_matrix, effective_max)
        elif self.config.method == OptimizationMethod.RISK_PARITY:
            return self._optimize_risk_parity(symbols, cov_matrix, effective_max)
        elif self.config.method == OptimizationMethod.MEAN_VARIANCE:
            return self._optimize_mean_variance(symbols, mean_returns, cov_matrix, effective_max)
        elif self.config.method == OptimizationMethod.MAX_DIVERSIFICATION:
            return self._optimize_max_diversification(symbols, returns, cov_matrix, effective_max)
        else:
            return self._optimize_equal_weight(symbols)
    
    def _get_effective_max_weight(self, n_assets: int) -> float:
        """
        获取有效的最大权重（考虑约束可行性）
        
        Args:
            n_assets: 资产数量
        
        Returns:
            有效最大权重（如果约束不可行则自动放宽）
        """
        if n_assets * self.config.max_weight < 1.0 - 1e-6:
            effective_max = max(self.config.max_weight, 1.0 / n_assets + 0.05)
            logger.warning(
                f"权重上限 {self.config.max_weight} 过小，{n_assets} 只资产最大总权重 "
                f"{n_assets * self.config.max_weight:.2f} < 1，约束不可行。自动放宽至 {effective_max:.2f}"
            )
            return effective_max
        return self.config.max_weight
    
    def _optimize_equal_weight(self, symbols: List[str]) -> PortfolioResult:
        """等权配置"""
        n = len(symbols)
        weights = {sym: 1.0 / n for sym in symbols}
        
        return PortfolioResult(
            weights=weights,
            expected_return=0,
            expected_volatility=0,
            sharpe_ratio=0,
            max_weight=1.0 / n,
            min_weight=1.0 / n
        )
    
    def _optimize_min_variance(
        self,
        symbols: List[str],
        cov_matrix: pd.DataFrame,
        effective_max: float
    ) -> PortfolioResult:
        """最小方差组合"""
        n = len(symbols)
        
        def portfolio_variance(weights):
            return weights @ cov_matrix.values @ weights
        
        def portfolio_volatility(weights):
            return np.sqrt(portfolio_variance(weights))
        
        # 约束：权重和为1
        constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        
        # 边界（使用有效的最大权重）
        bounds = tuple(
            (self.config.min_weight, effective_max)
            for _ in range(n)
        )
        
        # 初始权重
        w0 = np.ones(n) / n
        
        if SCIPY_AVAILABLE:
            result = minimize(
                portfolio_variance,
                w0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints
            )
            weights = result.x
        else:
            weights = w0
        
        # 归一化
        weights = np.clip(weights, 0, 1)
        weights = weights / weights.sum()
        
        weights_dict = {sym: float(weights[i]) for i, sym in enumerate(symbols)}
        vol = portfolio_volatility(weights)
        
        return PortfolioResult(
            weights=weights_dict,
            expected_return=0,
            expected_volatility=float(vol),
            sharpe_ratio=0,
            max_weight=max(weights),
            min_weight=min(weights)
        )
    
    def _optimize_max_sharpe(
        self,
        symbols: List[str],
        mean_returns: pd.Series,
        cov_matrix: pd.DataFrame,
        effective_max: float
    ) -> PortfolioResult:
        """最大夏普组合"""
        n = len(symbols)
        risk_free_rate = 0.03  # 无风险利率
        
        def neg_sharpe(weights):
            port_return = np.dot(weights, mean_returns.values)
            port_vol = np.sqrt(weights @ cov_matrix.values @ weights)
            if port_vol == 0:
                return 0
            return -(port_return - risk_free_rate) / port_vol
        
        # 约束
        constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        
        # 边界（使用有效的最大权重）
        bounds = tuple(
            (self.config.min_weight, effective_max)
            for _ in range(n)
        )
        
        w0 = np.ones(n) / n
        
        if SCIPY_AVAILABLE:
            result = minimize(
                neg_sharpe,
                w0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints
            )
            weights = result.x
        else:
            weights = w0
        
        # 归一化
        weights = np.clip(weights, 0, 1)
        weights = weights / weights.sum()
        
        weights_dict = {sym: float(weights[i]) for i, sym in enumerate(symbols)}
        port_return = np.dot(weights, mean_returns.values)
        port_vol = np.sqrt(weights @ cov_matrix.values @ weights)
        sharpe = (port_return - risk_free_rate) / port_vol if port_vol > 0 else 0
        
        return PortfolioResult(
            weights=weights_dict,
            expected_return=float(port_return),
            expected_volatility=float(port_vol),
            sharpe_ratio=float(sharpe),
            max_weight=max(weights),
            min_weight=min(weights)
        )
    
    def _optimize_risk_parity(
        self,
        symbols: List[str],
        cov_matrix: pd.DataFrame,
        effective_max: float
    ) -> PortfolioResult:
        """风险平价组合"""
        n = len(symbols)
        
        def risk_contribution(weights, cov):
            portfolio_vol = np.sqrt(weights @ cov @ weights)
            marginal_contrib = cov @ weights
            risk_contrib = weights * marginal_contrib / portfolio_vol
            return risk_contrib
        
        def risk_parity_objective(weights):
            rc = risk_contribution(weights, cov_matrix.values)
            target_rc = np.ones(n) * (np.sqrt(weights @ cov_matrix.values @ weights) / n)
            return np.sum((rc - target_rc) ** 2)
        
        constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        bounds = tuple((self.config.min_weight, effective_max) for _ in range(n))
        w0 = np.ones(n) / n
        
        if SCIPY_AVAILABLE:
            result = minimize(
                risk_parity_objective,
                w0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints
            )
            weights = result.x
        else:
            weights = w0
        
        weights = np.clip(weights, 0, 1)
        weights = weights / weights.sum()
        
        weights_dict = {sym: float(weights[i]) for i, sym in enumerate(symbols)}
        vol = np.sqrt(weights @ cov_matrix.values @ weights)
        
        return PortfolioResult(
            weights=weights_dict,
            expected_return=0,
            expected_volatility=float(vol),
            sharpe_ratio=0,
            max_weight=max(weights),
            min_weight=min(weights),
            diversification_ratio=self._calc_diversification_ratio(weights, cov_matrix)
        )
    
    def _optimize_mean_variance(
        self,
        symbols: List[str],
        mean_returns: pd.Series,
        cov_matrix: pd.DataFrame,
        effective_max: float
    ) -> PortfolioResult:
        """均值方差优化"""
        n = len(symbols)
        ra = self.config.risk_aversion
        
        def utility(weights):
            port_return = np.dot(weights, mean_returns.values)
            port_var = weights @ cov_matrix.values @ weights
            return -(port_return - 0.5 * ra * port_var)
        
        constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        bounds = tuple((self.config.min_weight, effective_max) for _ in range(n))
        w0 = np.ones(n) / n
        
        if SCIPY_AVAILABLE:
            result = minimize(
                utility,
                w0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints
            )
            weights = result.x
        else:
            weights = w0
        
        weights = np.clip(weights, 0, 1)
        weights = weights / weights.sum()
        
        weights_dict = {sym: float(weights[i]) for i, sym in enumerate(symbols)}
        port_return = np.dot(weights, mean_returns.values)
        port_vol = np.sqrt(weights @ cov_matrix.values @ weights)
        sharpe = port_return / port_vol if port_vol > 0 else 0
        
        return PortfolioResult(
            weights=weights_dict,
            expected_return=float(port_return),
            expected_volatility=float(port_vol),
            sharpe_ratio=float(sharpe),
            max_weight=max(weights),
            min_weight=min(weights)
        )
    
    def _optimize_max_diversification(
        self,
        symbols: List[str],
        returns: pd.DataFrame,
        cov_matrix: pd.DataFrame,
        effective_max: float
    ) -> PortfolioResult:
        """最大分散化组合"""
        n = len(symbols)
        
        # 计算各资产波动率
        volatilities = returns.std() * np.sqrt(252)
        
        def diversification_ratio(weights):
            weighted_vol = np.sum(weights * volatilities.values)
            port_vol = np.sqrt(weights @ cov_matrix.values @ weights)
            if port_vol == 0:
                return 0
            return weighted_vol / port_vol
        
        def neg_div(weights):
            return -diversification_ratio(weights)
        
        constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        bounds = tuple((self.config.min_weight, effective_max) for _ in range(n))
        w0 = np.ones(n) / n
        
        if SCIPY_AVAILABLE:
            result = minimize(
                neg_div,
                w0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints
            )
            weights = result.x
        else:
            weights = w0
        
        weights = np.clip(weights, 0, 1)
        weights = weights / weights.sum()
        
        weights_dict = {sym: float(weights[i]) for i, sym in enumerate(symbols)}
        vol = np.sqrt(weights @ cov_matrix.values @ weights)
        div_ratio = diversification_ratio(weights)
        
        return PortfolioResult(
            weights=weights_dict,
            expected_return=0,
            expected_volatility=float(vol),
            sharpe_ratio=0,
            max_weight=max(weights),
            min_weight=min(weights),
            diversification_ratio=float(div_ratio)
        )
    
    def _calc_diversification_ratio(
        self,
        weights: np.ndarray,
        cov_matrix: pd.DataFrame
    ) -> float:
        """计算分散化比率"""
        volatilities = np.sqrt(np.diag(cov_matrix.values))
        weighted_vol = np.sum(weights * volatilities)
        port_vol = np.sqrt(weights @ cov_matrix.values @ weights)
        if port_vol == 0:
            return 0
        return weighted_vol / port_vol
    
    def calculate_turnover(
        self,
        new_weights: Dict[str, float],
        old_weights: Dict[str, float]
    ) -> float:
        """计算换手率"""
        turnover = 0
        all_symbols = set(new_weights.keys()) | set(old_weights.keys())
        
        for sym in all_symbols:
            new_w = new_weights.get(sym, 0)
            old_w = old_weights.get(sym, 0)
            turnover += abs(new_w - old_w)
        
        return turnover / 2  # 单边换手率
    
    def apply_constraints(
        self,
        weights: Dict[str, float],
        sector_map: Optional[Dict[str, str]] = None
    ) -> Dict[str, float]:
        """应用额外约束"""
        result = weights.copy()
        
        # 应用行业约束
        if sector_map:
            sector_weights = {}
            for sym, w in result.items():
                sector = sector_map.get(sym, 'other')
                sector_weights[sector] = sector_weights.get(sector, 0) + w
            
            for sector, w in sector_weights.items():
                if sector in self.config.sector_limits:
                    limit = self.config.sector_limits[sector]
                    if w > limit:
                        # 按比例缩减
                        excess = w - limit
                        for sym in result:
                            if sector_map.get(sym) == sector:
                                result[sym] -= excess / len([s for s in result if sector_map.get(s) == sector])
        
        # 归一化
        total = sum(result.values())
        if total > 0:
            result = {k: v / total for k, v in result.items()}
        
        return result
