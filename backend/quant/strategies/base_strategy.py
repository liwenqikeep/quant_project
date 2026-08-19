"""
策略基类
所有策略都应继承此类
"""
from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Optional

class BaseStrategy(ABC):
    """策略基类"""
    
    def __init__(self, name: str = "BaseStrategy"):
        self.name = name
        self.position = 0  # 当前持仓状态，1表示持有，0表示空仓
        self.signals = pd.DataFrame()
    
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            data: 包含OHLCV数据的DataFrame
        
        Returns:
            DataFrame，包含 'signal' 列（1=买入，-1=卖出，0=持有）
        """
        pass
    
    def on_bar(self, bar: pd.Series) -> int:
        """
        每根K线执行的逻辑
        
        Args:
            bar: 当前K线数据
        
        Returns:
            交易信号：1=买入，-1=卖出，0=持有
        """
        return 0
    
    def reset(self):
        """重置策略状态"""
        self.position = 0
        self.signals = pd.DataFrame()
    
    def __repr__(self):
        return f"{self.name}(position={self.position})"
