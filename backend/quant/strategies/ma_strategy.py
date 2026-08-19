"""
双均线策略
金叉买入，死叉卖出
"""
import pandas as pd
import numpy as np
from typing import Optional
from .base_strategy import BaseStrategy
from quant.utils.logger import logger

class MAStrategy(BaseStrategy):
    """双均线策略"""
    
    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        name: str = "MAStrategy"
    ):
        """
        初始化双均线策略
        
        Args:
            short_window: 短期均线窗口
            long_window: 长期均线窗口
        """
        super().__init__(name=name)
        self.short_window = short_window
        self.long_window = long_window
        
        logger.info(f"双均线策略初始化: 短期={short_window}, 长期={long_window}")
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            data: 包含OHLCV数据的DataFrame
        
        Returns:
            DataFrame，包含信号列
        """
        df = data.copy()
        
        # 计算均线
        df["MA_short"] = df["close"].rolling(window=self.short_window).mean()
        df["MA_long"] = df["close"].rolling(window=self.long_window).mean()
        
        # 生成信号
        # 1 = 金叉（短期上穿长期）= 买入
        # -1 = 死叉（短期下穿长期）= 卖出
        # 0 = 持有
        
        df["signal"] = 0
        
        # 金叉：短期均线从下方穿越长期均线
        gold_cross = (df["MA_short"] > df["MA_long"]) & \
                     (df["MA_short"].shift(1) <= df["MA_long"].shift(1))
        
        # 死叉：短期均线从上方穿越长期均线
        dead_cross = (df["MA_short"] < df["MA_long"]) & \
                     (df["MA_short"].shift(1) >= df["MA_long"].shift(1))
        
        df.loc[gold_cross, "signal"] = 1
        df.loc[dead_cross, "signal"] = -1
        
        # 持仓状态（用于模拟持仓）- 使用 where().ffill() 替代已废弃的 replace(method="ffill")
        df["position"] = df["signal"].where(df["signal"] != 0).ffill().fillna(0).astype(int)
        
        logger.info(f"信号生成完成，买入信号: {(df['signal']==1).sum()}, 卖出信号: {(df['signal']==-1).sum()}")
        
        return df[["close", "MA_short", "MA_long", "signal", "position"]]
    
    def get_params(self) -> dict:
        """获取策略参数"""
        return {
            "short_window": self.short_window,
            "long_window": self.long_window
        }
