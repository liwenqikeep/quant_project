"""
配置管理模块
支持YAML/JSON配置、动态配置更新、配置验证
"""
import pandas as pd
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from pathlib import Path
import json
import yaml
import copy
from quant.utils.logger import logger


@dataclass
class ConfigSchema:
    """配置模式"""
    name: str
    type: str  # "str", "int", "float", "bool", "list", "dict"
    default: Any = None
    description: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    options: Optional[List[Any]] = None  # 枚举选项


class ConfigManager:
    """配置管理器"""
    
    def __init__(
        self,
        config_file: Optional[str] = None,
        auto_save: bool = True
    ):
        """
        初始化配置管理器
        
        Args:
            config_file: 配置文件路径
            auto_save: 是否自动保存
        """
        self.config_file = config_file
        self.auto_save = auto_save
        self.config: Dict = {}
        self.config_history: List[Dict] = []
        
        # 配置模式定义
        self.schemas: Dict[str, List[ConfigSchema]] = {}
        
        # 如果有配置文件，则加载
        if config_file and Path(config_file).exists():
            self.load_config(config_file)
        else:
            self._init_default_config()
        
        logger.info(f"配置管理器初始化: 文件={config_file}, 自动保存={auto_save}")
    
    def _validate_required_keys(self):
        """验证必填配置键"""
        required_keys = [
            "strategy.initial_cash",
            "strategy.commission",
            "strategy.stamp_tax",
            "data.data_dir",
            "data.tmp_dir",
            "data.raw_dir",
            "data.processed_dir"
        ]
        
        missing = []
        for key in required_keys:
            if self.get(key) is None:
                missing.append(key)
        
        if missing:
            logger.warning(f"配置缺失必填键: {missing}")
        else:
            logger.info("配置必填键校验通过")
        
        return missing
    
    def _init_default_config(self):
        """初始化默认配置（与 config.yaml 结构一致）"""
        self.config = {
            "system": {
                "name": "量化交易系统",
                "version": "1.0.0",
                "log_level": "INFO"
            },
            "data": {
                "data_dir": "data",
                "tmp_dir": "tmp",
                "raw_dir": "raw",
                "processed_dir": "processed",
                "sources": {
                    "default": "akshare",
                    "akshare": {"enabled": True},
                    "tushare": {"enabled": False, "token": ""}
                }
            },
            "strategy": {
                "initial_cash": 1000000,
                "commission": 0.0003,
                "stamp_tax": 0.0005,
                "slippage": 0.0,
                "min_commission": 5.0,
                "min_commission_enabled": True,
                "execution_price": "next_open",
                "backtest_start": "20200101",
                "backtest_end": "20231231"
            },
            "risk": {
                "commission": 0.0003,
                "stamp_tax": 0.0005,
                "slippage": 0.0,
                "max_position_per_stock": 0.2,
                "max_position_total": 0.9,
                "max_drawdown": 0.15,
                "max_single_trade_ratio": 0.1
            },
            "api": {
                "host": "0.0.0.0",
                "port": 5000,
                "debug": False
            }
        }
        
        # 验证必填配置
        self._validate_required_keys()
    
    def load_config(self, config_file: str) -> bool:
        """加载配置文件"""
        path = Path(config_file)
        
        if not path.exists():
            logger.warning(f"配置文件不存在: {config_file}")
            return False
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                if path.suffix in ['.yaml', '.yml']:
                    self.config = yaml.safe_load(f)
                elif path.suffix == '.json':
                    self.config = json.load(f)
                else:
                    logger.error(f"不支持的配置文件格式: {path.suffix}")
                    return False
            
            self.config_file = config_file
            self._validate_required_keys()
            logger.info(f"配置文件已加载: {config_file}")
            return True
            
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return False
    
    def save_config(self, config_file: Optional[str] = None) -> bool:
        """保存配置文件"""
        path = Path(config_file or self.config_file)
        
        if not path:
            logger.error("未指定配置文件路径")
            return False
        
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, 'w', encoding='utf-8') as f:
                if path.suffix in ['.yaml', '.yml']:
                    yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
                elif path.suffix == '.json':
                    json.dump(self.config, f, ensure_ascii=False, indent=2)
                else:
                    yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
            
            logger.info(f"配置文件已保存: {path}")
            return True
            
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 配置键，支持点号分隔，如 "data.cache_enabled"
            default: 默认值
        
        Returns:
            配置值
        """
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any, auto_save: bool = True):
        """
        设置配置值
        
        Args:
            key: 配置键
            value: 配置值
            auto_save: 是否自动保存
        """
        # 保存历史
        self._save_history()
        
        keys = key.split('.')
        config = self.config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
        
        logger.debug(f"配置已更新: {key} = {value}")
        
        if self.auto_save and auto_save:
            self.save_config()
    
    def _save_history(self):
        """保存配置历史"""
        self.config_history.append(copy.deepcopy(self.config))
        
        # 限制历史长度
        if len(self.config_history) > 50:
            self.config_history = self.config_history[-50:]
    
    def undo(self) -> bool:
        """撤销上次配置更改"""
        if not self.config_history:
            logger.warning("没有可撤销的配置更改")
            return False
        
        self.config = self.config_history.pop()
        logger.info("配置已撤销")
        
        if self.auto_save:
            self.save_config()
        
        return True
    
    def get_all(self) -> Dict:
        """获取所有配置"""
        return copy.deepcopy(self.config)
    
    def update(self, updates: Dict, auto_save: bool = True):
        """
        批量更新配置
        
        Args:
            updates: 配置更新字典
            auto_save: 是否自动保存
        """
        self._save_history()
        
        self._deep_update(self.config, updates)
        
        logger.info(f"配置已批量更新")
        
        if self.auto_save and auto_save:
            self.save_config()
    
    def _deep_update(self, target: Dict, source: Dict):
        """深度更新字典"""
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value
    
    def register_schema(self, section: str, schemas: List[ConfigSchema]):
        """注册配置模式"""
        self.schemas[section] = schemas
        logger.info(f"配置模式已注册: {section}")
    
    def validate_config(self) -> List[str]:
        """验证配置"""
        errors = []
        
        for section, schemas in self.schemas.items():
            if section not in self.config:
                continue
            
            for schema in schemas:
                key = f"{section}.{schema.name}"
                value = self.get(key)
                
                if value is None and schema.default is not None:
                    errors.append(f"{key}: 缺少值，使用默认值 {schema.default}")
                    continue
                
                if value is None:
                    continue
                
                # 类型检查
                expected_type = schema.type.lower()
                if expected_type == "int" and not isinstance(value, int):
                    errors.append(f"{key}: 期望 int 类型，实际 {type(value)}")
                elif expected_type == "float" and not isinstance(value, (int, float)):
                    errors.append(f"{key}: 期望 float 类型，实际 {type(value)}")
                elif expected_type == "str" and not isinstance(value, str):
                    errors.append(f"{key}: 期望 str 类型，实际 {type(value)}")
                elif expected_type == "bool" and not isinstance(value, bool):
                    errors.append(f"{key}: 期望 bool 类型，实际 {type(value)}")
                
                # 范围检查
                if schema.min_value is not None and value < schema.min_value:
                    errors.append(f"{key}: 值 {value} 小于最小值 {schema.min_value}")
                if schema.max_value is not None and value > schema.max_value:
                    errors.append(f"{key}: 值 {value} 大于最大值 {schema.max_value}")
                
                # 枚举检查
                if schema.options and value not in schema.options:
                    errors.append(f"{key}: 值 {value} 不在选项 {schema.options} 中")
        
        if errors:
            for error in errors:
                logger.warning(f"配置验证: {error}")
        else:
            logger.info("配置验证通过")
        
        return errors
    
    def export_config(self, format: str = "json") -> str:
        """导出配置"""
        if format == "json":
            return json.dumps(self.config, ensure_ascii=False, indent=2)
        elif format == "yaml":
            return yaml.dump(self.config, allow_unicode=True, default_flow_style=False)
        else:
            raise ValueError(f"不支持的格式: {format}")


# 全局配置实例
_global_config: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    """获取全局配置实例"""
    global _global_config
    if _global_config is None:
        _global_config = ConfigManager()
    return _global_config
