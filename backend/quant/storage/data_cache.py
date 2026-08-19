"""
数据缓存模块
内存缓存、磁盘缓存、LRU策略、过期管理
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
import json
import hashlib
import pickle
import time
import sys
from quant.utils.logger import logger


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    size_bytes: int = 0
    ttl_seconds: int = 3600  # 默认1小时


@dataclass
class CacheStats:
    """缓存统计"""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    total_size_bytes: int = 0
    entry_count: int = 0


class DataCache:
    """数据缓存"""
    
    def __init__(
        self,
        max_memory_mb: float = 500,
        cache_dir: Optional[str] = None,
        default_ttl: int = 3600,
        enable_disk_cache: bool = True
    ):
        """
        初始化数据缓存
        
        Args:
            max_memory_mb: 最大内存缓存大小（MB）
            cache_dir: 磁盘缓存目录
            default_ttl: 默认过期时间（秒）
            enable_disk_cache: 是否启用磁盘缓存
        """
        self.max_memory_bytes = int(max_memory_mb * 1024 * 1024)
        self.default_ttl = default_ttl
        self.enable_disk_cache = enable_disk_cache
        
        # 内存缓存
        self._memory_cache: Dict[str, CacheEntry] = {}
        self._current_memory_size = 0
        
        # 磁盘缓存
        if cache_dir is None:
            from quant.utils.paths import get_data_paths
            cache_dir = get_data_paths()['tmp'] / 'cache'
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 统计
        self.stats = CacheStats()
        
        # 回调函数
        self.on_cache_miss: Optional[Callable] = None
        
        logger.info(
            f"数据缓存初始化: 最大内存={max_memory_mb}MB, "
            f"默认TTL={default_ttl}秒, "
            f"磁盘缓存={'启用' if enable_disk_cache else '禁用'}"
        )
    
    def _generate_key(self, prefix: str, **kwargs) -> str:
        """
        生成缓存键
        
        Args:
            prefix: 键前缀
            **kwargs: 键参数
        
        Returns:
            缓存键
        """
        # 将参数转换为字符串并计算哈希
        params_str = json.dumps(kwargs, sort_keys=True, default=str)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()[:12]
        
        # 如果有日期参数，加入键中便于识别
        date_str = kwargs.get('date', kwargs.get('start_date', ''))
        if isinstance(date_str, datetime):
            date_str = date_str.strftime('%Y%m%d')
        
        return f"{prefix}:{date_str}:{params_hash}"
    
    def get(
        self,
        key: str,
        fetch_func: Optional[Callable] = None,
        ttl: Optional[int] = None
    ) -> Optional[Any]:
        """
        获取缓存
        
        Args:
            key: 缓存键
            fetch_func: 缓存未命中时的获取函数
            ttl: 过期时间（秒）
        
        Returns:
            缓存值
        """
        # 1. 先查内存缓存
        entry = self._memory_cache.get(key)
        if entry and not self._is_expired(entry, ttl or self.default_ttl):
            entry.last_accessed = datetime.now()
            entry.access_count += 1
            self.stats.hits += 1
            logger.debug(f"缓存命中(内存): {key}")
            return entry.value
        
        # 2. 查磁盘缓存
        if self.enable_disk_cache:
            disk_value = self._get_from_disk(key)
            if disk_value is not None:
                # 放回内存缓存
                self._put_to_memory(key, disk_value, ttl or self.default_ttl)
                self.stats.hits += 1
                logger.debug(f"缓存命中(磁盘): {key}")
                return disk_value
        
        # 3. 缓存未命中
        self.stats.misses += 1
        logger.debug(f"缓存未命中: {key}")
        
        # 如果提供了获取函数，则获取数据并缓存
        if fetch_func is not None:
            try:
                value = fetch_func()
                if value is not None:
                    self.put(key, value, ttl)
                return value
            except Exception as e:
                logger.error(f"获取数据失败: {key}, {e}")
                return None
        
        return None
    
    def put(self, key: str, value: Any, ttl: Optional[int] = None):
        """
        放入缓存
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
        """
        ttl = ttl or self.default_ttl
        
        # 放入内存缓存
        self._put_to_memory(key, value, ttl)
        
        # 同步到磁盘缓存
        if self.enable_disk_cache:
            self._put_to_disk(key, value)
    
    def _put_to_memory(self, key: str, value: Any, ttl: int):
        """放入内存缓存"""
        # 计算大小
        size = self._estimate_size(value)
        
        # 如果太大，直接跳过内存缓存
        if size > self.max_memory_bytes * 0.5:
            logger.warning(f"数据太大，跳过内存缓存: {key}, {size}bytes")
            return
        
        # 如果内存满了，清理空间
        while self._current_memory_size + size > self.max_memory_bytes:
            if not self._evict_lru():
                break
        
        # 删除旧条目
        if key in self._memory_cache:
            old_entry = self._memory_cache[key]
            self._current_memory_size -= old_entry.size_bytes
        
        # 添加新条目
        entry = CacheEntry(
            key=key,
            value=value,
            size_bytes=size,
            ttl_seconds=ttl
        )
        
        self._memory_cache[key] = entry
        self._current_memory_size += size
        self.stats.entry_count = len(self._memory_cache)
        self.stats.total_size_bytes = self._current_memory_size
        
        logger.debug(f"已缓存(内存): {key}, {size}bytes, TTL={ttl}s")
    
    def _evict_lru(self) -> bool:
        """清理最少使用的缓存"""
        if not self._memory_cache:
            return False
        
        # 找出最久未使用的
        lru_key = min(
            self._memory_cache.keys(),
            key=lambda k: self._memory_cache[k].last_accessed
        )
        
        entry = self._memory_cache.pop(lru_key)
        self._current_memory_size -= entry.size_bytes
        self.stats.evictions += 1
        self.stats.entry_count = len(self._memory_cache)
        
        logger.debug(f"LRU淘汰: {lru_key}")
        return True
    
    def _is_expired(self, entry: CacheEntry, ttl: int) -> bool:
        """检查是否过期"""
        age = (datetime.now() - entry.created_at).total_seconds()
        return age > ttl
    
    def _estimate_size(self, value: Any) -> int:
        """估算对象大小"""
        try:
            return len(pickle.dumps(value))
        except:
            return sys.getsizeof(value)
    
    def _get_from_disk(self, key: str) -> Optional[Any]:
        """从磁盘获取缓存"""
        cache_file = self.cache_dir / f"{hashlib.md5(key.encode()).hexdigest()}.pkl"
        
        if not cache_file.exists():
            return None
        
        try:
            # 检查过期
            meta_file = cache_file.with_suffix('.meta')
            if meta_file.exists():
                with open(meta_file, 'r') as f:
                    meta = json.load(f)
                
                created_at = datetime.fromisoformat(meta['created_at'])
                if (datetime.now() - created_at).total_seconds() > meta.get('ttl', self.default_ttl):
                    # 已过期，删除
                    cache_file.unlink()
                    meta_file.unlink()
                    return None
            
            # 读取数据
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
                
        except Exception as e:
            logger.error(f"读取磁盘缓存失败: {key}, {e}")
            return None
    
    def _put_to_disk(self, key: str, value: Any):
        """放入磁盘缓存"""
        cache_file = self.cache_dir / f"{hashlib.md5(key.encode()).hexdigest()}.pkl"
        meta_file = cache_file.with_suffix('.meta')
        
        try:
            # 保存数据
            with open(cache_file, 'wb') as f:
                pickle.dump(value, f)
            
            # 保存元数据
            meta = {
                'key': key,
                'created_at': datetime.now().isoformat(),
                'ttl': self.default_ttl,
                'size': self._estimate_size(value)
            }
            with open(meta_file, 'w') as f:
                json.dump(meta, f)
                
        except Exception as e:
            logger.error(f"写入磁盘缓存失败: {key}, {e}")
    
    def delete(self, key: str):
        """删除缓存"""
        # 删除内存缓存
        if key in self._memory_cache:
            entry = self._memory_cache.pop(key)
            self._current_memory_size -= entry.size_bytes
        
        # 删除磁盘缓存
        if self.enable_disk_cache:
            cache_file = self.cache_dir / f"{hashlib.md5(key.encode()).hexdigest()}.pkl"
            meta_file = cache_file.with_suffix('.meta')
            cache_file.unlink(missing_ok=True)
            meta_file.unlink(missing_ok=True)
    
    def clear(self):
        """清空所有缓存"""
        # 清空内存缓存
        self._memory_cache.clear()
        self._current_memory_size = 0
        
        # 清空磁盘缓存
        if self.enable_disk_cache:
            for cache_file in self.cache_dir.glob("*.pkl"):
                cache_file.unlink()
            for meta_file in self.cache_dir.glob("*.meta"):
                meta_file.unlink()
        
        logger.info("缓存已清空")
    
    def cleanup_expired(self):
        """清理过期缓存"""
        # 清理内存缓存
        expired_keys = [
            k for k, v in self._memory_cache.items()
            if self._is_expired(v, v.ttl_seconds)
        ]
        
        for key in expired_keys:
            entry = self._memory_cache.pop(key)
            self._current_memory_size -= entry.size_bytes
            self.stats.evictions += 1
        
        # 清理磁盘缓存
        if self.enable_disk_cache:
            for meta_file in self.cache_dir.glob("*.meta"):
                try:
                    with open(meta_file, 'r') as f:
                        meta = json.load(f)
                    
                    created_at = datetime.fromisoformat(meta['created_at'])
                    if (datetime.now() - created_at).total_seconds() > meta.get('ttl', self.default_ttl):
                        cache_file = meta_file.with_suffix('.pkl')
                        cache_file.unlink(missing_ok=True)
                        meta_file.unlink()
                        self.stats.evictions += 1
                except:
                    pass
        
        if expired_keys:
            logger.info(f"已清理 {len(expired_keys)} 个过期缓存")
    
    def get_stats(self) -> Dict:
        """获取缓存统计"""
        hit_rate = self.stats.hits / max(self.stats.hits + self.stats.misses, 1)
        
        return {
            "hits": self.stats.hits,
            "misses": self.stats.misses,
            "hit_rate": f"{hit_rate:.2%}",
            "evictions": self.stats.evictions,
            "memory_usage_mb": self._current_memory_size / (1024 * 1024),
            "memory_limit_mb": self.max_memory_bytes / (1024 * 1024),
            "memory_usage_pct": f"{self._current_memory_size / self.max_memory_bytes:.2%}",
            "entry_count": len(self._memory_cache),
            "disk_cache_enabled": self.enable_disk_cache
        }
    
    def cache_stock_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        fetch_func: Callable
    ) -> pd.DataFrame:
        """
        缓存股票数据
        
        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            fetch_func: 数据获取函数
        
        Returns:
            股票数据DataFrame
        """
        key = self._generate_key(
            "stock_data",
            symbol=symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        def _fetch():
            logger.info(f"获取股票数据: {symbol}")
            return fetch_func(symbol, start_date, end_date)
        
        result = self.get(key, fetch_func=_fetch, ttl=3600)  # 股票数据缓存1小时
        
        return result if result is not None else pd.DataFrame()
    
    def cache_indicator(
        self,
        symbol: str,
        indicator_name: str,
        params: Dict,
        fetch_func: Callable
    ) -> pd.DataFrame:
        """
        缓存技术指标
        
        Args:
            symbol: 股票代码
            indicator_name: 指标名称
            params: 指标参数
            fetch_func: 获取函数
        
        Returns:
            指标数据
        """
        key = self._generate_key(
            f"indicator_{indicator_name}",
            symbol=symbol,
            **params
        )
        
        return self.get(key, fetch_func=fetch_func, ttl=1800)  # 指标缓存30分钟
    
    def cache_realtime_price(
        self,
        symbol: str,
        price: float
    ):
        """缓存实时价格"""
        key = f"realtime:{symbol}"
        self.put(key, price, ttl=60)  # 实时价格只缓存1分钟
    
    def get_realtime_price(self, symbol: str) -> Optional[float]:
        """获取实时价格"""
        key = f"realtime:{symbol}"
        return self._memory_cache.get(key, CacheEntry(key="", value=None)).value


# 创建全局缓存实例
_global_cache: Optional[DataCache] = None


def get_cache() -> DataCache:
    """获取全局缓存实例"""
    global _global_cache
    if _global_cache is None:
        _global_cache = DataCache()
    return _global_cache
