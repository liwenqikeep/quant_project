"""
配置管理工具 - 惰性加载
"""
from pathlib import Path
from typing import Any, Dict, Optional

# 尝试导入 yaml，失败则使用替代方案
_yaml_available = False
try:
    import yaml
    _yaml_available = True
except ImportError:
    yaml = None

class Config:
    """配置管理类"""

    _instance: Optional['Config'] = None
    _config: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._config:
            self.load()

    def load(self, config_path: str = "config.yaml"):
        """加载配置文件"""
        if not _yaml_available:
            # yaml 不可用，使用空配置
            self._config = {}
            return

        path = Path(config_path)
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f) or {}
        else:
            # 配置文件不存在，使用空配置
            self._config = {}

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项，支持点号分隔的路径

        Args:
            key: 配置键，如 "data.raw_data_path"
            default: 默认值
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __repr__(self):
        return f"Config({self._config})"


# 全局配置实例 - 延迟初始化
def _get_config():
    """获取配置实例"""
    return Config()

# 不在模块加载时创建实例，让使用方决定何时初始化
# config = Config()  # 注释掉，延迟初始化
