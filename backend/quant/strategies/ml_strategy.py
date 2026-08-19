"""
机器学习量化策略
使用机器学习模型预测涨跌并生成信号
"""
import pandas as pd
import numpy as np
from typing import Optional
from pathlib import Path
import pickle
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
from sklearn.preprocessing import StandardScaler

from quant.strategies.base_strategy import BaseStrategy
from quant.utils.logger import logger

class MLStrategy(BaseStrategy):
    """机器学习量化策略"""
    
    def __init__(
        self,
        model_type: str = "gbdt",
        target_col: str = "return",
        lookback: int = 5,
        name: str = "MLStrategy"
    ):
        """
        初始化机器学习策略
        
        Args:
            model_type: 模型类型，"rf"=随机森林，"gbdt"=梯度提升
            target_col: 目标变量列名
            lookback: 历史数据回看窗口
        """
        super().__init__(name=name)
        self.model_type = model_type
        self.target_col = target_col
        self.lookback = lookback
        
        self.model = None
        self.scaler = None
        self.feature_cols = []
        
        logger.info(f"机器学习策略初始化: 模型={model_type}, 回看窗口={lookback}")
    
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        准备机器学习特征
        
        Args:
            df: 原始数据
        
        Returns:
            特征处理后的DataFrame
        """
        data = df.copy()
        
        # 目标变量：次日涨跌（1=涨，0=跌）
        data["target"] = (data["close"].shift(-1) > data["close"]).astype(int)
        
        # 生成特征
        feature_df = pd.DataFrame(index=data.index)
        
        # 价格动量特征
        for i in range(1, self.lookback + 1):
            feature_df[f"return_{i}d"] = data["close"].pct_change(i)
        
        # 波动率特征
        feature_df["volatility_5d"] = data["close"].pct_change().rolling(5).std()
        feature_df["volatility_20d"] = data["close"].pct_change().rolling(20).std()
        
        # 成交量特征
        if "volume" in data.columns:
            feature_df["volume_ratio"] = data["volume"] / data["volume"].rolling(5).mean()
        
        # 技术指标特征（如果有）
        if "RSI" in data.columns:
            feature_df["RSI"] = data["RSI"]
        
        if "MACD" in data.columns:
            feature_df["MACD"] = data["MACD"]
            feature_df["MACD_signal"] = data.get("MACD_signal", 0)
        
        # 移动平均线特征
        for window in [5, 10, 20]:
            if f"MA{window}" in data.columns:
                feature_df[f"MA{window}_ratio"] = data["close"] / data[f"MA{window}"] - 1
        
        # 删除含有NaN的行
        feature_df = feature_df.dropna()
        
        # 记录特征列名
        self.feature_cols = feature_df.columns.tolist()
        
        # 对齐目标变量
        target = data["target"].loc[feature_df.index]
        
        return feature_df, target
    
    def train(
        self, 
        df: pd.DataFrame,
        test_size: float = 0.2
    ) -> dict:
        """
        训练模型
        
        Args:
            df: 训练数据
            test_size: 测试集比例
        
        Returns:
            训练结果字典
        """
        logger.info("开始训练机器学习模型")
        
        # 准备特征
        X, y = self.prepare_features(df)
        
        # 分割数据（修复边界标签泄漏：切分点两侧各丢弃一天）
        split = int(len(X) * (1 - test_size))
        X_train, X_test = X.iloc[:split - 1], X.iloc[split + 1:]
        y_train, y_test = y.iloc[:split - 1], y.iloc[split + 1:]
        
        # 标准化
        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # 选择模型
        if self.model_type == "rf":
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=42,
                n_jobs=-1
            )
        else:  # gbdt
            self.model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=42
            )
        
        # 训练
        self.model.fit(X_train_scaled, y_train)
        
        # 预测
        y_pred = self.model.predict(X_test_scaled)
        
        # 评估
        results = {
            "accuracy": accuracy_score(y_test, y_pred),
            "classification_report": classification_report(y_test, y_pred),
            "train_size": len(X_train),
            "test_size": len(X_test),
            "n_features": len(self.feature_cols)
        }
        
        logger.info(f"模型训练完成，准确率: {results['accuracy']:.4f}")
        logger.info(f"\n{results['classification_report']}")
        
        return results
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            data: 包含OHLCV数据的DataFrame
        
        Returns:
            DataFrame，包含信号列
        """
        if self.model is None:
            logger.warning("模型未训练，使用默认信号")
            return pd.DataFrame({"signal": 0})
        
        df = data.copy()
        
        # 准备特征
        X, _ = self.prepare_features(df)
        
        # 确保特征列顺序一致
        X = X[self.feature_cols]
        
        # 标准化
        X_scaled = self.scaler.transform(X)
        
        # 预测
        predictions = self.model.predict(X_scaled)
        probabilities = self.model.predict_proba(X_scaled)[:, 1]
        
        # 生成信号
        df_result = df.loc[X.index].copy()
        df_result["prediction"] = predictions
        df_result["probability"] = probabilities
        
        # 预测为涨且概率>0.55时买入
        df_result["signal"] = 0
        df_result.loc[(predictions == 1) & (probabilities > 0.55), "signal"] = 1
        df_result.loc[(predictions == 0) & (probabilities < 0.45), "signal"] = -1
        
        # 持仓状态 - 使用 where().ffill() 替代已废弃的 replace(method="ffill")
        df_result["position"] = df_result["signal"].where(df_result["signal"] != 0).ffill().fillna(0).astype(int)
        
        logger.info(f"ML策略信号生成完成，信号分布: \n{df_result['signal'].value_counts()}")
        
        return df_result
    
    def save_model(self, path: str):
        """保存模型"""
        model_data = {
            "model": self.model,
            "scaler": self.scaler,
            "feature_cols": self.feature_cols,
            "model_type": self.model_type,
            "lookback": self.lookback
        }
        
        with open(path, "wb") as f:
            pickle.dump(model_data, f)
        
        logger.info(f"模型已保存: {path}")
    
    def load_model(self, path: str):
        """加载模型"""
        with open(path, "rb") as f:
            model_data = pickle.load(f)
        
        self.model = model_data["model"]
        self.scaler = model_data["scaler"]
        self.feature_cols = model_data["feature_cols"]
        self.model_type = model_data["model_type"]
        self.lookback = model_data["lookback"]
        
        logger.info(f"模型已加载: {path}")
    
    def get_feature_importance(self) -> pd.DataFrame:
        """获取特征重要性"""
        if self.model is None:
            return pd.DataFrame()
        
        importance = pd.DataFrame({
            "feature": self.feature_cols,
            "importance": self.model.feature_importances_
        }).sort_values("importance", ascending=False)
        
        return importance
