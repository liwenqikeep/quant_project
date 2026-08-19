"""
相关性跟踪模块
跟踪资产相关性、动态调整组合
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from quant.utils.logger import logger


@dataclass
class CorrelationSnapshot:
    """相关性快照"""
    timestamp: datetime
    correlations: Dict[Tuple[str, str], float]  # (sym1, sym2) -> correlation
    avg_correlation: float                     # 平均相关性
    high_correlation_pairs: List[Tuple[str, str, float]]  # 高相关对


class CorrelationTracker:
    """相关性跟踪器"""
    
    def __init__(
        self,
        lookback_days: int = 60,
        high_correlation_threshold: float = 0.7,
        window_size: int = 20
    ):
        """
        初始化相关性跟踪器
        
        Args:
            lookback_days: 回溯天数
            high_correlation_threshold: 高相关性阈值
            window_size: 计算窗口大小
        """
        self.lookback_days = lookback_days
        self.high_threshold = high_correlation_threshold
        self.window_size = window_size
        
        self.correlation_history: List[CorrelationSnapshot] = []
        self.current_prices: Dict[str, pd.Series] = {}
        self.last_update: Optional[datetime] = None
        
        logger.info(
            f"相关性跟踪器初始化: 回溯={lookback_days}天, "
            f"阈值={high_correlation_threshold}"
        )
    
    def update_prices(self, prices: pd.DataFrame):
        """
        更新价格数据
        
        Args:
            prices: 价格DataFrame，列为股票代码，行为日期
        """
        for symbol in prices.columns:
            self.current_prices[symbol] = prices[symbol]
        
        self.last_update = datetime.now()
    
    def update_price(self, symbol: str, prices: pd.Series):
        """更新单个标的价格"""
        self.current_prices[symbol] = prices
    
    def calculate_correlations(self) -> Dict[Tuple[str, str], float]:
        """
        计算当前相关性矩阵
        
        Returns:
            相关性字典
        """
        if len(self.current_prices) < 2:
            return {}
        
        # 构建DataFrame
        price_df = pd.DataFrame(self.current_prices)
        
        # 计算收益率
        returns = price_df.pct_change().dropna()
        
        # 取最近N天
        if len(returns) > self.lookback_days:
            returns = returns.iloc[-self.lookback_days:]
        
        if len(returns) < 10:
            logger.warning("数据不足，无法计算相关性")
            return {}
        
        # 计算相关矩阵
        corr_matrix = returns.corr()
        
        # 转换为字典
        correlations = {}
        symbols = corr_matrix.columns.tolist()
        
        for i, sym1 in enumerate(symbols):
            for j, sym2 in enumerate(symbols):
                if i < j:  # 只存储上三角
                    corr = corr_matrix.loc[sym1, sym2]
                    if not np.isnan(corr):
                        correlations[(sym1, sym2)] = corr
        
        return correlations
    
    def calculate_rolling_correlation(
        self,
        symbol1: str,
        symbol2: str,
        window: Optional[int] = None
    ) -> pd.Series:
        """
        计算滚动相关性
        
        Args:
            symbol1: 标的1
            symbol2: 标的2
            window: 窗口大小
        
        Returns:
            滚动相关性序列
        """
        window = window or self.window_size
        
        if symbol1 not in self.current_prices or symbol2 not in self.current_prices:
            return pd.Series()
        
        prices1 = self.current_prices[symbol1]
        prices2 = self.current_prices[symbol2]
        
        returns1 = prices1.pct_change().dropna()
        returns2 = prices2.pct_change().dropna()
        
        # 对齐数据
        aligned = pd.DataFrame({'r1': returns1, 'r2': returns2}).dropna()
        
        if len(aligned) < window:
            return pd.Series()
        
        # 计算滚动相关性
        rolling_corr = aligned['r1'].rolling(window).corr(aligned['r2'])
        
        return rolling_corr
    
    def get_high_correlation_pairs(
        self,
        n: int = 10
    ) -> List[Tuple[str, str, float]]:
        """
        获取高相关性标的对
        
        Args:
            n: 返回数量
        
        Returns:
            [(sym1, sym2, correlation), ...]
        """
        correlations = self.calculate_correlations()
        
        if not correlations:
            return []
        
        # 排序
        sorted_pairs = sorted(
            correlations.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )
        
        return [(pair[0], pair[1], corr) for pair, corr in sorted_pairs[:n]]
    
    def get_low_correlation_pairs(
        self,
        n: int = 10
    ) -> List[Tuple[str, str, float]]:
        """
        获取低相关性标的对
        
        Returns:
            [(sym1, sym2, correlation), ...]
        """
        correlations = self.calculate_correlations()
        
        if not correlations:
            return []
        
        # 按相关性绝对值排序（从低到高）
        sorted_pairs = sorted(
            correlations.items(),
            key=lambda x: abs(x[1])
        )
        
        return [(pair[0], pair[1], corr) for pair, corr in sorted_pairs[:n]]
    
    def calculate_average_correlation(self) -> float:
        """计算平均相关性"""
        correlations = self.calculate_correlations()
        
        if not correlations:
            return 0
        
        return sum(correlations.values()) / len(correlations)
    
    def detect_correlation_change(
        self,
        symbol1: str,
        symbol2: str,
        threshold: float = 0.2
    ) -> Optional[Dict]:
        """
        检测相关性变化
        
        Args:
            symbol1: 标的1
            symbol2: 标的2
            threshold: 变化阈值
        
        Returns:
            变化信息
        """
        # 获取历史快照
        recent_snapshots = [
            s for s in self.correlation_history[-10:]
            if (symbol1, symbol2) in s.correlations
        ]
        
        if len(recent_snapshots) < 2:
            return None
        
        old_corr = recent_snapshots[0].correlations.get((symbol1, symbol2), 0)
        new_corr = recent_snapshots[-1].correlations.get((symbol1, symbol2), 0)
        
        change = new_corr - old_corr
        
        if abs(change) > threshold:
            return {
                "symbol1": symbol1,
                "symbol2": symbol2,
                "old_correlation": old_corr,
                "new_correlation": new_corr,
                "change": change,
                "change_direction": "increase" if change > 0 else "decrease"
            }
        
        return None
    
    def record_snapshot(self):
        """记录相关性快照"""
        correlations = self.calculate_correlations()
        avg_corr = self.calculate_average_correlation()
        
        # 获取高相关对
        high_pairs = self.get_high_correlation_pairs(n=5)
        
        snapshot = CorrelationSnapshot(
            timestamp=datetime.now(),
            correlations=correlations,
            avg_correlation=avg_corr,
            high_correlation_pairs=high_pairs
        )
        
        self.correlation_history.append(snapshot)
        
        # 限制历史长度
        if len(self.correlation_history) > 1000:
            self.correlation_history = self.correlation_history[-500:]
        
        return snapshot
    
    def get_correlation_matrix(self) -> pd.DataFrame:
        """获取相关性矩阵"""
        if len(self.current_prices) < 2:
            return pd.DataFrame()
        
        price_df = pd.DataFrame(self.current_prices)
        returns = price_df.pct_change().dropna()
        
        if len(returns) > self.lookback_days:
            returns = returns.iloc[-self.lookback_days:]
        
        return returns.corr()
    
    def get_correlation_report(self) -> Dict:
        """获取相关性报告"""
        correlations = self.calculate_correlations()
        avg_corr = self.calculate_average_correlation()
        high_pairs = self.get_high_correlation_pairs()
        low_pairs = self.get_low_correlation_pairs()
        
        return {
            "timestamp": datetime.now(),
            "avg_correlation": avg_corr,
            "correlation_count": len(correlations),
            "high_threshold": self.high_threshold,
            "high_correlation_pairs": [
                {"pair": list(p), "correlation": c}
                for p, c in high_pairs
            ],
            "low_correlation_pairs": [
                {"pair": list(p), "correlation": c}
                for p, c in low_pairs
            ],
            "correlation_matrix": self.get_correlation_matrix().to_dict()
        }
    
    def get_diversification_benefit(self) -> float:
        """
        估算分散化收益
        
        Returns:
            分散化收益（组合波动率降低百分比）
        """
        if len(self.current_prices) < 2:
            return 0
        
        price_df = pd.DataFrame(self.current_prices)
        returns = price_df.pct_change().dropna().iloc[-self.lookback_days:]
        
        # 等权组合的波动率
        equal_weights = np.ones(len(returns.columns)) / len(returns.columns)
        portfolio_vol = np.sqrt(
            equal_weights @ returns.cov().values @ equal_weights
        ) * np.sqrt(252)
        
        # 平均波动率
        avg_vol = returns.std().mean() * np.sqrt(252)
        
        if avg_vol == 0:
            return 0
        
        # 分散化收益
        benefit = (avg_vol - portfolio_vol) / avg_vol
        
        return max(0, benefit)
    
    def suggest_rebalancing(
        self,
        current_weights: Dict[str, float],
        correlation_threshold: float = 0.7
    ) -> List[Dict]:
        """
        基于相关性建议再平衡
        
        Args:
            current_weights: 当前权重
            correlation_threshold: 相关性阈值
        
        Returns:
            建议列表
        """
        suggestions = []
        
        high_pairs = self.get_high_correlation_pairs(n=20)
        
        for sym1, sym2, corr in high_pairs:
            if abs(corr) > correlation_threshold:
                w1 = current_weights.get(sym1, 0)
                w2 = current_weights.get(sym2, 0)
                
                # 如果两个高相关标的权重都较高，建议降低一个
                if w1 > 0.1 and w2 > 0.1:
                    suggestions.append({
                        "type": "high_correlation",
                        "symbols": [sym1, sym2],
                        "correlation": corr,
                        "weights": [w1, w2],
                        "suggestion": f"降低{sim2 if w1 > w2 else sym1}的权重以降低风险",
                        "priority": "high" if abs(corr) > 0.8 else "medium"
                    })
        
        return suggestions
