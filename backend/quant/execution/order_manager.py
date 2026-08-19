"""
订单管理器
订单路由、拆分、合并、重试、优先级管理
"""
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from collections import defaultdict
import time
from pathlib import Path
from quant.utils.logger import logger


class OrderPriority(Enum):
    """订单优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


@dataclass
class OrderRequest:
    """订单请求"""
    symbol: str
    side: str  # "buy" or "sell"
    quantity: int
    order_type: str = "limit"  # "market", "limit", "stop"
    price: float = 0
    priority: OrderPriority = OrderPriority.NORMAL
    parent_id: str = ""  # 父订单ID（拆分订单用）
    strategy_id: str = ""  # 策略ID
    remark: str = ""
    create_time: datetime = field(default_factory=datetime.now)


@dataclass
class ExecutionStats:
    """执行统计"""
    total_orders: int = 0
    filled_orders: int = 0
    cancelled_orders: int = 0
    rejected_orders: int = 0
    total_quantity: int = 0
    filled_quantity: int = 0
    avg_slippage: float = 0  # 平均滑点
    total_commission: float = 0
    vwap: float = 0  # 成交量加权平均价


class OrderManager:
    """订单管理器"""
    
    def __init__(self, broker, risk_engine=None):
        """
        初始化订单管理器
        
        Args:
            broker: 券商适配器
            risk_engine: 风控引擎（可选）
        """
        self.broker = broker
        self.risk_engine = risk_engine
        
        # 订单缓存
        self.pending_orders: Dict[str, OrderRequest] = {}
        self.active_orders: Dict[str, str] = {}  # order_request_id -> broker_order_id
        self.completed_orders: Dict[str, OrderRequest] = {}
        
        # 执行统计
        self.stats = ExecutionStats()
        
        # 回调函数
        self.on_order_submitted: Optional[Callable] = None
        self.on_order_filled: Optional[Callable] = None
        self.on_order_cancelled: Optional[Callable] = None
        self.on_order_rejected: Optional[Callable] = None
        
        # 配置
        self.enable_order_split = True  # 启用订单拆分
        self.split_threshold = 100000   # 超过此金额拆分订单
        self.split_size = 5000         # 拆分后每单数量
        self.max_retry = 3              # 最大重试次数
        self.retry_interval = 1         # 重试间隔（秒）
        
        logger.info("订单管理器初始化完成")
    
    def submit_order(self, request: OrderRequest) -> List[str]:
        """
        提交订单
        
        Args:
            request: 订单请求
        
        Returns:
            提交的订单ID列表
        """
        self.stats.total_orders += 1
        request_id = f"REQ{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        self.pending_orders[request_id] = request
        
        logger.info(
            f"接收到订单请求: {request_id}, {request.side}, "
            f"{request.symbol}, {request.quantity}股"
        )
        
        # 拆分订单
        if self.enable_order_split and request.quantity * request.price > self.split_threshold:
            order_ids = self._split_and_submit(request, request_id)
        else:
            order_ids = self._submit_single(request, request_id)
        
        return order_ids
    
    def _split_and_submit(
        self,
        request: OrderRequest,
        request_id: str
    ) -> List[str]:
        """
        拆分并提交订单
        
        Args:
            request: 订单请求
            request_id: 请求ID
        
        Returns:
            订单ID列表
        """
        order_ids = []
        remaining = request.quantity
        
        while remaining > 0:
            chunk_size = min(self.split_size, remaining)
            
            # 创建子订单
            child_request = OrderRequest(
                symbol=request.symbol,
                side=request.side,
                quantity=chunk_size,
                order_type=request.order_type,
                price=request.price,
                priority=request.priority,
                parent_id=request_id,
                strategy_id=request.strategy_id,
                remark=f"拆分订单: {len(order_ids) + 1}"
            )
            
            child_id = self._submit_single(child_request, request_id)
            order_ids.extend(child_id)
            
            remaining -= chunk_size
            
            # 分批提交间隔
            if remaining > 0:
                time.sleep(0.1)
        
        logger.info(f"订单拆分完成: {request_id} -> {len(order_ids)} 个子订单")
        return order_ids
    
    def _submit_single(
        self,
        request: OrderRequest,
        request_id: str
    ) -> List[str]:
        """
        提交单个订单
        
        Args:
            request: 订单请求
            request_id: 请求ID
        
        Returns:
            订单ID列表
        """
        from .broker_adapter import OrderSide, OrderType
        
        # 风控检查
        if self.risk_engine:
            account = self.broker.get_account_info()
            position = self.broker.get_position(request.symbol)
            position_value = position.market_value if position else 0
            
            can_pass, reason, risk_level = self.risk_engine.check_order(
                symbol=request.symbol,
                direction=request.side,
                quantity=request.quantity,
                price=request.price if request.price > 0 else 10.0,
                cash=account.cash,
                position_value=position_value,
                total_value=account.total_assets
            )
            
            if not can_pass:
                logger.warning(
                    f"订单被风控拦截: {request_id}, {request.symbol}, "
                    f"原因: {reason}"
                )
                self._handle_rejected(request, request_id, reason)
                return []
            
            if risk_level.value in ["warning", "danger"]:
                logger.warning(f"风控警告: {reason}")
        
        # 提交到券商
        try:
            side = OrderSide.BUY if request.side.lower() == "buy" else OrderSide.SELL
            order_type = OrderType.LIMIT if request.order_type == "limit" else OrderType.MARKET
            
            broker_order_id = self.broker.send_order(
                symbol=request.symbol,
                side=side,
                quantity=request.quantity,
                order_type=order_type,
                price=request.price
            )
            
            self.active_orders[request_id] = broker_order_id
            self.pending_orders.pop(request_id, None)
            
            logger.info(f"订单提交成功: {request_id} -> {broker_order_id}")
            
            if self.on_order_submitted:
                self.on_order_submitted(request, broker_order_id)
            
            return [broker_order_id]
            
        except Exception as e:
            logger.error(f"订单提交失败: {request_id}, 错误: {e}")
            self._handle_rejected(request, request_id, str(e))
            return []
    
    def _handle_rejected(self, request: OrderRequest, request_id: str, reason: str):
        """处理被拒绝的订单"""
        self.stats.rejected_orders += 1
        self.pending_orders.pop(request_id, None)
        
        if self.on_order_rejected:
            self.on_order_rejected(request, reason)
    
    def cancel_order(self, request_id: str) -> bool:
        """
        取消订单
        
        Args:
            request_id: 请求ID
        
        Returns:
            是否取消成功
        """
        if request_id not in self.active_orders:
            logger.warning(f"订单不存在或已完成: {request_id}")
            return False
        
        broker_order_id = self.active_orders[request_id]
        
        try:
            success = self.broker.cancel_order(broker_order_id)
            if success:
                self.pending_orders[request_id] = self.completed_orders.get(
                    request_id,
                    OrderRequest(symbol="", side="", quantity=0)
                )
                self.active_orders.pop(request_id, None)
                self.stats.cancelled_orders += 1
                
                if self.on_order_cancelled:
                    self.on_order_cancelled(request_id)
                
                logger.info(f"订单已取消: {request_id}")
            return success
            
        except Exception as e:
            logger.error(f"取消订单失败: {request_id}, 错误: {e}")
            return False
    
    def cancel_all(self) -> int:
        """
        取消所有活动订单
        
        Returns:
            取消的订单数量
        """
        count = 0
        for request_id in list(self.active_orders.keys()):
            if self.cancel_order(request_id):
                count += 1
        return count
    
    def retry_failed_orders(self):
        """重试失败的订单"""
        for request_id, request in list(self.pending_orders.items()):
            if hasattr(request, 'retry_count'):
                request.retry_count += 1
            else:
                request.retry_count = 1
            
            if request.retry_count <= self.max_retry:
                logger.info(f"重试订单: {request_id}, 第{request.retry_count}次")
                self.submit_order(request)
            else:
                logger.warning(f"订单重试次数超限: {request_id}")
                self._handle_rejected(request, request_id, "重试次数超限")
    
    def get_order_status(self, request_id: str) -> str:
        """获取订单状态"""
        if request_id in self.pending_orders:
            return "pending"
        elif request_id in self.active_orders:
            broker_order = self.broker.get_order(self.active_orders[request_id])
            if broker_order:
                return broker_order.status.value
            return "unknown"
        elif request_id in self.completed_orders:
            return "completed"
        return "not_found"
    
    def get_pending_orders(self) -> List[OrderRequest]:
        """获取待提交订单"""
        return list(self.pending_orders.values())
    
    def get_active_orders(self) -> List[Dict]:
        """获取活动订单详情"""
        result = []
        for request_id, broker_order_id in self.active_orders.items():
            request = self.pending_orders.get(request_id)
            broker_order = self.broker.get_order(broker_order_id)
            if request and broker_order:
                result.append({
                    "request_id": request_id,
                    "broker_order_id": broker_order_id,
                    "symbol": request.symbol,
                    "side": request.side,
                    "quantity": request.quantity,
                    "filled_quantity": broker_order.filled_quantity,
                    "status": broker_order.status.value,
                    "create_time": request.create_time
                })
        return result
    
    def get_execution_stats(self) -> Dict:
        """获取执行统计"""
        return {
            "total_orders": self.stats.total_orders,
            "filled_orders": self.stats.filled_orders,
            "cancelled_orders": self.stats.cancelled_orders,
            "rejected_orders": self.stats.rejected_orders,
            "pending_orders": len(self.pending_orders),
            "active_orders": len(self.active_orders),
            "total_quantity": self.stats.total_quantity,
            "filled_quantity": self.stats.filled_quantity,
            "fill_rate": self.stats.filled_quantity / max(self.stats.total_quantity, 1),
            "avg_slippage": self.stats.avg_slippage,
            "total_commission": self.stats.total_commission
        }
    
    def generate_trade_report(self) -> pd.DataFrame:
        """生成交易报告"""
        trades = self.broker.get_trades()
        
        if not trades:
            return pd.DataFrame()
        
        records = []
        for trade in trades:
            records.append({
                "trade_id": trade.trade_id,
                "order_id": trade.order_id,
                "symbol": trade.symbol,
                "side": trade.side.value,
                "price": trade.price,
                "quantity": trade.quantity,
                "trade_value": trade.price * trade.quantity,
                "commission": trade.commission,
                "trade_time": trade.trade_time
            })
        
        df = pd.DataFrame(records)
        
        if not df.empty:
            df = df.sort_values("trade_time")
            df["cumulative_value"] = df["trade_value"].cumsum()
            df["cumulative_commission"] = df["commission"].cumsum()
        
        return df
