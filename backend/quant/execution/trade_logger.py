"""
交易日志记录器
交易记录、审计追踪、统计分析
"""
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
import json
from quant.utils.logger import logger


@dataclass
class TradeEntry:
    """交易条目"""
    timestamp: datetime
    symbol: str
    side: str
    price: float
    quantity: int
    amount: float
    commission: float
    order_id: str
    strategy_id: str
    reason: str = ""
    expected_price: float = 0
    slippage: float = 0


@dataclass
class DailyStats:
    """每日统计"""
    date: date
    total_trades: int = 0
    buy_trades: int = 0
    sell_trades: int = 0
    total_buy_amount: float = 0
    total_sell_amount: float = 0
    total_commission: float = 0
    realized_pnl: float = 0
    symbols_traded: List[str] = field(default_factory=list)


class TradeLogger:
    """交易日志记录器"""
    
    def __init__(self, log_dir: str = "logs/trades"):
        """
        初始化交易日志记录器
        
        Args:
            log_dir: 日志目录
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.trades: List[TradeEntry] = []
        self.daily_stats: Dict[date, DailyStats] = {}
        
        logger.info(f"交易日志记录器初始化: {self.log_dir}")
    
    def log_trade(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: int,
        order_id: str,
        strategy_id: str = "",
        reason: str = "",
        expected_price: float = 0
    ):
        """
        记录交易
        
        Args:
            symbol: 股票代码
            side: 交易方向
            price: 成交价格
            quantity: 成交数量
            order_id: 订单ID
            strategy_id: 策略ID
            reason: 交易原因
            expected_price: 预期价格
        """
        commission = self._calculate_commission(price * quantity, side)
        slippage = price - expected_price if expected_price > 0 else 0
        
        entry = TradeEntry(
            timestamp=datetime.now(),
            symbol=symbol,
            side=side,
            price=price,
            quantity=quantity,
            amount=price * quantity,
            commission=commission,
            order_id=order_id,
            strategy_id=strategy_id,
            reason=reason,
            expected_price=expected_price,
            slippage=slippage
        )
        
        self.trades.append(entry)
        self._update_daily_stats(entry)
        
        logger.debug(
            f"交易已记录: {symbol}, {side}, {quantity}@{price:.2f}, "
            f"手续费={commission:.2f}, 滑点={slippage:.2f}"
        )
    
    def _calculate_commission(self, amount: float, side: str) -> float:
        """
        计算手续费（与回测器口径一致）
        
        Args:
            amount: 成交金额
            side: 交易方向
        
        Returns:
            总手续费
        """
        commission = amount * 0.0003  # 万三佣金
        commission = max(5.0, commission)  # 最低5元
        
        # A股买入不收印花税，只在卖出时收取万分之五
        if side.lower() == "sell":
            commission += amount * 0.0005
        
        return commission
    
    def _update_daily_stats(self, trade: TradeEntry):
        """更新每日统计"""
        today = trade.timestamp.date()
        
        if today not in self.daily_stats:
            self.daily_stats[today] = DailyStats(date=today)
        
        stats = self.daily_stats[today]
        stats.total_trades += 1
        
        if trade.side.lower() == "buy":
            stats.buy_trades += 1
            stats.total_buy_amount += trade.amount
        else:
            stats.sell_trades += 1
            stats.total_sell_amount += trade.amount
            # 估算已实现盈亏（简化版）
            stats.realized_pnl += self._estimate_realized_pnl(trade)
        
        stats.total_commission += trade.commission
        
        if trade.symbol not in stats.symbols_traded:
            stats.symbols_traded.append(trade.symbol)
    
    def _estimate_realized_pnl(self, trade: TradeEntry) -> float:
        """估算已实现盈亏"""
        # 简化版：使用平均成本估算
        return 0  # 实际需要结合持仓成本计算
    
    def get_trades_df(self) -> pd.DataFrame:
        """获取交易记录DataFrame"""
        if not self.trades:
            return pd.DataFrame()
        
        records = []
        for trade in self.trades:
            records.append({
                "timestamp": trade.timestamp,
                "symbol": trade.symbol,
                "side": trade.side,
                "price": trade.price,
                "quantity": trade.quantity,
                "amount": trade.amount,
                "commission": trade.commission,
                "order_id": trade.order_id,
                "strategy_id": trade.strategy_id,
                "reason": trade.reason,
                "slippage": trade.slippage
            })
        
        df = pd.DataFrame(records)
        if not df.empty:
            df = df.sort_values("timestamp")
        return df
    
    def get_daily_stats_df(self) -> pd.DataFrame:
        """获取每日统计DataFrame"""
        if not self.daily_stats:
            return pd.DataFrame()
        
        records = []
        for stats in self.daily_stats.values():
            records.append({
                "date": stats.date,
                "total_trades": stats.total_trades,
                "buy_trades": stats.buy_trades,
                "sell_trades": stats.sell_trades,
                "total_buy_amount": stats.total_buy_amount,
                "total_sell_amount": stats.total_sell_amount,
                "net_amount": stats.total_sell_amount - stats.total_buy_amount,
                "total_commission": stats.total_commission,
                "realized_pnl": stats.realized_pnl,
                "symbols_traded": ",".join(stats.symbols_traded)
            })
        
        df = pd.DataFrame(records)
        if not df.empty:
            df = df.sort_values("date")
        return df
    
    def get_symbol_stats(self, symbol: str) -> Dict:
        """获取指定股票的交易统计"""
        symbol_trades = [t for t in self.trades if t.symbol == symbol]
        
        if not symbol_trades:
            return {}
        
        buy_trades = [t for t in symbol_trades if t.side.lower() == "buy"]
        sell_trades = [t for t in symbol_trades if t.side.lower() == "sell"]
        
        return {
            "symbol": symbol,
            "total_trades": len(symbol_trades),
            "buy_trades": len(buy_trades),
            "sell_trades": len(sell_trades),
            "total_buy_amount": sum(t.amount for t in buy_trades),
            "total_sell_amount": sum(t.amount for t in sell_trades),
            "total_commission": sum(t.commission for t in symbol_trades),
            "avg_slippage": sum(t.slippage for t in symbol_trades) / len(symbol_trades),
            "first_trade_time": symbol_trades[0].timestamp if symbol_trades else None,
            "last_trade_time": symbol_trades[-1].timestamp if symbol_trades else None
        }
    
    def get_strategy_stats(self, strategy_id: str) -> Dict:
        """获取指定策略的交易统计"""
        strategy_trades = [t for t in self.trades if t.strategy_id == strategy_id]
        
        if not strategy_trades:
            return {}
        
        buy_trades = [t for t in strategy_trades if t.side.lower() == "buy"]
        sell_trades = [t for t in strategy_trades if t.side.lower() == "sell"]
        
        return {
            "strategy_id": strategy_id,
            "total_trades": len(strategy_trades),
            "buy_trades": len(buy_trades),
            "sell_trades": len(sell_trades),
            "total_amount": sum(t.amount for t in strategy_trades),
            "total_commission": sum(t.commission for t in strategy_trades),
            "symbols": list(set(t.symbol for t in strategy_trades)),
            "avg_slippage": sum(t.slippage for t in strategy_trades) / len(strategy_trades)
        }
    
    def get_summary(self) -> Dict:
        """获取汇总统计"""
        if not self.trades:
            return {}
        
        buy_trades = [t for t in self.trades if t.side.lower() == "buy"]
        sell_trades = [t for t in self.trades if t.side.lower() == "sell"]
        
        return {
            "total_trades": len(self.trades),
            "buy_trades": len(buy_trades),
            "sell_trades": len(sell_trades),
            "total_buy_amount": sum(t.amount for t in buy_trades),
            "total_sell_amount": sum(t.amount for t in sell_trades),
            "net_amount": sum(t.amount for t in sell_trades) - sum(t.amount for t in buy_trades),
            "total_commission": sum(t.commission for t in self.trades),
            "avg_commission": sum(t.commission for t in self.trades) / len(self.trades),
            "avg_slippage": sum(t.slippage for t in self.trades) / len(self.trades),
            "symbols_traded": list(set(t.symbol for t in self.trades)),
            "strategies_used": list(set(t.strategy_id for t in self.trades if t.strategy_id)),
            "first_trade_time": self.trades[0].timestamp if self.trades else None,
            "last_trade_time": self.trades[-1].timestamp if self.trades else None,
            "trading_days": len(self.daily_stats)
        }
    
    def save_to_csv(self, filepath: Optional[str] = None):
        """保存交易记录到CSV"""
        if filepath is None:
            filepath = self.log_dir / f"trades_{date.today().isoformat()}.csv"
        else:
            filepath = Path(filepath)
        
        df = self.get_trades_df()
        if not df.empty:
            df.to_csv(filepath, index=False)
            logger.info(f"交易记录已保存: {filepath}")
    
    def save_daily_stats(self, filepath: Optional[str] = None):
        """保存每日统计到CSV"""
        if filepath is None:
            filepath = self.log_dir / f"daily_stats_{date.today().isoformat()}.csv"
        else:
            filepath = Path(filepath)
        
        df = self.get_daily_stats_df()
        if not df.empty:
            df.to_csv(filepath, index=False)
            logger.info(f"每日统计已保存: {filepath}")
    
    def export_json(self, filepath: Optional[str] = None) -> str:
        """导出交易记录到JSON"""
        if filepath is None:
            filepath = self.log_dir / f"trades_{date.today().isoformat()}.json"
        else:
            filepath = Path(filepath)
        
        data = {
            "summary": self.get_summary(),
            "trades": [
                {
                    "timestamp": t.timestamp.isoformat(),
                    "symbol": t.symbol,
                    "side": t.side,
                    "price": t.price,
                    "quantity": t.quantity,
                    "amount": t.amount,
                    "commission": t.commission,
                    "order_id": t.order_id,
                    "strategy_id": t.strategy_id,
                    "reason": t.reason,
                    "slippage": t.slippage
                }
                for t in self.trades
            ]
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"交易记录已导出: {filepath}")
        return str(filepath)
    
    def clear_old_records(self, days: int = 90):
        """清理旧记录"""
        cutoff = datetime.now() - pd.Timedelta(days=days)
        old_count = len(self.trades)
        
        self.trades = [t for t in self.trades if t.timestamp >= cutoff]
        
        # 清理旧统计
        old_dates = [d for d in self.daily_stats.keys() if d < cutoff.date()]
        for d in old_dates:
            del self.daily_stats[d]
        
        removed = old_count - len(self.trades)
        if removed > 0:
            logger.info(f"已清理 {removed} 条旧交易记录")


# 类型注解需要的Optional
from typing import Optional
