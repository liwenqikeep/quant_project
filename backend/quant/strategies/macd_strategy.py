"""
MACD 策略
MACD金叉买入，死叉卖出
"""
import pandas as pd
import numpy as np
from .base_strategy import BaseStrategy
from quant.utils.logger import logger

class MACDStrategy(BaseStrategy):
    """MACD 策略"""
    
    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        name: str = "MACDStrategy"
    ):
        """
        初始化MACD策略
        
        Args:
            fast_period: 快线周期
            slow_period: 慢线周期
            signal_period: 信号线周期
        """
        super().__init__(name=name)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        
        logger.info(f"MACD策略初始化: 快线={fast_period}, 慢线={slow_period}, 信号线={signal_period}")
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            data: 包含OHLCV数据的DataFrame
        
        Returns:
            DataFrame，包含信号列
        """
        df = data.copy()
        
        # 计算MACD
        ema_fast = df["close"].ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = df["close"].ewm(span=self.slow_period, adjust=False).mean()
        
        df["MACD"] = ema_fast - ema_slow
        df["MACD_signal"] = df["MACD"].ewm(span=self.signal_period, adjust=False).mean()
        df["MACD_hist"] = df["MACD"] - df["MACD_signal"]
        
        # 生成信号
        df["signal"] = 0
        
        # 金叉：MACD从下方穿越信号线
        gold_cross = (df["MACD"] > df["MACD_signal"]) & \
                     (df["MACD"].shift(1) <= df["MACD_signal"].shift(1))
        
        # 死叉：MACD从上方穿越信号线
        dead_cross = (df["MACD"] < df["MACD_signal"]) & \
                     (df["MACD"].shift(1) >= df["MACD_signal"].shift(1))
        
        df.loc[gold_cross, "signal"] = 1
        df.loc[dead_cross, "signal"] = -1
        
        # 持仓状态 - 使用 where().ffill() 替代已废弃的 replace(method="ffill")
        df["position"] = df["signal"].where(df["signal"] != 0).ffill().fillna(0).astype(int)
        
        logger.info(f"MACD策略信号生成完成，买入信号: {gold_cross.sum()}, 卖出信号: {dead_cross.sum()}")
        
        return df[["close", "MACD", "MACD_signal", "MACD_hist", "signal", "position"]]
    
    def get_params(self) -> dict:
        """获取策略参数"""
        return {
            "fast_period": self.fast_period,
            "slow_period": self.slow_period,
            "signal_period": self.signal_period
        }
