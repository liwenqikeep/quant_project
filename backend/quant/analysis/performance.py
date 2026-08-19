"""
绩效分析模块
计算和评估交易策略的绩效指标
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from quant.utils.logger import logger


@dataclass
class PerformanceMetrics:
    """绩效指标"""
    total_return: float = 0           # 总收益率
    annual_return: float = 0           # 年化收益率
    volatility: float = 0             # 年化波动率
    sharpe_ratio: float = 0           # 夏普比率
    sortino_ratio: float = 0          # 索提诺比率
    max_drawdown: float = 0           # 最大回撤
    max_drawdown_duration: int = 0    # 最大回撤持续天数
    calmar_ratio: float = 0           # 卡玛比率
    win_rate: float = 0               # 胜率
    profit_loss_ratio: float = 0      # 盈亏比
    avg_holding_days: float = 0       # 平均持仓天数
    turnover: float = 0              # 换手率
    information_ratio: float = 0     # 信息比率
    tracking_error: float = 0         # 跟踪误差
    alpha: float = 0                 # Alpha
    beta: float = 0                  # Beta


class PerformanceAnalyzer:
    """绩效分析器"""
    
    def __init__(self, risk_free_rate: float = 0.03):
        """
        初始化绩效分析器
        
        Args:
            risk_free_rate: 无风险利率（年化）
        """
        self.risk_free_rate = risk_free_rate
        logger.info(f"绩效分析器初始化: 无风险利率={risk_free_rate:.2%}")
    
    def analyze(
        self,
        equity_curve: pd.Series,
        benchmark_returns: Optional[pd.Series] = None,
        trades: Optional[List[Dict]] = None
    ) -> PerformanceMetrics:
        """
        分析绩效
        
        Args:
            equity_curve: 权益曲线
            benchmark_returns: 基准收益
            trades: 交易记录列表
        
        Returns:
            绩效指标
        """
        if len(equity_curve) < 2:
            logger.warning("数据不足，无法分析绩效")
            return PerformanceMetrics()
        
        # 计算收益率序列
        returns = equity_curve.pct_change().dropna()
        
        metrics = PerformanceMetrics()
        
        # 基本指标
        metrics.total_return = self._calculate_total_return(equity_curve)
        metrics.annual_return = self._calculate_annual_return(equity_curve)
        metrics.volatility = self._calculate_volatility(returns)
        metrics.sharpe_ratio = self._calculate_sharpe_ratio(returns)
        metrics.sortino_ratio = self._calculate_sortino_ratio(returns)
        
        # 回撤指标
        dd, duration = self._calculate_drawdown(equity_curve)
        metrics.max_drawdown = dd
        metrics.max_drawdown_duration = duration
        
        # 风险调整指标
        metrics.calmar_ratio = self._calculate_calmar_ratio(
            metrics.annual_return, metrics.max_drawdown
        )
        
        # 交易指标
        if trades:
            trade_metrics = self._calculate_trade_metrics(trades)
            metrics.win_rate = trade_metrics['win_rate']
            metrics.profit_loss_ratio = trade_metrics['profit_loss_ratio']
            metrics.avg_holding_days = trade_metrics['avg_holding_days']
            metrics.turnover = trade_metrics['turnover']
        
        # 相对基准指标
        if benchmark_returns is not None:
            aligned_returns = returns.align(benchmark_returns, join='inner')
            metrics.information_ratio = self._calculate_information_ratio(
                aligned_returns[0], aligned_returns[1]
            )
            metrics.tracking_error = self._calculate_tracking_error(
                aligned_returns[0], aligned_returns[1]
            )
            metrics.alpha, metrics.beta = self._calculate_alpha_beta(
                aligned_returns[0], aligned_returns[1]
            )
        
        return metrics
    
    def _calculate_total_return(self, equity_curve: pd.Series) -> float:
        """计算总收益率"""
        start_value = equity_curve.iloc[0]
        end_value = equity_curve.iloc[-1]
        if start_value == 0:
            return 0
        return (end_value - start_value) / start_value
    
    def _calculate_annual_return(
        self,
        equity_curve: pd.Series,
        periods_per_year: int = 252
    ) -> float:
        """计算年化收益率"""
        total_return = self._calculate_total_return(equity_curve)
        n_periods = len(equity_curve)
        years = n_periods / periods_per_year
        
        if years == 0:
            return 0
        
        return (1 + total_return) ** (1 / years) - 1
    
    def _calculate_volatility(
        self,
        returns: pd.Series,
        periods_per_year: int = 252
    ) -> float:
        """计算年化波动率"""
        if len(returns) == 0:
            return 0
        return returns.std() * np.sqrt(periods_per_year)
    
    def _calculate_sharpe_ratio(
        self,
        returns: pd.Series,
        periods_per_year: int = 252
    ) -> float:
        """计算夏普比率"""
        volatility = self._calculate_volatility(returns, periods_per_year)
        if volatility == 0:
            return 0
        
        annual_return = returns.mean() * periods_per_year
        excess_return = annual_return - self.risk_free_rate
        
        return excess_return / volatility
    
    def _calculate_sortino_ratio(
        self,
        returns: pd.Series,
        periods_per_year: int = 252
    ) -> float:
        """计算索提诺比率"""
        if len(returns) == 0:
            return 0
        
        # 下行波动率
        downside_returns = returns[returns < 0]
        if len(downside_returns) == 0:
            return float('inf')
        
        downside_std = downside_returns.std() * np.sqrt(periods_per_year)
        
        if downside_std == 0:
            return 0
        
        annual_return = returns.mean() * periods_per_year
        excess_return = annual_return - self.risk_free_rate
        
        return excess_return / downside_std
    
    def _calculate_drawdown(
        self,
        equity_curve: pd.Series
    ) -> Tuple[float, int]:
        """
        计算最大回撤和持续时间
        
        Returns:
            (最大回撤, 最大回撤持续天数)
        """
        # 计算累计峰值
        peak = equity_curve.expanding().max()
        
        # 计算回撤
        drawdown = (equity_curve - peak) / peak
        
        # 最大回撤（返回负值，与 backtester.py 一致）
        max_dd = drawdown.min()  # 负值
        
        # 最大回撤持续时间
        dd_duration = 0
        max_duration = 0
        in_drawdown = False
        
        for i, dd_val in enumerate(drawdown):
            if dd_val < 0:
                if not in_drawdown:
                    in_drawdown = True
                    dd_duration = 1
                else:
                    dd_duration += 1
                max_duration = max(max_duration, dd_duration)
            else:
                in_drawdown = False
                dd_duration = 0
        
        return max_dd, max_duration
    
    def _calculate_calmar_ratio(
        self,
        annual_return: float,
        max_drawdown: float
    ) -> float:
        """
        计算卡玛比率
        
        注意：max_drawdown 应为负值，此处取绝对值计算
        """
        if max_drawdown == 0:
            return 0
        return annual_return / abs(max_drawdown)
    
    def _calculate_trade_metrics(self, trades: List[Dict]) -> Dict:
        """计算交易指标"""
        if not trades:
            return {
                'win_rate': 0,
                'profit_loss_ratio': 0,
                'avg_holding_days': 0,
                'turnover': 0
            }
        
        # 分离买卖交易
        buys = [t for t in trades if t.get('side') == 'buy']
        sells = [t for t in trades if t.get('side') == 'sell']
        
        # 计算盈亏
        wins = 0
        losses = 0
        total_profit = 0
        total_loss = 0
        
        for trade in sells:
            pnl = trade.get('pnl', 0)
            if pnl > 0:
                wins += 1
                total_profit += pnl
            elif pnl < 0:
                losses += 1
                total_loss += abs(pnl)
        
        total_trades = wins + losses
        win_rate = wins / total_trades if total_trades > 0 else 0
        
        avg_profit = total_profit / wins if wins > 0 else 0
        avg_loss = total_loss / losses if losses > 0 else 1
        profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 0
        
        # 平均持仓天数
        holding_days = []
        for trade in trades:
            if 'holding_days' in trade:
                holding_days.append(trade['holding_days'])
        avg_holding = np.mean(holding_days) if holding_days else 0
        
        return {
            'win_rate': win_rate,
            'profit_loss_ratio': profit_loss_ratio,
            'avg_holding_days': avg_holding,
            'turnover': 0  # 需要资金数据计算
        }
    
    def _calculate_information_ratio(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series
    ) -> float:
        """计算信息比率"""
        excess_returns = returns - benchmark_returns
        tracking_error = excess_returns.std()
        
        if tracking_error == 0:
            return 0
        
        return excess_returns.mean() / tracking_error
    
    def _calculate_tracking_error(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series
    ) -> float:
        """计算跟踪误差"""
        excess_returns = returns - benchmark_returns
        return excess_returns.std()
    
    def _calculate_alpha_beta(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series
    ) -> Tuple[float, float]:
        """计算Alpha和Beta"""
        if len(returns) < 2:
            return 0, 0
        
        # 线性回归
        covariance = np.cov(returns, benchmark_returns)
        
        if covariance[1, 1] == 0:
            return 0, 0
        
        beta = covariance[0, 1] / covariance[1, 1]
        alpha = returns.mean() - beta * benchmark_returns.mean()
        
        # 年化
        alpha_annual = alpha * 252
        beta_annual = beta  # Beta不需要年化
        
        return alpha_annual, beta_annual
    
    def get_metrics_dict(self, metrics: PerformanceMetrics) -> Dict:
        """将指标转换为字典"""
        return {
            'total_return': f"{metrics.total_return:.2%}",
            'annual_return': f"{metrics.annual_return:.2%}",
            'volatility': f"{metrics.volatility:.2%}",
            'sharpe_ratio': f"{metrics.sharpe_ratio:.2f}",
            'sortino_ratio': f"{metrics.sortino_ratio:.2f}",
            'max_drawdown': f"{metrics.max_drawdown:.2%}",
            'max_drawdown_duration': f"{metrics.max_drawdown_duration}天",
            'calmar_ratio': f"{metrics.calmar_ratio:.2f}",
            'win_rate': f"{metrics.win_rate:.2%}",
            'profit_loss_ratio': f"{metrics.profit_loss_ratio:.2f}",
            'avg_holding_days': f"{metrics.avg_holding_days:.1f}天",
            'alpha': f"{metrics.alpha:.2%}",
            'beta': f"{metrics.beta:.2f}",
            'information_ratio': f"{metrics.information_ratio:.2f}",
            'tracking_error': f"{metrics.tracking_error:.2%}"
        }
    
    def compare_strategies(
        self,
        results: Dict[str, pd.Series]
    ) -> pd.DataFrame:
        """
        比较多个策略
        
        Args:
            results: {策略名: 权益曲线}
        
        Returns:
            比较表格
        """
        records = []
        
        for name, equity in results.items():
            metrics = self.analyze(equity)
            records.append({
                '策略': name,
                '总收益': f"{metrics.total_return:.2%}",
                '年化收益': f"{metrics.annual_return:.2%}",
                '波动率': f"{metrics.volatility:.2%}",
                '夏普比率': f"{metrics.sharpe_ratio:.2f}",
                '最大回撤': f"{metrics.max_drawdown:.2%}",
                '卡玛比率': f"{metrics.calmar_ratio:.2f}",
                '胜率': f"{metrics.win_rate:.2%}"
            })
        
        return pd.DataFrame(records)
