"""
再平衡模块
定期再平衡、阈值再平衡、渐进式再平衡
"""
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from quant.utils.logger import logger


class RebalanceTrigger(Enum):
    """再平衡触发方式"""
    PERIODIC = "periodic"           # 定期
    THRESHOLD = "threshold"         # 阈值触发
    HYBRID = "hybrid"             # 混合


@dataclass
class RebalanceConfig:
    """再平衡配置"""
    trigger: RebalanceTrigger = RebalanceTrigger.PERIODIC
    
    # 定期配置
    rebalance_interval_days: int = 20  # 再平衡周期（天）
    
    # 阈值配置
    drift_threshold: float = 0.05     # 漂移阈值
    min_drift_to_rebalance: float = 0.02  # 最小漂移再平衡阈值
    
    # 执行配置
    max_turnover_per_rebalance: float = 0.3  # 单次最大换手率
    allow_partial_rebalance: bool = True  # 允许部分再平衡
    
    # 成本控制
    transaction_cost_rate: float = 0.001  # 交易成本率
    min_rebalance_cost: float = 100     # 最小再平衡成本（低于此值不执行）


@dataclass
class RebalanceTrade:
    """再平衡交易"""
    symbol: str
    action: str  # "buy" or "sell"
    current_weight: float
    target_weight: float
    weight_diff: float
    estimated_cost: float


@dataclass
class RebalancePlan:
    """再平衡计划"""
    timestamp: datetime
    target_weights: Dict[str, float]
    trades: List[RebalanceTrade]
    total_turnover: float
    estimated_cost: float
    reason: str


