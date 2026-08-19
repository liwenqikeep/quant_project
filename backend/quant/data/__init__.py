"""
数据模块

包含数据获取、处理、存储等功能
"""
# 惰性导入，避免在测试时触发可选依赖
__all__ = ["DataFetcher", "DataProcessor", "DataStorage",
           "BaseDataSource", "AkshareAdapter", "TushareAdapter"]

def __getattr__(name):
    if name == "DataFetcher":
        from .fetcher import DataFetcher
        return DataFetcher
    elif name == "DataProcessor":
        from .processor import DataProcessor
        return DataProcessor
    elif name == "DataStorage":
        from .storage import DataStorage
        return DataStorage
    elif name == "BaseDataSource":
        from .base_data_source import BaseDataSource
        return BaseDataSource
    elif name == "AkshareAdapter":
        from .base_data_source import AkshareAdapter
        return AkshareAdapter
    elif name == "TushareAdapter":
        from .base_data_source import TushareAdapter
        return TushareAdapter
    raise AttributeError(f"module 'data' has no attribute '{name}'")
