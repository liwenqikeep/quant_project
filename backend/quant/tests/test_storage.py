"""
测试数据存储
"""
import pytest
import pandas as pd
import tempfile
import os
from pathlib import Path


class TestStorage:
    """存储测试"""

    def test_csv_write_read_roundtrip(self):
        """CSV读写往返一致性"""
        df = pd.DataFrame({
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "close": [100.0, 102.0, 101.5],
            "volume": [1000, 1500, 1200]
        })

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            temp_path = f.name
            df.to_csv(temp_path, index=False)

        try:
            df_read = pd.read_csv(temp_path)

            assert len(df_read) == len(df), "行数不一致"
            assert list(df_read.columns) == list(df.columns), "列名不一致"
            pd.testing.assert_frame_equal(df, df_read), "数据不一致"
        finally:
            os.unlink(temp_path)

    def test_csv_empty_dataframe(self):
        """空DataFrame处理"""
        df = pd.DataFrame()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            temp_path = f.name
            df.to_csv(temp_path, index=False)

        try:
            # 空CSV文件读取会报错，使用on_bad_lines跳过
            try:
                df_read = pd.read_csv(temp_path, on_bad_lines='skip')
                assert len(df_read) == 0, "读取空文件应为空DataFrame"
            except pd.errors.EmptyDataError:
                # 空文件抛出EmptyDataError是预期行为
                pass
        finally:
            os.unlink(temp_path)

    def test_csv_with_nan(self):
        """含NaN值的数据"""
        df = pd.DataFrame({
            "a": [1.0, None, 3.0],
            "b": [None, 2.0, 3.0]
        })

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            temp_path = f.name
            df.to_csv(temp_path, index=False)

        try:
            df_read = pd.read_csv(temp_path)
            # 验证NaN值被正确保留
            assert pd.isna(df_read.loc[1, "a"]), "NaN值应保留在第二行"
            assert pd.isna(df_read.loc[0, "b"]), "NaN值应保留在第一行"
        finally:
            os.unlink(temp_path)
