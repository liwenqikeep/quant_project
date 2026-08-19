"""
数据处理模块
包含因子计算、数据清洗、特征工程等功能
"""
import pandas as pd
import numpy as np
from typing import List, Optional
from quant.utils.logger import logger

class DataProcessor:
    """数据处理器"""
    
    def __init__(self):
        logger.info("数据处理器初始化")
    
    @staticmethod
    def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        添加技术指标
        
        Args:
            df: 包含 OHLCV 数据的 DataFrame
        
        Returns:
            添加技术指标后的 DataFrame
        """
        logger.info("计算技术指标")
        
        df = df.copy()
        
        # 移动平均线
        for window in [5, 10, 20, 30, 60]:
            df[f"MA{window}"] = df["close"].rolling(window=window).mean()
        
        # 指数移动平均线
        for window in [12, 26]:
            df[f"EMA{window}"] = df["close"].ewm(span=window, adjust=False).mean()
        
        # MACD
        df["MACD"] = df["EMA12"] - df["EMA26"]
        df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_hist"] = df["MACD"] - df["MACD_signal"]
        
        # RSI（使用Wilder平滑，与通达信/同花顺口径一致）
        delta = df["close"].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        # 处理除零：loss为0时RSI应为100
        rs = gain / loss.replace(0, np.nan)
        df["RSI"] = (100 - 100 / (1 + rs)).fillna(100.0)
        
        # 布林带
        df["BOLL_MID"] = df["close"].rolling(window=20).mean()
        df["BOLL_STD"] = df["close"].rolling(window=20).std()
        df["BOLL_UPPER"] = df["BOLL_MID"] + 2 * df["BOLL_STD"]
        df["BOLL_LOWER"] = df["BOLL_MID"] - 2 * df["BOLL_STD"]
        
        # KDJ 指标
        low14 = df["low"].rolling(window=14).min()
        high14 = df["high"].rolling(window=14).max()
        # 处理除零：high14==low14时（涨跌停日），RSV填充50
        denom = (high14 - low14).replace(0, np.nan)
        df["RSV"] = ((df["close"] - low14) / denom * 100).fillna(50.0)
        df["K"] = df["RSV"].ewm(alpha=1/3, adjust=False).mean()
        df["D"] = df["K"].ewm(alpha=1/3, adjust=False).mean()
        df["J"] = 3 * df["K"] - 2 * df["D"]
        
        # 成交量指标
        df["VOL_MA5"] = df["volume"].rolling(window=5).mean()
        df["VOL_MA10"] = df["volume"].rolling(window=10).mean()
        
        # 涨跌停标记
        df["pct_change"] = df["close"].pct_change()
        
        logger.info(f"技术指标计算完成，共 {len([c for c in df.columns if c not in ['open', 'close', 'high', 'low', 'volume', 'amount']])} 个指标")
        
        return df
    
    @staticmethod
    def add_price_features(df: pd.DataFrame) -> pd.DataFrame:
        """
        添加价格特征
        
        Args:
            df: 包含 OHLCV 数据的 DataFrame
        
        Returns:
            添加价格特征后的 DataFrame
        """
        df = df.copy()
        
        # 日收益率
        df["return"] = df["close"].pct_change()
        
        # 累计收益率
        df["cumulative_return"] = (1 + df["return"]).cumprod() - 1
        
        # 价格波动率（20日年化）
        df["volatility_20"] = df["return"].rolling(window=20).std() * np.sqrt(252)
        
        # 最高价/最低价比率
        df["high_low_ratio"] = df["high"] / df["low"] - 1
        
        # 开盘价/收盘价比率
        df["open_close_ratio"] = df["open"] / df["close"] - 1
        
        # 上影线/下影线
        df["upper_shadow"] = (df["high"] - np.maximum(df["open"], df["close"])) / df["close"]
        df["lower_shadow"] = (np.minimum(df["open"], df["close"]) - df["low"]) / df["close"]
        
        return df
    
    @staticmethod
    def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
        """
        添加成交量特征
        
        Args:
            df: 包含成交量的 DataFrame
        
        Returns:
            添加成交量特征后的 DataFrame
        """
        df = df.copy()
        
        # 量比
        df["vol_ratio"] = df["volume"] / df["VOL_MA5"]
        
        # 成交额变化
        df["amount_change"] = df["amount"].pct_change()
        
        # 成交量加权价格
        df["vwap"] = df["amount"] / df["volume"]
        
        return df
    
    @staticmethod
    def clean_data(df: pd.DataFrame) -> pd.DataFrame:
        """
        数据清洗（不破坏时间序列）
        
        Args:
            df: 原始 DataFrame
        
        Returns:
            清洗后的 DataFrame
        """
        logger.info("开始数据清洗")
        
        df = df.copy()
        initial_len = len(df)
        
        # 处理缺失值
        df = df.dropna()
        logger.info(f"删除缺失值: {initial_len} -> {len(df)}")
        
        # 验证数据合法性（不删除行，只标记）
        # 检查价格是否为正数
        if "close" in df.columns:
            invalid_close = (df["close"] <= 0) | df["close"].isna()
            if invalid_close.any():
                logger.warning(f"发现 {invalid_close.sum()} 条非法收盘价")
                df = df[~invalid_close]
        
        # 检查成交量是否为非负数
        if "volume" in df.columns:
            invalid_volume = (df["volume"] < 0) | df["volume"].isna()
            if invalid_volume.any():
                logger.warning(f"发现 {invalid_volume.sum()} 条非法成交量")
                df = df[~invalid_volume]
        
        logger.info(f"数据清洗完成: {initial_len} -> {len(df)}")
        
        return df
    
    @staticmethod
    def winsorize_returns(df: pd.DataFrame, lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame:
        """
        对收益率进行截尾处理（不删除时间序列行）
        
        Args:
            df: DataFrame
            lower: 下分位数（默认1%）
            upper: 上分位数（默认99%）
        
        Returns:
            添加截尾收益率列的 DataFrame
        """
        df = df.copy()
        ret = df["close"].pct_change()
        lo, hi = ret.quantile(lower), ret.quantile(upper)
        df["return_winsorized"] = ret.clip(lo, hi)
        df["return_outlier"] = (ret < lo) | (ret > hi)  # 标记异常点
        return df
    
    @staticmethod
    def split_train_test(
        df: pd.DataFrame, 
        test_size: float = 0.2,
        date_col: str = "date"
    ) -> tuple:
        """
        按时间顺序分割训练集和测试集
        
        Args:
            df: 数据集
            test_size: 测试集比例
            date_col: 日期列名
        
        Returns:
            (train_df, test_df)
        """
        split_idx = int(len(df) * (1 - test_size))
        train = df.iloc[:split_idx].copy()
        test = df.iloc[split_idx:].copy()
        
        logger.info(f"数据分割: 训练集 {len(train)} 条, 测试集 {len(test)} 条")
        
        return train, test
    
    def process_stock_data(
        self, 
        df: pd.DataFrame,
        add_indicators: bool = True,
        add_features: bool = True,
        clean: bool = True
    ) -> pd.DataFrame:
        """
        完整的股票数据处理流程
        
        Args:
            df: 原始股票数据
            add_indicators: 是否添加技术指标
            add_features: 是否添加价格/成交量特征
            clean: 是否清洗数据
        
        Returns:
            处理后的 DataFrame
        """
        logger.info("开始完整数据处理流程")
        
        result = df.copy()
        
        if add_indicators:
            result = self.add_technical_indicators(result)
        
        if add_features:
            result = self.add_price_features(result)
            result = self.add_volume_features(result)
        
        if clean:
            result = self.clean_data(result)
        
        logger.info(f"数据处理完成，特征数量: {len(result.columns)}")
        
        return result
