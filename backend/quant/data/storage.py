"""
数据存储模块 - 薄封装层

将文件存储职责委托给 storage/ 模块
保留 DataStorage 作为向后兼容的入口
"""
from pathlib import Path
from typing import Optional
import pandas as pd

# 重新导出核心类（兼容旧代码）
from quant.storage.database import Database, StockData, TradeRecord
from quant.storage.data_cache import DataCache

__all__ = ['Database', 'StockData', 'TradeRecord', 'DataCache', 'DataStorage']


class DataStorage:
    """
    数据存储器（向后兼容封装）

    新代码建议直接使用 quant.storage.Database 或 quant.storage.DataCache
    """

    def __init__(self, storage_dir: str = "data"):
        from quant.utils.logger import logger
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "quant_data.db"
        self._db = Database(db_path=str(self.db_path))
        logger.info(f"数据存储器初始化，存储目录: {self.storage_dir}")

    def save_to_csv(
        self,
        df: pd.DataFrame,
        filename: str,
        subdir: str = "raw"
    ) -> str:
        """保存数据到CSV文件"""
        path = self.storage_dir / subdir / f"{filename}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path)
        return str(path)

    def load_from_csv(
        self,
        filename: str,
        subdir: str = "raw"
    ) -> pd.DataFrame:
        """从CSV文件加载数据"""
        path = self.storage_dir / subdir / f"{filename}.csv"
        if path.exists():
            return pd.read_csv(path)
        raise FileNotFoundError(f"文件不存在: {path}")
