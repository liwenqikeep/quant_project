"""
仓位限制管理
单股仓位、行业仓位、市值风格仓位等限制
"""
import pandas as pd
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path
from quant.utils.logger import logger


@dataclass
class PositionLimit:
    """单一仓位限制"""
    max_ratio: float = 0.2      # 最大持仓比例
    max_amount: float = None     # 最大持仓金额（可选）
    min_amount: float = None     # 最小持仓金额（可选）
    blocked: bool = False        # 是否被禁止交易


@dataclass
class PositionLimits:
    """仓位限制管理器"""
    # 单股仓位限制
    stock_limits: Dict[str, PositionLimit] = field(default_factory=dict)
    
    # 行业仓位限制
    industry_limits: Dict[str, PositionLimit] = field(default_factory=dict)
    
    # 市值风格限制
    market_cap_limits: Dict[str, PositionLimit] = field(default_factory=dict)
    
    # 全局限制
    max_total_position: float = 0.9      # 总仓位上限
    max_single_stock: float = 0.2        # 单股最大仓位
    max_industry_single: float = 0.3     # 单行业最大仓位
    min_position_to_hold: int = 100      # 最小持仓股数（手）


class PositionLimitManager:
    """仓位限制管理器"""
    
    # 行业分类映射（简化版）
    INDUSTRY_MAPPING = {
        "000001": "银行", "000002": "房地产", "000004": "软件",
        "000005": "商业零售", "000006": "房地产", "000007": "酒店",
        "000008": "通信", "000009": "综合", "000010": "环保",
        "600000": "银行", "600004": "银行", "600006": "汽车",
        "600007": "房地产", "600008": "环保", "600009": "交通运输",
        "600010": "钢铁", "600011": "电力", "600012": "汽车",
        "600015": "银行", "600016": "银行", "600017": "港口",
        "600018": "港口", "600019": "钢铁", "600020": "交通运输",
        "600021": "电力", "600022": "钢铁", "600023": "电力",
        "600026": "交通运输", "600027": "电力", "600028": "石油",
        "600029": "交通运输", "600030": "证券", "600031": "机械",
        "600032": "建筑", "600033": "交通运输", "600034": "银行",
        "600035": "汽车", "600036": "银行", "600037": "交通运输",
        "600038": "军工", "600039": "建筑", "600048": "房地产",
        "600050": "通信", "600051": "贸易", "600052": "房地产",
        "600053": "房地产", "600054": "旅游", "600055": "医药",
        "600056": "医药", "600057": "房地产", "600058": "钢铁",
        "600059": "白酒", "600060": "家电", "600061": "多元金融",
        "600062": "医药", "600063": "化工", "600064": "房地产",
        "600066": "汽车", "600067": "房地产", "600068": "建筑",
        "600069": "纺织", "600070": "家电", "600089": "电气设备",
        "600104": "汽车", "600519": "白酒", "600887": "食品饮料",
        "600900": "电力", "601006": "交通运输", "601012": "电气设备",
        "601088": "煤炭", "601166": "银行", "601186": "建筑",
        "601229": "银行", "601288": "银行", "601318": "保险",
        "601328": "银行", "601398": "银行", "601601": "保险",
        "601628": "保险", "601668": "建筑", "601818": "银行",
        "601857": "石油", "601988": "银行", "601998": "银行",
    }
    
    # 市值风格分类
    MARKET_CAP_STYLE = {
        "large_cap": {"threshold": 1000, "max_ratio": 0.5},      # 千亿以上
        "mid_cap": {"threshold": 300, "max_ratio": 0.3},         # 300亿-1000亿
        "small_cap": {"threshold": 0, "max_ratio": 0.2},        # 300亿以下
    }
    
    def __init__(self, config: Optional[PositionLimits] = None):
        """
        初始化仓位限制管理器
        
        Args:
            config: 仓位限制配置
        """
        self.config = config or PositionLimits()
        self.current_positions: Dict[str, float] = {}  # symbol -> position_value
        self.total_position_value = 0
        self.total_value = 0
        self.industry_exposure: Dict[str, float] = defaultdict(float)
        self.market_cap_exposure: Dict[str, float] = defaultdict(float)
        logger.info("仓位限制管理器初始化完成")
    
    def set_total_value(self, total_value: float):
        """设置总资产"""
        self.total_value = total_value
        logger.debug(f"总资产更新: {total_value:,.2f}")
    
    def update_position(
        self,
        symbol: str,
        position_value: float,
        industry: Optional[str] = None,
        market_cap: Optional[float] = None
    ):
        """
        更新持仓信息
        
        Args:
            symbol: 股票代码
            position_value: 持仓市值
            industry: 行业分类
            market_cap: 市值（亿元）
        """
        old_value = self.current_positions.get(symbol, 0)
        delta = position_value - old_value
        
        self.current_positions[symbol] = position_value
        self.total_position_value += delta
        
        # 更新行业暴露
        if industry is None:
            industry = self._get_industry(symbol)
        if industry:
            self.industry_exposure[industry] += delta
            if position_value == 0:
                del self.current_positions[symbol]
        
        # 更新市值风格暴露
        if market_cap is not None:
            style = self._get_market_cap_style(market_cap)
            self.market_cap_exposure[style] += delta
        
        logger.debug(
            f"持仓更新: {symbol} = {position_value:,.2f}, "
            f"总仓位 = {self.total_position_value/self.total_value:.2%}"
        )
    
    def _get_industry(self, symbol: str) -> str:
        """获取股票行业"""
        # 尝试从映射获取
        code = symbol.replace(".SZ", "").replace(".SH", "")
        if code in self.INDUSTRY_MAPPING:
            return self.INDUSTRY_MAPPING[code]
        
        # 按代码范围猜测行业（简化版）
        code_num = int(code) if code.isdigit() else 0
        if 1 <= code_num <= 100:
            return "综合"
        elif code_num < 1000:
            return "主板"
        elif code_num < 2000:
            return "中小板"
        elif code_num < 3000:
            return "创业板"
        elif code_num < 4000:
            return "科创板"
        return "其他"
    
    def _get_market_cap_style(self, market_cap: float) -> str:
        """获取市值风格"""
        if market_cap >= 1000:
            return "large_cap"
        elif market_cap >= 300:
            return "mid_cap"
        return "small_cap"
    
    def check_buy_limit(
        self,
        symbol: str,
        amount: float,
        industry: Optional[str] = None,
        market_cap: Optional[float] = None
    ) -> tuple:
        """
        检查买入限制
        
        Args:
            symbol: 股票代码
            amount: 买入金额
            industry: 行业
            market_cap: 市值
        
        Returns:
            (是否允许, 拒绝原因)
        """
        reasons = []
        
        # 1. 检查总仓位
        new_total = self.total_position_value + amount
        if self.total_value > 0 and new_total / self.total_value > self.config.max_total_position:
            reasons.append(
                f"总仓位超限: {new_total/self.total_value:.2%} > "
                f"{self.config.max_total_position:.2%}"
            )
        
        # 2. 检查单股仓位
        current_stock = self.current_positions.get(symbol, 0)
        new_stock = current_stock + amount
        if self.total_value > 0 and new_stock / self.total_value > self.config.max_single_stock:
            reasons.append(
                f"单股仓位超限: {new_stock/self.total_value:.2%} > "
                f"{self.config.max_single_stock:.2%}"
            )
        
        # 3. 检查行业仓位
        if industry is None:
            industry = self._get_industry(symbol)
        if industry:
            new_industry = self.industry_exposure.get(industry, 0) + amount
            if self.total_value > 0 and new_industry / self.total_value > self.config.max_industry_single:
                reasons.append(
                    f"行业仓位超限[{industry}]: {new_industry/self.total_value:.2%} > "
                    f"{self.config.max_industry_single:.2%}"
                )
        
        # 4. 检查市值风格限制
        if market_cap is not None:
            style = self._get_market_cap_style(market_cap)
            new_style_exposure = self.market_cap_exposure.get(style, 0) + amount
            style_limit = self.MARKET_CAP_STYLE.get(style, {}).get("max_ratio", 0.3)
            if self.total_value > 0 and new_style_exposure / self.total_value > style_limit:
                reasons.append(
                    f"市值风格仓位超限[{style}]: {new_style_exposure/self.total_value:.2%} > "
                    f"{style_limit:.2%}"
                )
        
        # 5. 检查黑名单
        if symbol in self.config.stock_limits:
            limit = self.config.stock_limits[symbol]
            if limit.blocked:
                reasons.append(f"{symbol}在禁止名单中")
        
        allowed = len(reasons) == 0
        reason = "; ".join(reasons) if reasons else "通过"
        
        if not allowed:
            logger.warning(f"买入限制检查未通过: {symbol}, {reason}")
        
        return allowed, reason
    
    def check_sell_limit(
        self,
        symbol: str,
        amount: float
    ) -> tuple:
        """
        检查卖出限制
        
        Args:
            symbol: 股票代码
            amount: 卖出金额
        
        Returns:
            (是否允许, 拒绝原因)
        """
        reasons = []
        
        current = self.current_positions.get(symbol, 0)
        if amount > current:
            reasons.append(f"卖出数量超出现有持仓: {amount} > {current}")
        
        # 检查是否涨停（不能卖）
        # 这里需要结合实时行情判断
        
        allowed = len(reasons) == 0
        reason = "; ".join(reasons) if reasons else "通过"
        
        return allowed, reason
    
    def get_rebalance_suggestions(
        self,
        target_positions: Dict[str, float]
    ) -> List[Dict]:
        """
        获取再平衡建议
        
        Args:
            target_positions: 目标持仓 {symbol: ratio}
        
        Returns:
            再平衡操作列表
        """
        actions = []
        
        # 计算当前仓位比例
        current_ratios = {
            sym: val / self.total_value 
            for sym, val in self.current_positions.items()
            if self.total_value > 0
        }
        
        # 合并目标和当前的股票列表
        all_symbols = set(current_ratios.keys()) | set(target_positions.keys())
        
        for symbol in all_symbols:
            current_ratio = current_ratios.get(symbol, 0)
            target_ratio = target_positions.get(symbol, 0)
            delta_ratio = target_ratio - current_ratio
            delta_amount = delta_ratio * self.total_value
            
            if abs(delta_ratio) > 0.01:  # 超过1%才操作
                action = "buy" if delta_amount > 0 else "sell"
                actions.append({
                    "symbol": symbol,
                    "action": action,
                    "ratio_change": delta_ratio,
                    "amount": abs(delta_amount),
                    "current_ratio": current_ratio,
                    "target_ratio": target_ratio
                })
        
        return actions
    
    def get_exposure_report(self) -> Dict:
        """获取暴露度报告"""
        return {
            "total_position_ratio": self.total_position_value / self.total_value if self.total_value > 0 else 0,
            "positions": {
                sym: {
                    "value": val,
                    "ratio": val / self.total_value if self.total_value > 0 else 0
                }
                for sym, val in self.current_positions.items()
            },
            "industry_exposure": dict(self.industry_exposure),
            "market_cap_exposure": dict(self.market_cap_exposure),
            "total_value": self.total_value
        }


# 类型注解需要的Optional
from typing import Optional
