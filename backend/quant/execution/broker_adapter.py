"""
券商接口适配器
统一封装不同券商的交易接口
"""
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod
import time
from pathlib import Path
from quant.utils.logger import logger


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"           # 市价单
    LIMIT = "limit"            # 限价单
    STOP = "stop"              # 止损单
    STOP_LIMIT = "stop_limit"  # 止损限价单


class OrderSide(Enum):
    """交易方向"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"         # 待提交
    SUBMITTED = "submitted"     # 已提交
    PARTIAL = "partial"         # 部分成交
    FILLED = "filled"           # 完全成交
    CANCELLED = "cancelled"     # 已取消
    REJECTED = "rejected"       # 已拒绝
    EXPIRED = "expired"         # 已过期


@dataclass
class Order:
    """订单"""
    order_id: str = ""
    symbol: str = ""            # 股票代码
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.LIMIT
    price: float = 0           # 限价/止损价
    quantity: int = 0          # 委托数量
    filled_quantity: int = 0    # 已成交数量
    avg_fill_price: float = 0  # 平均成交价
    status: OrderStatus = OrderStatus.PENDING
    create_time: datetime = field(default_factory=datetime.now)
    update_time: datetime = field(default_factory=datetime.now)
    cancel_time: Optional[datetime] = None
    reject_reason: str = ""
    commission: float = 0       # 手续费
    remark: str = ""            # 备注


@dataclass
class Trade:
    """成交记录"""
    trade_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    price: float = 0
    quantity: int = 0
    commission: float = 0
    trade_time: datetime = field(default_factory=datetime.now)


@dataclass
class AccountInfo:
    """账户信息"""
    account_id: str = ""
    cash: float = 0             # 可用资金
    frozen_cash: float = 0      # 冻结资金
    market_value: float = 0     # 持仓市值
    total_assets: float = 0     # 总资产
    position_count: int = 0     # 持仓数量
    today_trades: int = 0       # 今日交易次数
    today_turnover: float = 0   # 今日成交额


@dataclass
class Position:
    """持仓信息"""
    symbol: str = ""
    shares: int = 0             # 持仓股数
    avg_cost: float = 0         # 平均成本
    frozen_shares: int = 0      # 冻结股数（挂单中）
    today_buy: int = 0          # 今日买入
    today_sell: int = 0         # 今日卖出
    open_price: float = 0       # 开盘价
    last_price: float = 0       # 最新价
    market_value: float = 0     # 市值
    unrealized_pnl: float = 0   # 浮动盈亏
    realized_pnl: float = 0    # 已实现盈亏


class BrokerAdapter(ABC):
    """券商适配器基类"""
    
    @abstractmethod
    def connect(self) -> bool:
        """连接券商"""
        pass
    
    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """检查连接状态"""
        pass
    
    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """获取账户信息"""
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Position]:
        """获取持仓"""
        pass
    
    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Position]:
        """获取指定持仓"""
        pass
    
    @abstractmethod
    def send_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        order_type: OrderType = OrderType.LIMIT,
        price: float = 0
    ) -> str:
        """发送订单"""
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        pass
    
    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        """查询订单"""
        pass
    
    @abstractmethod
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """查询订单列表"""
        pass
    
    @abstractmethod
    def get_trades(self, symbol: Optional[str] = None) -> List[Trade]:
        """查询成交记录"""
        pass


class SimulatedBroker(BrokerAdapter):
    """模拟券商（用于回测和模拟交易）"""
    
    def __init__(self, initial_cash: float = 1000000):
        """
        初始化模拟券商
        
        Args:
            initial_cash: 初始资金
        """
        self.initial_cash = initial_cash
        self._connected = False
        self._cash = initial_cash
        self._positions: Dict[str, Position] = {}
        self._orders: Dict[str, Order] = {}
        self._trades: Dict[str, Trade] = {}
        self._order_id_counter = 0
        self._trade_id_counter = 0
        self._last_price: Dict[str, float] = {}  # 最新价缓存
        
        # 成交回调
        self.on_trade: Optional[Callable] = None
        
        logger.info(f"模拟券商初始化: 初始资金={initial_cash:,.2f}")
    
    def connect(self) -> bool:
        """连接"""
        self._connected = True
        logger.info("模拟券商已连接")
        return True
    
    def disconnect(self):
        """断开连接"""
        self._connected = False
        logger.info("模拟券商已断开")
    
    def is_connected(self) -> bool:
        return self._connected
    
    def set_last_price(self, symbol: str, price: float):
        """设置最新价（用于模拟成交）"""
        self._last_price[symbol] = price
    
    def get_account_info(self) -> AccountInfo:
        """获取账户信息"""
        total_assets = self._cash
        today_trades = 0
        today_turnover = 0
        
        for pos in self._positions.values():
            total_assets += pos.market_value
            today_trades += pos.today_buy + pos.today_sell
            today_turnover += (pos.today_buy + pos.today_sell) * pos.avg_cost
        
        return AccountInfo(
            account_id="SIM001",
            cash=self._cash,
            frozen_cash=0,
            market_value=total_assets - self._cash,
            total_assets=total_assets,
            position_count=len(self._positions),
            today_trades=today_trades,
            today_turnover=today_turnover
        )
    
    def get_positions(self) -> List[Position]:
        """获取所有持仓"""
        return list(self._positions.values())
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """获取指定持仓"""
        return self._positions.get(symbol)
    
    def send_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        order_type: OrderType = OrderType.LIMIT,
        price: float = 0
    ) -> str:
        """发送订单"""
        if not self._connected:
            raise ConnectionError("券商未连接")
        
        self._order_id_counter += 1
        order_id = f"SIM{self._order_id_counter:08d}"
        
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            status=OrderStatus.SUBMITTED,
            create_time=datetime.now()
        )
        
        self._orders[order_id] = order
        
        # 模拟立即成交（市价单或价格满足条件）
        self._simulate_fill(order)
        
        logger.info(
            f"订单已提交: {order_id}, {side.value}, "
            f"{symbol}, {quantity}股, {'市价' if order_type == OrderType.MARKET else f'{price:.2f}'}"
        )
        
        return order_id
    
    def _simulate_fill(self, order: Order):
        """模拟成交"""
        # 获取成交价格
        if order.order_type == OrderType.MARKET:
            fill_price = self._last_price.get(order.symbol, order.price)
            if fill_price == 0:
                fill_price = order.price if order.price > 0 else 10.0  # 默认价格
        else:
            fill_price = order.price
        
        # 模拟成交
        self._trade_id_counter += 1
        trade_id = f"TR{self._trade_id_counter:08d}"
        
        trade = Trade(
            trade_id=trade_id,
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            price=fill_price,
            quantity=order.quantity,
            commission=self._calculate_commission(fill_price * order.quantity),
            trade_time=datetime.now()
        )
        
        self._trades[trade_id] = trade
        
        # 更新订单状态
        order.filled_quantity = order.quantity
        order.avg_fill_price = fill_price
        order.status = OrderStatus.FILLED
        order.update_time = datetime.now()
        order.commission = trade.commission
        
        # 更新持仓
        self._update_position(order.symbol, order.side, order.quantity, fill_price)
        
        # 扣除手续费
        self._cash -= trade.commission
        
        # 触发成交回调
        if self.on_trade:
            self.on_trade(trade)
        
        logger.debug(
            f"订单成交: {order.order_id}, 成交价={fill_price:.2f}, "
            f"数量={order.quantity}, 手续费={trade.commission:.2f}"
        )
    
    def _calculate_commission(self, trade_value: float) -> float:
        """计算手续费"""
        commission = trade_value * 0.0003  # 万三佣金
        commission = max(5.0, commission)   # 最低5元
        
        if trade_value > 0:
            stamp_tax = trade_value * 0.001  # 千一印花税（仅卖出）
            commission += stamp_tax
        
        return commission
    
    def _update_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float
    ):
        """更新持仓"""
        pos = self._positions.get(symbol)
        
        if pos is None:
            pos = Position(
                symbol=symbol,
                shares=0,
                avg_cost=0,
                market_value=0
            )
            self._positions[symbol] = pos
        
        if side == OrderSide.BUY:
            # 买入：增加持仓
            total_cost = pos.shares * pos.avg_cost + quantity * price
            pos.shares += quantity
            pos.avg_cost = total_cost / pos.shares if pos.shares > 0 else 0
            pos.today_buy += quantity
            self._cash -= quantity * price
        else:
            # 卖出：减少持仓
            pos.shares -= quantity
            pos.today_sell += quantity
            self._cash += quantity * price
            
            if pos.shares == 0:
                del self._positions[symbol]
        
        # 更新市值
        if symbol in self._last_price:
            pos.last_price = self._last_price[symbol]
            pos.market_value = pos.shares * pos.last_price
            pos.unrealized_pnl = (pos.last_price - pos.avg_cost) * pos.shares
    
    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        order = self._orders.get(order_id)
        if order is None:
            logger.warning(f"订单不存在: {order_id}")
            return False
        
        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED]:
            logger.warning(f"订单无法取消: {order_id}, 状态={order.status.value}")
            return False
        
        order.status = OrderStatus.CANCELLED
        order.cancel_time = datetime.now()
        
        logger.info(f"订单已取消: {order_id}")
        return True
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """查询订单"""
        return self._orders.get(order_id)
    
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """查询订单列表"""
        if status is None:
            return list(self._orders.values())
        return [o for o in self._orders.values() if o.status == status]
    
    def get_trades(self, symbol: Optional[str] = None) -> List[Trade]:
        """查询成交记录"""
        if symbol is None:
            return list(self._trades.values())
        return [t for t in self._trades.values() if t.symbol == symbol]
    
    def reset(self):
        """重置账户（用于新回测）"""
        self._cash = self.initial_cash
        self._positions.clear()
        self._orders.clear()
        self._trades.clear()
        self._order_id_counter = 0
        self._trade_id_counter = 0
        self._last_price.clear()
        logger.info("模拟账户已重置")
