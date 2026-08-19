"""
量化框架配置入口

统一管理配置加载与分发
"""
from pathlib import Path
from quant.utils.logger import logger

# 配置管理器实例（全局单例）
_config_manager = None

def get_config_manager():
    """
    获取配置管理器实例（延迟初始化）
    
    Returns:
        ConfigManager 实例
    """
    global _config_manager
    if _config_manager is None:
        from quant.infrastructure.config_manager import ConfigManager
        
        # 查找配置文件
        config_paths = [
            Path("config.yaml"),
            Path("../config.yaml"),
            Path(__file__).parent.parent / "config.yaml",
        ]
        
        config_file = None
        for path in config_paths:
            if path.exists():
                config_file = str(path)
                break
        
        _config_manager = ConfigManager(config_file=config_file)
        
        if config_file:
            logger.info(f"配置已加载: {config_file}")
        else:
            logger.warning("未找到 config.yaml，使用默认配置")
    
    return _config_manager


def get_config(key: str, default=None):
    """
    获取配置值（快捷方法）
    
    Args:
        key: 配置键，支持点号分隔，如 "strategy.initial_cash"
        default: 默认值
    
    Returns:
        配置值
    """
    return get_config_manager().get(key, default)


def load_config(config_file: str = None):
    """
    显式加载配置文件
    
    Args:
        config_file: 配置文件路径
    
    Returns:
        是否加载成功
    """
    global _config_manager
    from quant.infrastructure.config_manager import ConfigManager
    
    _config_manager = ConfigManager(config_file=config_file)
    return _config_manager is not None