class Rebalancer:
    """再平衡器"""
    
    def __init__(self, config: Optional[RebalanceConfig] = None):
        """
        初始化再平衡器
        
        Args:
            config: 再平衡配置
        """
        self.config = config or RebalanceConfig()
        self.last_rebalance_date: Optional[datetime] = None
        self.current_weights: Dict[str, float] = {}
        self.target_weights: Dict[str, float] = {}
        
        logger.info(f"再平衡器初始化: 触发方式={self.config.trigger.value}")
    
    def set_target_weights(self, weights: Dict[str, float]):
        """设置目标权重"""
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            # 归一化
            self.target_weights = {k: v / total for k, v in weights.items()}
        else:
            self.target_weights = weights
        
        logger.info(f"目标权重已设置: {len(self.target_weights)} 个标的")
    
    def update_current_weights(self, weights: Dict[str, float]):
        """更新当前权重"""
        self.current_weights = weights
    
    def check_rebalance_needed(self) -> tuple:
        """
        检查是否需要再平衡
        
        Returns:
            (是否需要, 原因)
        """
        if not self.target_weights:
            return False, "未设置目标权重"
        
        if not self.current_weights:
            return True, "首次调仓"
        
        # 计算漂移
        max_drift = self._calculate_max_drift()
        total_drift = self._calculate_total_drift()
        
        # 检查是否触发再平衡
        if self.config.trigger == RebalanceTrigger.PERIODIC:
            if self._check_periodic_trigger():
                return True, f"定期再平衡 (间隔{self._get_days_since_rebalance()}天)"
            return False, "未到再平衡周期"
        
        elif self.config.trigger == RebalanceTrigger.THRESHOLD:
            if max_drift > self.config.drift_threshold:
                return True, f"触发阈值再平衡 (最大漂移={max_drift:.2%})"
            return False, f"漂移未超阈值 ({max_drift:.2%} < {self.config.drift_threshold:.2%})"
        
        else:  # HYBRID
            if self._check_periodic_trigger() and max_drift > self.config.min_drift_to_rebalance:
                return True, f"混合再平衡 (周期+漂移={max_drift:.2%})"
            elif max_drift > self.config.drift_threshold:
                return True, f"漂移触发再平衡 (最大漂移={max_drift:.2%})"
            return False, "未触发再平衡"
    
    def _check_periodic_trigger(self) -> bool:
        """检查定期触发条件"""
        if self.last_rebalance_date is None:
            return True
        
        days_since = self._get_days_since_rebalance()
        return days_since >= self.config.rebalance_interval_days
    
    def _get_days_since_rebalance(self) -> int:
        """获取距上次再平衡的天数"""
        if self.last_rebalance_date is None:
            return 999
        return (datetime.now() - self.last_rebalance_date).days
    
    def _calculate_max_drift(self) -> float:
        """计算最大漂移"""
        max_drift = 0
        
        for symbol, target_w in self.target_weights.items():
            current_w = self.current_weights.get(symbol, 0)
            drift = abs(current_w - target_w)
            max_drift = max(max_drift, drift)
        
        return max_drift
    
    def _calculate_total_drift(self) -> float:
        """计算总漂移"""
        total_drift = 0
        
        for symbol, target_w in self.target_weights.items():
            current_w = self.current_weights.get(symbol, 0)
            total_drift += abs(current_w - target_w)
        
        # 考虑新增和移除的标的
        current_symbols = set(self.current_weights.keys())
        target_symbols = set(self.target_weights.keys())
        
        for sym in target_symbols - current_symbols:
            total_drift += self.target_weights[sym]
        
        for sym in current_symbols - target_symbols:
            total_drift += self.current_weights[sym]
        
        return total_drift / 2
    
    def generate_rebalance_plan(
        self,
        total_value: float
    ) -> Optional[RebalancePlan]:
        """
        生成再平衡计划
        
        Args:
            total_value: 总资产
        
        Returns:
            再平衡计划
        """
        needs_rebalance, reason = self.check_rebalance_needed()
        
        if not needs_rebalance:
            return None
        
        logger.info(f"生成再平衡计划: {reason}")
        
        # 计算目标市值
        target_values = {
            sym: total_value * weight
            for sym, weight in self.target_weights.items()
        }
        
        # 合并当前持仓
        all_symbols = set(self.current_weights.keys()) | set(self.target_weights.keys())
        
        trades = []
        total_turnover = 0
        estimated_cost = 0
        
        for symbol in all_symbols:
            current_w = self.current_weights.get(symbol, 0)
            target_w = self.target_weights.get(symbol, 0)
            
            if abs(current_w - target_w) < 0.001:
                continue
            
            current_value = total_value * current_w
            target_value = total_value * target_w
            value_diff = target_value - current_value
            
            # 估算交易成本
            cost = abs(value_diff) * self.config.transaction_cost_rate
            cost = max(cost, self.config.min_rebalance_cost * 0.001)  # 按资产比例估算
            
            trade = RebalanceTrade(
                symbol=symbol,
                action="buy" if value_diff > 0 else "sell",
                current_weight=current_w,
                target_weight=target_w,
                weight_diff=target_w - current_w,
                estimated_cost=cost
            )
            
            trades.append(trade)
            total_turnover += abs(value_diff) / total_value
            estimated_cost += cost
        
        # 检查换手率限制
        if total_turnover > self.config.max_turnover_per_rebalance:
            if self.config.allow_partial_rebalance:
                # 渐进式再平衡
                trades = self._partial_rebalance(trades, total_turnover, self.config.max_turnover_per_rebalance)
                total_turnover = sum(abs(t.weight_diff) for t in trades)
                logger.warning(f"换手率超限，采用部分再平衡: {total_turnover:.2%}")
            else:
                logger.warning(f"换手率超限，取消再平衡: {total_turnover:.2%}")
                return None
        
        # 估算成本检查
        if estimated_cost > total_value * 0.01:
            logger.warning(f"再平衡成本过高: {estimated_cost:,.2f} ({estimated_cost/total_value:.2%})")
        
        return RebalancePlan(
            timestamp=datetime.now(),
            target_weights=self.target_weights.copy(),
            trades=trades,
            total_turnover=total_turnover,
            estimated_cost=estimated_cost,
            reason=reason
        )
    
    def _partial_rebalance(
        self,
        trades: List[RebalanceTrade],
        total_turnover: float,
        max_turnover: float
    ) -> List[RebalanceTrade]:
        """部分再平衡"""
        scale = max_turnover / total_turnover
        
        adjusted_trades = []
        for trade in trades:
            new_diff = trade.weight_diff * scale
            
            # 重新计算目标权重（简化处理）
            adjusted_trade = RebalanceTrade(
                symbol=trade.symbol,
                action=trade.action,
                current_weight=trade.current_weight,
                target_weight=trade.current_weight + new_diff,
                weight_diff=new_diff,
                estimated_cost=trade.estimated_cost * scale
            )
            adjusted_trades.append(adjusted_trade)
        
        return adjusted_trades
    
    def execute_rebalance(self, plan: RebalancePlan):
        """执行再平衡计划"""
        logger.info(
            f"执行再平衡: {len(plan.trades)} 笔交易, "
            f"换手率={plan.total_turnover:.2%}, "
            f"成本={plan.estimated_cost:,.2f}"
        )
        
        # 更新权重
        for trade in plan.trades:
            self.current_weights[trade.symbol] = trade.target_weight
        
        # 更新再平衡时间
        self.last_rebalance_date = datetime.now()
        
        logger.info("再平衡执行完成")
    
    def get_rebalance_recommendations(self) -> List[Dict]:
        """获取再平衡建议"""
        needs, reason = self.check_rebalance_needed()
        
        if not needs:
            return []
        
        recommendations = []
        for symbol, target_w in self.target_weights.items():
            current_w = self.current_weights.get(symbol, 0)
            drift = target_w - current_w
            
            if abs(drift) > 0.001:
                recommendations.append({
                    "symbol": symbol,
                    "action": "buy" if drift > 0 else "sell",
                    "current_weight": current_w,
                    "target_weight": target_w,
                    "drift": drift,
                    "drift_pct": abs(drift) / max(current_w, 0.001)
                })
        
        return sorted(recommendations, key=lambda x: abs(x['drift']), reverse=True)
