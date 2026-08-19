"""
持仓追踪器
实时持仓监控、成本计算、盈亏追踪
"""
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from quant.utils.logger import logger


@dataclass
class PositionRecord:
    """持仓记录"""
    symbol: str
    shares: int = 0
    avg_cost: float = 0
    last_price: float = 0
    market_value: float = 0
    unrealized_pnl: float = 0
    unrealized_pnl_pct: float = 0
    realized_pnl: float = 0
    today_trades: int = 0
    update_time: datetime = field(default_factory=datetime.now)


@dataclass
class TradeRecord:
    """交易记录"""
    symbol: str
    side: str  # "buy" or "sell"
    price: float
    shares: int
    amount: float
    commission: float
    trade_time: datetime


class PositionTracker:
    """持仓追踪器"""
    
    def __init__(self):
        self.positions: Dict[str, PositionRecord] = {}
        self.trade_history: List[TradeRecord] = []
        self.cash = 0
        self.initial_cash = 0
        logger.info("持仓追踪器初始化完成")
    
    def set_cash(self, cash: float, initial: bool = False):
        """设置现金"""
        self.cash = cash
        if initial:
            self.initial_cash = cash
        logger.debug(f"现金更新: {cash:,.2f}")
    
    def update_position(
        self,
        symbol: str,
        shares: int,
        price: float,
        side: str,
        commission: float = 0
    ) -> PositionRecord:
        """
        更新持仓
        
        Args:
            symbol: 股票代码
            shares: 交易股数
            price: 成交价格
            side: 交易方向 ("buy" or "sell")
            commission: 手续费
        
        Returns:
            更新后的持仓记录
        """
        pos = self.positions.get(symbol)
        
        # 记录交易
        trade = TradeRecord(
            symbol=symbol,
            side=side,
            price=price,
            shares=shares,
            amount=shares * price,
            commission=commission,
            trade_time=datetime.now()
        )
        self.trade_history.append(trade)
        
        if pos is None:
            pos = PositionRecord(symbol=symbol)
            self.positions[symbol] = pos
        
        if side.lower() == "buy":
            # 买入：更新成本
            old_value = pos.shares * pos.avg_cost
            new_value = shares * price
            total_shares = pos.shares + shares
            pos.avg_cost = (old_value + new_value) / total_shares if total_shares > 0 else 0
            pos.shares = total_shares
            self.cash -= (new_value + commission)
            pos.today_trades += 1
        else:
            # 卖出：更新持仓，计算已实现盈亏
            old_value = pos.shares * pos.avg_cost
            sold_value = shares * price
            remaining_shares = pos.shares - shares
            realized_pnl = sold_value - (shares * pos.avg_cost) - commission
            pos.realized_pnl += realized_pnl
            pos.shares = remaining_shares
            self.cash += (sold_value - commission)
            pos.today_trades += 1
            
            if pos.shares == 0:
                # 持仓清空，保留记录一段时间
                pos.avg_cost = 0
        
        # 更新最新价和市值
        pos.last_price = price
        pos.market_value = pos.shares * price
        pos.unrealized_pnl = (price - pos.avg_cost) * pos.shares if pos.shares > 0 else 0
        pos.unrealized_pnl_pct = (price / pos.avg_cost - 1) if pos.avg_cost > 0 else 0
        pos.update_time = datetime.now()
        
        logger.debug(
            f"持仓更新: {symbol}, {side}, {shares}股@{price:.2f}, "
            f"剩余: {pos.shares}股, 成本: {pos.avg_cost:.2f}"
        )
        
        return pos
    
    def update_price(self, symbol: str, price: float):
        """
        更新持仓价格
        
        Args:
            symbol: 股票代码
            price: 最新价格
        """
        pos = self.positions.get(symbol)
        if pos:
            pos.last_price = price
            pos.market_value = pos.shares * price
            pos.unrealized_pnl = (price - pos.avg_cost) * pos.shares if pos.shares > 0 else 0
            pos.unrealized_pnl_pct = (price / pos.avg_cost - 1) if pos.avg_cost > 0 else 0
            pos.update_time = datetime.now()
    
    def update_prices(self, prices: Dict[str, float]):
        """批量更新价格"""
        for symbol, price in prices.items():
            self.update_price(symbol, price)
    
    def get_position(self, symbol: str) -> Optional[PositionRecord]:
        """获取指定持仓"""
        return self.positions.get(symbol)
    
    def get_all_positions(self) -> List[PositionRecord]:
        """获取所有持仓"""
        return list(self.positions.values())
    
    def get_total_value(self) -> float:
        """获取总资产"""
        market_value = sum(pos.market_value for pos in self.positions.values())
        return self.cash + market_value
    
    def get_total_pnl(self) -> tuple:
        """获取总盈亏"""
        unrealized = sum(pos.unrealized_pnl for pos in self.positions.values())
        realized = sum(pos.realized_pnl for pos in self.positions.values())
        total = unrealized + realized
        total_pnl_pct = total / self.initial_cash if self.initial_cash > 0 else 0
        return total, unrealized, realized, total_pnl_pct
    
    def get_position_summary(self) -> Dict:
        """获取持仓摘要"""
        total_value = self.get_total_value()
        total_market_value = total_value - self.cash
        total_unrealized, total_realized, _, total_pnl_pct = self.get_total_pnl()
        
        # 计算今日盈亏
        today = datetime.now().date()
        today_trades = [t for t in self.trade_history if t.trade_time.date() == today]
        today_pnl = 0
        for trade in today_trades:
            if trade.side.lower() == "sell":
                # 估算卖出盈亏
                cost = self._estimate_cost(trade.symbol, trade.shares)
                today_pnl += trade.amount - cost - trade.commission
        
        return {
            "cash": self.cash,
            "market_value": total_market_value,
            "total_value": total_value,
            "position_count": len(self.positions),
            "unrealized_pnl": total_unrealized,
            "realized_pnl": total_realized,
            "total_pnl": total_unrealized + total_realized,
            "total_pnl_pct": total_pnl_pct,
            "today_pnl": today_pnl,
            "today_trades": len(today_trades),
            "return": (total_value - self.initial_cash) / self.initial_cash if self.initial_cash > 0 else 0
        }
    
    def _estimate_cost(self, symbol: str, shares: int) -> float:
        """估算买入成本"""
        pos = self.positions.get(symbol)
        if pos and pos.avg_cost > 0:
            return shares * pos.avg_cost
        return 0
    
    def get_position_df(self) -> pd.DataFrame:
        """获取持仓DataFrame"""
        if not self.positions:
            return pd.DataFrame()
        
        records = []
        for pos in self.positions.values():
            records.append({
                "symbol": pos.symbol,
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "last_price": pos.last_price,
                "market_value": pos.market_value,
                "unrealized_pnl": pos.unrealized_pnl,
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                "realized_pnl": pos.realized_pnl,
                "weight": pos.market_value / self.get_total_value() if self.get_total_value() > 0 else 0
            })
        
        df = pd.DataFrame(records)
        if not df.empty:
            df = df.sort_values("market_value", ascending=False)
        return df
    
    def get_trade_history_df(self) -> pd.DataFrame:
        """获取交易历史DataFrame"""
        if not self.trade_history:
            return pd.DataFrame()
        
        records = []
        for trade in self.trade_history:
            records.append({
                "symbol": trade.symbol,
                "side": trade.side,
                "price": trade.price,
                "shares": trade.shares,
                "amount": trade.amount,
                "commission": trade.commission,
                "trade_time": trade.trade_time
            })
        
        df = pd.DataFrame(records)
        if not df.empty:
            df = df.sort_values("trade_time", ascending=False)
        return df
    
    def reset(self):
        """重置追踪器"""
        self.positions.clear()
        self.trade_history.clear()
        self.cash = 0
        self.initial_cash = 0
        logger.info("持仓追踪器已重置")
