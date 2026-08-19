"""
日志工具 - 惰性加载版本
"""
import sys
import logging
from pathlib import Path
from typing import Optional

# 标准库 logging 作为后备
_std_logger: Optional[logging.Logger] = None
_is_loguru_available = False
_loguru_logger = None

def _init_std_logger():
    """初始化标准库日志作为后备"""
    global _std_logger
    if _std_logger is None:
        _std_logger = logging.getLogger("quant")
        _std_logger.setLevel(logging.INFO)

        # 控制台输出
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s'
        )
        handler.setFormatter(formatter)
        _std_logger.addHandler(handler)

        # 文件输出
        log_path = Path("logs")
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path / "quant.log")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        _std_logger.addHandler(file_handler)

    return _std_logger

def _try_init_loguru():
    """尝试初始化 loguru"""
    global _is_loguru_available, _loguru_logger
    if _loguru_logger is not None:
        return _loguru_logger

    try:
        from loguru import logger as _lr
        _is_loguru_available = True
        _loguru_logger = _lr

        # 配置 loguru
        _lr.remove()

        # 控制台输出
        _lr.add(
            sys.stdout,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            level="INFO",
            colorize=True
        )

        # 文件输出
        log_path = Path("logs")
        log_path.mkdir(parents=True, exist_ok=True)
        _lr.add(
            log_path / "quant_{time:YYYY-MM-DD}.log",
            rotation="100 MB",
            retention="30 days",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            level="INFO"
        )

        return _lr
    except Exception:
        _is_loguru_available = False
        return None

class LazyLogger:
    """惰性日志包装器"""

    def __init__(self):
        self._logger = None

    def _get_logger(self):
        if self._logger is None:
            # 优先使用 loguru
            self._logger = _try_init_loguru()
            if self._logger is None:
                # 使用标准库
                self._logger = _init_std_logger()
        return self._logger

    def __getattr__(self, name):
        return getattr(self._get_logger(), name)

    def __call__(self, *args, **kwargs):
        return self._get_logger()(*args, **kwargs)

    def info(self, msg, *args, **kwargs):
        return self._get_logger().info(msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        return self._get_logger().debug(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        return self._get_logger().warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        return self._get_logger().error(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        return self._get_logger().critical(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        return self._get_logger().exception(msg, *args, **kwargs)


# 全局惰性 logger 实例
logger = LazyLogger()

def setup_logger(log_dir: str = "logs", level: str = "INFO"):
    """配置日志系统"""
    # 重新配置
    global logger, _loguru_logger
    _loguru_logger = None  # 重置以便重新初始化

    # 设置日志级别
    logging.getLogger("quant").setLevel(getattr(logging, level.upper(), logging.INFO))

    return logger
