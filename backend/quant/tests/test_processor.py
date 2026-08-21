"""
测试数据处理模块

覆盖：clean_data 不删行、process_stock_data 流程、winsorize 截尾行为
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from quant.data.processor import DataProcessor


def make_stock_df(dates, opens, closes, highs, lows, volumes, amounts):
    """构造规范列股票 DataFrame"""
    return pd.DataFrame(
        {
            "open": opens,
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": volumes,
            "amount": amounts,
        },
        index=pd.to_datetime(dates),
    )


class TestCleanData:
    """数据清洗不删行"""

    def test_clean_data_row_count_unchanged(self):
        """清洗前后行数不变"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03", "2024-01-04"],
            opens=[100.0, 101.0, 102.0],
            closes=[101.0, 102.0, 103.0],
            highs=[102.0, 103.0, 104.0],
            lows=[99.0, 100.0, 101.0],
            volumes=[10000, 11000, 12000],
            amounts=[1e6, 1.1e6, 1.2e6],
        )
        result = processor.clean_data(df)
        assert len(result) == len(df)
        assert list(result.index) == list(df.index)

    def test_clean_data_index_unchanged(self):
        """清洗前后 index 不变"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03"],
            opens=[100.0, 101.0],
            closes=[101.0, 100.0],
            highs=[102.0, 102.0],
            lows=[99.0, 99.5],
            volumes=[10000, 11000],
            amounts=[1e6, 1.1e6],
        )
        result = processor.clean_data(df)
        assert result.index.equals(df.index)

    def test_clean_data_invalid_close_replaced_with_nan(self):
        """非法收盘价（<=0）替换为 NaN，不删行"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03"],
            opens=[100.0, 101.0],
            closes=[-10.0, 102.0],  # 非法
            highs=[102.0, 103.0],
            lows=[99.0, 100.0],
            volumes=[10000, 11000],
            amounts=[1e6, 1.1e6],
        )
        result = processor.clean_data(df)
        assert len(result) == 2
        assert pd.isna(result.loc["2024-01-02", "close"])
        assert result.loc["2024-01-03", "close"] == 102.0

    def test_clean_data_invalid_volume_replaced_with_nan(self):
        """非法成交量（<0）替换为 NaN，不删行"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03"],
            opens=[100.0, 101.0],
            closes=[101.0, 102.0],
            highs=[102.0, 103.0],
            lows=[99.0, 100.0],
            volumes=[-100.0, 11000],  # 非法
            amounts=[1e6, 1.1e6],
        )
        result = processor.clean_data(df)
        assert len(result) == 2
        assert pd.isna(result.loc["2024-01-02", "volume"])
        assert result.loc["2024-01-03", "volume"] == 11000

    def test_clean_data_all_legal_unchanged(self):
        """全合法数据保持不变"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03"],
            opens=[100.0, 101.0],
            closes=[102.0, 100.0],
            highs=[103.0, 102.0],
            lows=[99.0, 99.5],
            volumes=[10000, 11000],
            amounts=[1e6, 1.1e6],
        )
        result = processor.clean_data(df)
        assert len(result) == 2
        assert result.loc["2024-01-02", "close"] == 102.0


class TestProcessStockData:
    """完整数据处理流程"""

    def test_process_stock_data_order(self):
        """流程顺序：clean -> add_indicators -> add_features"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03"],
            opens=[100.0, 101.0],
            closes=[102.0, 100.0],
            highs=[103.0, 102.0],
            lows=[99.0, 99.5],
            volumes=[10000, 11000],
            amounts=[1e6, 1.1e6],
        )
        result = processor.process_stock_data(df)
        # 验证添加了指标列
        assert "MA5" in result.columns
        assert "MA10" in result.columns
        assert "vol_ratio" in result.columns
        # 行数不变
        assert len(result) == len(df)

    def test_process_stock_data_skip_clean(self):
        """跳过清洗时仍添加指标"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03"],
            opens=[100.0, 101.0],
            closes=[102.0, 100.0],
            highs=[103.0, 102.0],
            lows=[99.0, 99.5],
            volumes=[10000, 11000],
            amounts=[1e6, 1.1e6],
        )
        result = processor.process_stock_data(df, clean=False)
        assert "MA5" in result.columns
        assert len(result) == len(df)

    def test_process_stock_data_skip_indicators(self):
        """跳过指标时仍清洗"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03"],
            opens=[100.0, 101.0],
            closes=[-10.0, 102.0],  # 非法
            highs=[103.0, 103.0],
            lows=[99.0, 100.0],
            volumes=[10000, 11000],
            amounts=[1e6, 1.1e6],
        )
        result = processor.process_stock_data(df, add_indicators=False)
        assert len(result) == 2
        assert pd.isna(result.loc["2024-01-02", "close"])


class TestAddVolumeFeatures:
    """成交量特征"""

    def test_add_volume_features_standalone(self):
        """单独调用 add_volume_features 不依赖外部 VOL_MA5"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"],
            opens=[100.0] * 5,
            closes=[102.0, 100.0, 103.0, 101.0, 104.0],
            highs=[103.0] * 5,
            lows=[99.0] * 5,
            volumes=[10000.0, 11000.0, 12000.0, 13000.0, 14000.0],
            amounts=[1e6, 1.1e6, 1.2e6, 1.3e6, 1.4e6],
        )
        result = processor.add_volume_features(df)
        assert "vol_ratio" in result.columns
        assert "amount_change" in result.columns
        assert "vwap" in result.columns
        # VOL_MA5 应该被自动计算
        assert "VOL_MA5" in result.columns


class TestWinsorizeReturns:
    """收益率截尾"""

    def test_winsorize_returns_adds_columns(self):
        """winsorize_returns 添加截尾收益率列"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03", "2024-01-04"],
            opens=[100.0, 102.0, 104.0],
            closes=[102.0, 104.0, 106.0],
            highs=[103.0, 105.0, 107.0],
            lows=[99.0, 101.0, 103.0],
            volumes=[10000, 11000, 12000],
            amounts=[1e6, 1.1e6, 1.2e6],
        )
        result = processor.winsorize_returns(df)
        assert "return_winsorized" in result.columns
        assert "return_outlier" in result.columns

    def test_winsorize_returns_row_count_unchanged(self):
        """winsorize_returns 不改变行数"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03"],
            opens=[100.0, 102.0],
            closes=[102.0, 104.0],
            highs=[103.0, 105.0],
            lows=[99.0, 101.0],
            volumes=[10000, 11000],
            amounts=[1e6, 1.1e6],
        )
        result = processor.winsorize_returns(df)
        assert len(result) == len(df)


class TestSplitTrainTest:
    """训练测试集分割"""

    def test_split_train_test_preserves_order(self):
        """分割保持时间顺序（不随机打乱）"""
        processor = DataProcessor()
        df = make_stock_df(
            ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"],
            opens=[100.0, 101.0, 102.0, 103.0, 104.0],
            closes=[102.0, 100.0, 103.0, 101.0, 104.0],
            highs=[103.0, 102.0, 104.0, 104.0, 105.0],
            lows=[99.0, 99.5, 100.0, 100.5, 103.0],
            volumes=[10000, 11000, 12000, 13000, 14000],
            amounts=[1e6, 1.1e6, 1.2e6, 1.3e6, 1.4e6],
        )
        train, test = processor.split_train_test(df, test_size=0.4)
        # 训练集在前，测试集在后，保持时间顺序
        assert train.index[-1] < test.index[0]
        assert len(train) == 3
        assert len(test) == 2
