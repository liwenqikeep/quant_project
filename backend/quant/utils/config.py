"""
配置管理工具 - 转发到 infrastructure.config_manager

注意：此文件保留用于向后兼容，新代码请使用 quant.config
"""
from quant.config import get_config, load_config, get_config_manager

__all__ = ['get_config', 'load_config', 'get_config_manager']
