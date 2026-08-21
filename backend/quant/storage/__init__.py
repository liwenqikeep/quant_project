"""
数据存储模块
包含数据库操作、数据缓存、数据版本控制等功能
"""

from .data_cache import DataCache

__all__ = [
    "DataCache",
    "Database",
    "StockData",
    "TradeRecord",
]


def __getattr__(name: str):  # noqa: F401
    """延迟导入 Database/StockData/TradeRecord（仅在 SQLAlchemy 可用时）"""
    if name in ("Database", "StockData", "TradeRecord"):
        from .database import Database, StockData, TradeRecord  # noqa: F401

        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
