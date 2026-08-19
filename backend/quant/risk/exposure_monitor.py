"""
敞口监控模块
市场敞口、行业敞口、风格敞口、流动性风险监控
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from quant.utils.logger import logger


@dataclass
class ExposureConfig:
    """敞口监控配置"""
    # 风险敞口限制
    max_market_exposure: float = 1.0      # 最大市场敞口（多头1.0，空头-1.0）
    max_beta_exposure: float = 2.0        # 最大Beta敞口
    max_volatility_exposure: float = 0.5  # 最大波动率敞口
    
    # 行业敞口限制
    max_single_industry: float = 0.3       # 单行业最大敞口
    max_industry_concentration: float = 0.6 # 行业集中度（Top3占比）
    
    # 风格敞口限制
    style_factors: List[str] = field(
        default_factory=lambda: ["size", "value", "momentum", "quality", "low_vol"]
    )
    max_style_exposure: float = 1.5        # 单风格因子最大敞口
    
    # 流动性限制
    min_avg_volume: float = 1000000        # 最小日均成交量
    max_position_days_holding: int = 20    # 最大持仓天数（用于流动性检查）
    
    # 相关性限制
    max_position_correlation: float = 0.7   # 持仓间最大相关性
    max_beta_with_index: float = 1.5       # 与指数最大Beta


@dataclass
class ExposureSnapshot:
    """敞口快照"""
    timestamp: datetime
    market_exposure: float          # 市场净敞口（多头-空头）
    beta_exposure: float           # Beta敞口
    volatility_exposure: float      # 波动率敞口
    industry_exposure: Dict[str, float]  # 行业敞口
    style_exposure: Dict[str, float]    # 风格敞口
    position_count: int            # 持仓数量
    concentration: float           # 集中度（HHI）
    liquidity_score: float         # 流动性评分


class ExposureMonitor:
    """敞口监控器"""
    
    def __init__(self, config: Optional[ExposureConfig] = None):
        """
        初始化敞口监控器
        
        Args:
            config: 敞口监控配置
        """
        self.config = config or ExposureConfig()
        
        # 持仓信息
        self.positions: Dict[str, Dict] = {}
        self.total_value = 0
        
        # 历史快照
        self.history: List[ExposureSnapshot] = []
        
        # 因子暴露度（需要外部数据或模型估计）
        self.factor_betas: Dict[str, Dict[str, float]] = {}  # symbol -> {factor: beta}
        
        logger.info("敞口监控器初始化完成")
    
    def update_position(
        self,
        symbol: str,
        position_value: float,
        shares: int = 0,
        avg_price: float = 0,
        beta: float = 1.0,
        industry: str = "其他",
        style_scores: Optional[Dict[str, float]] = None,
        daily_volume: float = 0,
        **kwargs
    ):
        """
        更新持仓信息
        
        Args:
            symbol: 股票代码
            position_value: 持仓市值
            shares: 持仓股数
            avg_price: 平均成本
            beta: Beta值
            industry: 行业
            style_scores: 风格因子得分
            daily_volume: 日成交量
        """
        self.positions[symbol] = {
            "position_value": position_value,
            "shares": shares,
            "avg_price": avg_price,
            "beta": beta,
            "industry": industry,
            "style_scores": style_scores or {},
            "daily_volume": daily_volume,
            "entry_date": kwargs.get("entry_date", datetime.now())
        }
        
        # 更新因子Beta缓存
        if symbol not in self.factor_betas:
            self.factor_betas[symbol] = self._estimate_factor_betas(symbol, beta, style_scores)
        
        logger.debug(f"持仓更新: {symbol} = {position_value:,.2f}")
    
    def remove_position(self, symbol: str):
        """移除持仓"""
        if symbol in self.positions:
            del self.positions[symbol]
            logger.debug(f"持仓移除: {symbol}")
    
    def _estimate_factor_betas(
        self,
        symbol: str,
        market_beta: float,
        style_scores: Optional[Dict[str, float]] = None
    ) -> Dict[str, float]:
        """
        估算因子Beta（简化版，实际需要回归分析）
        
        Args:
            symbol: 股票代码
            market_beta: 市场Beta
            style_scores: 风格得分
        
        Returns:
            各因子Beta字典
        """
        # 简化估计：基于市值和风格打分估算因子暴露
        style_scores = style_scores or {}
        
        # 基于规模因子：市值越大，规模Beta越高
        size_beta = min(1.0, max(-1.0, (style_scores.get("size", 0) - 0.5) * 2))
        
        # 基于价值因子
        value_beta = min(1.0, max(-1.0, (style_scores.get("value", 0) - 0.5) * 2))
        
        # 基于动量因子
        momentum_beta = min(1.0, max(-1.0, (style_scores.get("momentum", 0) - 0.5) * 2))
        
        # 基于质量因子
        quality_beta = min(1.0, max(-1.0, (style_scores.get("quality", 0) - 0.5) * 2))
        
        # 基于低波因子
        low_vol_beta = min(1.0, max(-1.0, (style_scores.get("low_vol", 0) - 0.5) * 2))
        
        return {
            "market": market_beta,
            "size": size_beta,
            "value": value_beta,
            "momentum": momentum_beta,
            "quality": quality_beta,
            "low_vol": low_vol_beta
        }
    
    def set_total_value(self, total_value: float):
        """设置总资产"""
        self.total_value = total_value
    
    def calculate_exposures(self) -> ExposureSnapshot:
        """
        计算当前敞口
        
        Returns:
            敞口快照
        """
        if self.total_value == 0:
            logger.warning("总资产为0，无法计算敞口")
            return None
        
        # 计算各维度敞口
        industry_exposure = defaultdict(float)
        style_exposure = defaultdict(float)
        
        market_exposure = 0
        beta_exposure = 0
        volatility_exposure = 0
        
        for symbol, pos in self.positions.items():
            weight = pos["position_value"] / self.total_value
            
            # 市场敞口
            market_exposure += weight
            
            # Beta敞口
            beta_exposure += weight * pos["beta"]
            
            # 波动率敞口（简化：用beta平方代替）
            volatility_exposure += weight * (pos["beta"] ** 2)
            
            # 行业敞口
            industry_exposure[pos["industry"]] += weight
            
            # 风格敞口
            factor_betas = self.factor_betas.get(symbol, {})
            for factor, beta in factor_betas.items():
                style_exposure[factor] += weight * beta
        
        # 计算集中度（HHI指数）
        all_weights = [p["position_value"] / self.total_value for p in self.positions.values()]
        concentration = sum(w ** 2 for w in all_weights) if all_weights else 0
        
        # 计算流动性评分
        liquidity_score = self._calculate_liquidity_score()
        
        snapshot = ExposureSnapshot(
            timestamp=datetime.now(),
            market_exposure=market_exposure,
            beta_exposure=beta_exposure,
            volatility_exposure=volatility_exposure,
            industry_exposure=dict(industry_exposure),
            style_exposure=dict(style_exposure),
            position_count=len(self.positions),
            concentration=concentration,
            liquidity_score=liquidity_score
        )
        
        self.history.append(snapshot)
        
        return snapshot
    
    def _calculate_liquidity_score(self) -> float:
        """
        计算流动性评分
        
        Returns:
            流动性评分 (0-1，越高越好)
        """
        if not self.positions:
            return 1.0
        
        liquidity_scores = []
        for symbol, pos in self.positions.items():
            if pos["daily_volume"] > 0:
                # 计算持仓需要多少天卖出
                days_to_exit = pos["shares"] / (pos["daily_volume"] / pos.get("avg_price", 1))
                # 评分：需要天数越少，评分越高
                score = min(1.0, 5.0 / max(days_to_exit, 1))
                liquidity_scores.append(score)
        
        return np.mean(liquidity_scores) if liquidity_scores else 1.0
    
    def check_exposure_limits(self) -> Tuple[bool, List[str]]:
        """
        检查敞口是否超限
        
        Returns:
            (是否合规, 违规原因列表)
        """
        snapshot = self.calculate_exposures()
        violations = []
        
        # 1. 市场敞口检查
        if abs(snapshot.market_exposure) > self.config.max_market_exposure:
            violations.append(
                f"市场敞口超限: {snapshot.market_exposure:.2%} "
                f"(限制: ±{self.config.max_market_exposure:.2%})"
            )
        
        # 2. Beta敞口检查
        if abs(snapshot.beta_exposure) > self.config.max_beta_exposure:
            violations.append(
                f"Beta敞口超限: {snapshot.beta_exposure:.2f} "
                f"(限制: ±{self.config.max_beta_exposure:.2f})"
            )
        
        # 3. 波动率敞口检查
        if snapshot.volatility_exposure > self.config.max_volatility_exposure:
            violations.append(
                f"波动率敞口超限: {snapshot.volatility_exposure:.2%} "
                f"(限制: {self.config.max_volatility_exposure:.2%})"
            )
        
        # 4. 行业敞口检查
        for industry, exposure in snapshot.industry_exposure.items():
            if exposure > self.config.max_single_industry:
                violations.append(
                    f"行业敞口超限[{industry}]: {exposure:.2%} "
                    f"(限制: {self.config.max_single_industry:.2%})"
                )
        
        # 5. 行业集中度检查
        top_industries = sorted(
            snapshot.industry_exposure.values(),
            reverse=True
        )[:3]
        if top_industries:
            concentration = sum(top_industries)
            if concentration > self.config.max_industry_concentration:
                violations.append(
                    f"行业集中度超限: {concentration:.2%} "
                    f"(限制: {self.config.max_industry_concentration:.2%})"
                )
        
        # 6. 风格因子敞口检查
        for factor, exposure in snapshot.style_exposure.items():
            if abs(exposure) > self.config.max_style_exposure:
                violations.append(
                    f"风格因子敞口超限[{factor}]: {exposure:.2f} "
                    f"(限制: ±{self.config.max_style_exposure:.2f})"
                )
        
        # 7. 流动性检查
        if snapshot.liquidity_score < 0.3:
            violations.append(
                f"流动性风险警告: 评分={snapshot.liquidity_score:.2f} (低于0.3)"
            )
        
        # 8. 与指数Beta检查
        if abs(snapshot.beta_exposure) > self.config.max_beta_with_index:
            violations.append(
                f"指数Beta超限: {snapshot.beta_exposure:.2f} "
                f"(限制: ±{self.config.max_beta_with_index:.2f})"
            )
        
        is_compliant = len(violations) == 0
        
        if not is_compliant:
            for v in violations:
                logger.warning(f"敞口违规: {v}")
        
        return is_compliant, violations
    
    def get_rebalance_suggestions(self) -> List[Dict]:
        """
        获取再平衡建议
        
        Returns:
            调整建议列表
        """
        suggestions = []
        snapshot = self.calculate_exposures()
        
        # 行业再平衡建议
        for industry, exposure in snapshot.industry_exposure.items():
            if exposure > self.config.max_single_industry:
                excess = exposure - self.config.max_single_industry
                suggestions.append({
                    "type": "reduce_industry",
                    "industry": industry,
                    "excess_ratio": excess,
                    "action": "sell",
                    "priority": "high"
                })
        
        # Beta调整建议
        if abs(snapshot.beta_exposure) > self.config.max_beta_exposure * 0.8:
            direction = "reduce" if snapshot.beta_exposure > 0 else "increase"
            suggestions.append({
                "type": "adjust_beta",
                "current_beta": snapshot.beta_exposure,
                "action": direction,
                "priority": "medium"
            })
        
        return suggestions
    
    def get_exposure_report(self) -> Dict:
        """获取完整敞口报告"""
        snapshot = self.calculate_exposures()
        is_compliant, violations = self.check_exposure_limits()
        
        return {
            "timestamp": snapshot.timestamp.isoformat(),
            "total_value": self.total_value,
            "position_count": snapshot.position_count,
            "market_exposure": snapshot.market_exposure,
            "beta_exposure": snapshot.beta_exposure,
            "volatility_exposure": snapshot.volatility_exposure,
            "industry_exposure": snapshot.industry_exposure,
            "style_exposure": snapshot.style_exposure,
            "concentration_hhi": snapshot.concentration,
            "liquidity_score": snapshot.liquidity_score,
            "is_compliant": is_compliant,
            "violations": violations,
            "suggestions": self.get_rebalance_suggestions()
        }
    
    def plot_exposure(self, save_path: Optional[str] = None):
        """绘制敞口分析图"""
        try:
            import matplotlib.pyplot as plt
            
            snapshot = self.calculate_exposures()
            
            fig, axes = plt.subplots(2, 2, figsize=(14, 10))
            
            # 1. 行业敞口饼图
            ax1 = axes[0, 0]
            if snapshot.industry_exposure:
                industries = list(snapshot.industry_exposure.keys())
                exposures = list(snapshot.industry_exposure.values())
                ax1.pie(exposures, labels=industries, autopct='%1.1f%%')
                ax1.set_title('行业敞口分布')
            
            # 2. 风格因子敞口
            ax2 = axes[0, 1]
            if snapshot.style_exposure:
                factors = list(snapshot.style_exposure.keys())
                exposures = list(snapshot.style_exposure.values())
                colors = ['green' if e >= 0 else 'red' for e in exposures]
                ax2.barh(factors, exposures, color=colors, alpha=0.7)
                ax2.axvline(x=0, color='black', linestyle='-', linewidth=0.5)
                ax2.set_xlabel('Beta')
                ax2.set_title('风格因子暴露')
                ax2.grid(True, alpha=0.3)
            
            # 3. 持仓市值分布
            ax3 = axes[1, 0]
            if self.positions:
                symbols = list(self.positions.keys())
                values = [p['position_value'] / self.total_value for p in self.positions.values()]
                sorted_indices = np.argsort(values)[::-1][:10]  # Top 10
                ax3.barh(
                    [symbols[i] for i in sorted_indices],
                    [values[i] for i in sorted_indices]
                )
                ax3.set_xlabel('权重')
                ax3.set_title('Top 10 持仓权重')
                ax3.grid(True, alpha=0.3)
            
            # 4. 关键指标仪表盘
            ax4 = axes[1, 1]
            ax4.axis('off')
            
            metrics_text = f"""
            市场敞口: {snapshot.market_exposure:.2%}
            Beta敞口: {snapshot.beta_exposure:.2f}
            波动率敞口: {snapshot.volatility_exposure:.2%}
            持仓数量: {snapshot.position_count}
            HHI集中度: {snapshot.concentration:.3f}
            流动性评分: {snapshot.liquidity_score:.2f}
            """
            
            ax4.text(0.1, 0.5, metrics_text, fontsize=12, 
                    verticalalignment='center', fontfamily='monospace')
            ax4.set_title('关键敞口指标')
            
            plt.tight_layout()
            
            if save_path:
                plt.savefig(save_path, dpi=150, bbox_inches='tight')
                logger.info(f"敞口图表已保存: {save_path}")
            else:
                plt.show()
            
            plt.close()
            
        except ImportError:
            logger.warning("matplotlib未安装，无法绘图")
