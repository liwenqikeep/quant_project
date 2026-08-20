"""
数据模块

包含数据获取、处理、同步、存储等功能
"""
# 惰性导入，避免在测试时触发可选依赖
__all__ = [
    "DataFetcher",
    "DataProcessor",
    "DataStorage",
    "BaseDataSource",
    "AkshareAdapter",
    "TushareAdapter",
    # 新增组件
    "DataSyncService",
    "DataCalibrator",
    "DataFetchError",
    "AdjustType",
    "FetchStatus",
    "FetchOutcome",
    "BatchFetchReport",
    "DataCalibrationReport",
    "DailyBarDict",
    "FetchLogDict",
    "CalibrationIssueDict",
]

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
    elif name == "DataSyncService":
        from .sync import DataSyncService
        return DataSyncService
    elif name == "DataCalibrator":
        from .calibration import DataCalibrator
        return DataCalibrator
    elif name == "DataFetchError":
        from .errors import DataFetchError
        return DataFetchError
    elif name == "AdjustType":
        from .models import AdjustType
        return AdjustType
    elif name == "FetchStatus":
        from .models import FetchStatus
        return FetchStatus
    elif name == "FetchOutcome":
        from .models import FetchOutcome
        return FetchOutcome
    elif name == "BatchFetchReport":
        from .models import BatchFetchReport
        return BatchFetchReport
    elif name == "DataCalibrationReport":
        from .models import DataCalibrationReport
        return DataCalibrationReport
    elif name == "DailyBarDict":
        from .models import DailyBarDict
        return DailyBarDict
    elif name == "FetchLogDict":
        from .models import FetchLogDict
        return FetchLogDict
    elif name == "CalibrationIssueDict":
        from .models import CalibrationIssueDict
        return CalibrationIssueDict
    raise AttributeError(f"module 'data' has no attribute '{name}'")
