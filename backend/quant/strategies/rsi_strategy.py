"""
RSI 策略
RSI超卖买入，超买卖出
"""
import pandas as pd
import numpy as np
from .base_strategy import BaseStrategy
from quant.utils.logger import logger

class RSIStrategy(BaseStrategy):
    """RSI 策略"""
    
    def __init__(
        self,
        rsi_period: int = 14,
        oversold: int = 30,
        overbought: int = 70,
        name: str = "RSIStrategy"
    ):
        """
        初始化RSI策略
        
        Args:
            rsi_period: RSI计算周期
            oversold: 超卖阈值
            overbought: 超买阈值
        """
        super().__init__(name=name)
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        
        logger.info(f"RSI策略初始化: 周期={rsi_period}, 超卖={oversold}, 超买={overbought}")
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            data: 包含OHLCV数据的DataFrame
        
        Returns:
            DataFrame，包含信号列
        """
        df = data.copy()
        
        # 计算RSI（使用Wilder平滑，与通达信/同花顺口径一致）
        delta = df["close"].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/self.rsi_period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/self.rsi_period, adjust=False).mean()
        
        # 处理除零：loss为0时RSI应为100
        rs = gain / loss.replace(0, np.nan)
        df["RSI"] = (100 - 100 / (1 + rs)).fillna(100.0)
        
        # 生成信号
        df["signal"] = 0
        
        # RSI低于超卖阈值 -> 买入
        buy_signal = df["RSI"] < self.oversold
        
        # RSI高于超买阈值 -> 卖出
        sell_signal = df["RSI"] > self.overbought
        
        df.loc[buy_signal, "signal"] = 1
        df.loc[sell_signal, "signal"] = -1
        
        # 持仓状态 - 使用 where().ffill() 替代已废弃的 replace(method="ffill")
        df["position"] = df["signal"].where(df["signal"] != 0).ffill().fillna(0).astype(int)
        
        logger.info(f"RSI策略信号生成完成，买入信号: {buy_signal.sum()}, 卖出信号: {sell_signal.sum()}")
        
        return df[["close", "RSI", "signal", "position"]]
    
    def get_params(self) -> dict:
        """获取策略参数"""
        return {
            "rsi_period": self.rsi_period,
            "oversold": self.oversold,
            "overbought": self.overbought
        }
