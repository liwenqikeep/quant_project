"""
风控引擎
核心风控逻辑，订单校验，风险指标计算
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from quant.utils.logger import logger


class RiskLevel(Enum):
    """风险等级"""
    SAFE = "safe"
    WARNING = "warning"
    DANGER = "danger"
    STOP = "stop"


@dataclass
class RiskConfig:
    """风控配置"""
    # 仓位限制
    max_position_per_stock: float = 0.2  # 单只股票最大仓位比例
    max_position_total: float = 0.9     # 总仓位上限
    min_position_total: float = 0.0      # 总仓位下限（做空时）
    
    # 资金限制
    max_single_trade_ratio: float = 0.1  # 单笔交易最大资金比例
    min_cash_reserve: float = 0.05       # 最小现金储备比例
    
    # 成本参数（与回测器口径一致）
    commission: float = 0.0003         # 佣金费率
    stamp_tax: float = 0.0005           # 印花税率（卖出时收取）
    slippage: float = 0.0               # 滑点
    
    # 风险指标限制
    max_drawdown: float = 0.15          # 最大回撤限制
    max_volatility: float = 0.3         # 最大波动率限制
    max_var: float = 0.05                # 最大Value at Risk（95%置信度，日频）
    
    # 交易限制
    max_trades_per_day: int = 50        # 每日最大交易次数
    max_loss_per_day: float = 0.02      # 每日最大亏损比例
    cooling_period_seconds: int = 5      # 冷却期（秒）
    
    # 杠杆限制
    max_leverage: float = 1.0           # 最大杠杆倍数
    margin_call_level: float = 0.3       # 追保线（保证金比例低于此值时警告）
    forced_liquidation_level: float = 0.2 # 强平线


@dataclass
class RiskStatus:
    """风控状态"""
    risk_level: RiskLevel = RiskLevel.SAFE
    current_drawdown: float = 0.0
    current_volatility: float = 0.0
    daily_pnl: float = 0.0
    daily_trade_count: int = 0
    total_position_ratio: float = 0.0
    cash_reserve_ratio: float = 1.0
    leverage: float = 1.0
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


class RiskEngine:
    """风控引擎"""
    
    def __init__(self, config: Optional[RiskConfig] = None):
        """
        初始化风控引擎
        
        Args:
            config: 风控配置，如为None则使用默认配置
        """
        self.config = config or RiskConfig()
        self.reset()
        logger.info("风控引擎初始化完成")
    
    def reset(self):
        """重置风控状态"""
        self.status = RiskStatus()
        self.trade_history = []
        self.daily_trade_count = 0
        self.last_trade_time = None
        self.peak_value = 0
        self.current_value = 0
        logger.debug("风控状态已重置")
    
    def check_order(
        self,
        symbol: str,
        direction: str,  # "buy" or "sell"
        quantity: int,
        price: float,
        cash: float,
        position_value: float,
        total_value: float
    ) -> Tuple[bool, str, RiskLevel]:
        """
        检查订单是否可以通过风控
        
        Args:
            symbol: 股票代码
            direction: 交易方向
            quantity: 交易数量
            price: 交易价格
            cash: 当前可用资金
            position_value: 当前持仓市值
            total_value: 总资产
        
        Returns:
            (可以通过, 拒绝原因, 当前风险等级)
        """
        violations = []
        warnings = []
        
        # 1. 冷却期检查
        if self._check_cooling_period():
            violations.append(f"冷却期内，禁止交易")
        
        # 2. 每日交易次数限制
        if self.daily_trade_count >= self.config.max_trades_per_day:
            violations.append(f"已达到每日最大交易次数限制({self.config.max_trades_per_day})")
        
        # 3. 单笔交易金额限制
        trade_value = quantity * price
        if trade_value > total_value * self.config.max_single_trade_ratio:
            violations.append(
                f"单笔交易金额({trade_value:.2f})超过限制("
                f"{total_value * self.config.max_single_trade_ratio:.2f})"
            )
        
        # 4. 资金检查
        if direction == "buy":
            # A股买入不收印花税，只计佣金（与回测器口径一致）
            required_cash = trade_value * (1 + self.config.commission)
            if required_cash > cash:
                violations.append(f"资金不足: 需要{required_cash:.2f}, 可用{cash:.2f}")
            
            # 现金储备检查
            remaining_cash = cash - required_cash
            min_reserve = total_value * self.config.min_cash_reserve
            if remaining_cash < min_reserve:
                warnings.append(f"现金储备低于最低要求")
        
        # 5. 仓位检查
        if direction == "buy":
            new_position_value = position_value + trade_value
            new_position_ratio = new_position_value / total_value
            if new_position_ratio > self.config.max_position_total:
                violations.append(
                    f"总仓位比例({new_position_ratio:.2%})超过限制("
                    f"{self.config.max_position_total:.2%})"
                )
            if trade_value / total_value > self.config.max_position_per_stock:
                violations.append(
                    f"单只股票仓位({trade_value/total_value:.2%})超过限制("
                    f"{self.config.max_position_per_stock:.2%})"
                )
        
        # 6. 回撤检查
        if self.status.current_drawdown < -self.config.max_drawdown:
            violations.append(
                f"当前回撤({self.status.current_drawdown:.2%})超过限制("
                f"{-self.config.max_drawdown:.2%})"
            )
        elif self.status.current_drawdown < -self.config.max_drawdown * 0.8:
            warnings.append(f"回撤接近限制，请注意风险")
        
        # 7. 每日亏损检查
        if self.status.daily_pnl < -total_value * self.config.max_loss_per_day:
            violations.append(
                f"今日亏损({self.status.daily_pnl:.2f})超过限制("
                f"{-total_value * self.config.max_loss_per_day:.2f})"
            )
        
        # 8. 杠杆检查
        if self.status.leverage > self.config.max_leverage:
            violations.append(
                f"当前杠杆({self.status.leverage:.2f}x)超过限制("
                f"{self.config.max_leverage:.2f}x)"
            )
        
        # 确定风险等级
        if violations:
            risk_level = RiskLevel.STOP
        elif warnings:
            risk_level = RiskLevel.WARNING
        elif self.status.current_drawdown < -self.config.max_drawdown * 0.5:
            risk_level = RiskLevel.DANGER
        else:
            risk_level = RiskLevel.SAFE
        
        # 记录检查结果
        self.status.violations = violations
        self.status.warnings = warnings
        self.status.risk_level = risk_level
        
        can_pass = len(violations) == 0
        reason = "; ".join(violations) if violations else "; ".join(warnings) if warnings else "通过"
        
        if not can_pass:
            logger.warning(f"订单被风控拦截: {reason}")
        elif warnings:
            logger.info(f"订单风控警告: {reason}")
        
        return can_pass, reason, risk_level
    
    def _check_cooling_period(self) -> bool:
        """检查是否在冷却期内"""
        if self.last_trade_time is None:
            return False
        elapsed = (datetime.now() - self.last_trade_time).total_seconds()
        return elapsed < self.config.cooling_period_seconds
    
    def update_trade(self, trade_info: Dict):
        """
        更新交易记录
        
        Args:
            trade_info: 交易信息字典
        """
        self.trade_history.append(trade_info)
        self.daily_trade_count += 1
        self.last_trade_time = datetime.now()
        
        # 更新每日盈亏
        if "pnl" in trade_info:
            self.status.daily_pnl += trade_info["pnl"]
        
        logger.debug(f"交易记录已更新: {trade_info.get('symbol')}, "
                    f"当日交易次数: {self.daily_trade_count}")
    
    def update_position(
        self,
        cash: float,
        position_value: float,
        total_value: float
    ):
        """
        更新持仓状态
        
        Args:
            cash: 可用资金
            position_value: 持仓市值
            total_value: 总资产
        """
        self.current_value = total_value
        
        # 更新峰值
        if total_value > self.peak_value:
            self.peak_value = total_value
        
        # 计算回撤
        if self.peak_value > 0:
            self.status.current_drawdown = (total_value - self.peak_value) / self.peak_value
        
        # 计算仓位比例
        self.status.total_position_ratio = position_value / total_value if total_value > 0 else 0
        
        # 计算现金储备比例
        self.status.cash_reserve_ratio = cash / total_value if total_value > 0 else 1
        
        # 计算杠杆
        self.status.leverage = (position_value + cash) / total_value if total_value > 0 else 1
        
        # 更新波动率
        self._update_volatility()
        
        logger.debug(
            f"持仓状态更新: 仓位={self.status.total_position_ratio:.2%}, "
            f"回撤={self.status.current_drawdown:.2%}, "
            f"杠杆={self.status.leverage:.2f}x"
        )
    
    def _update_volatility(self):
        """更新波动率计算"""
        if len(self.trade_history) >= 20:
            returns = []
            for i in range(1, min(20, len(self.trade_history))):
                if "daily_return" in self.trade_history[-i]:
                    returns.append(self.trade_history[-i]["daily_return"])
            if returns:
                self.status.current_volatility = np.std(returns) * np.sqrt(252)
    
    def calculate_var(
        self,
        returns: pd.Series,
        confidence: float = 0.95
    ) -> float:
        """
        计算Value at Risk
        
        Args:
            returns: 收益率序列
            confidence: 置信度
        
        Returns:
            VaR值（负数表示损失）
        """
        if len(returns) < 30:
            return -self.config.max_var
        
        var = np.percentile(returns, (1 - confidence) * 100)
        return var
    
    def get_risk_report(self) -> Dict:
        """
        获取风控报告
        
        Returns:
            风控状态字典
        """
        return {
            "risk_level": self.status.risk_level.value,
            "current_drawdown": self.status.current_drawdown,
            "current_volatility": self.status.current_volatility,
            "daily_pnl": self.status.daily_pnl,
            "daily_trade_count": self.status.daily_trade_count,
            "total_position_ratio": self.status.total_position_ratio,
            "cash_reserve_ratio": self.status.cash_reserve_ratio,
            "leverage": self.status.leverage,
            "violations": self.status.violations,
            "warnings": self.status.warnings,
            "peak_value": self.peak_value,
            "current_value": self.current_value,
            "timestamp": self.status.timestamp.isoformat()
        }
    
    def reset_daily(self):
        """重置每日计数"""
        self.daily_trade_count = 0
        self.status.daily_pnl = 0
        self.status.warnings = []
        logger.info("每日风控计数已重置")
