"""数据路径管理模块

统一从 config.yaml 解析数据存储目录，划分为三类：
- tmp/      临时缓存（缓存、新闻缓存等，可随时清理）
- raw/      原始数据（交易所/数据源直接返回的数据）
- processed/处理后数据（清洗结果、数据库、回测结果等）

所有目录均可在 config.yaml 的 data 段配置：
- data_dir: 数据根目录（绝对路径，或相对运行目录的相对路径）
- tmp_dir / raw_dir / processed_dir: 子目录名（默认 tmp / raw / processed）
兼容旧配置键 raw_data_path / processed_data_path（完整路径，优先使用）。
"""
from pathlib import Path
from typing import Dict, Optional

from quant.utils.logger import logger


def _resolve(path: str) -> Path:
    """将配置路径解析为绝对路径（相对路径基于当前工作目录）"""
    p = Path(str(path)).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def _join_sub(data_dir: Path, sub: Optional[str]) -> Path:
    """将子目录名拼接到数据根目录下；子目录为绝对路径时直接使用"""
    p = Path(str(sub)).expanduser()
    if p.is_absolute():
        return p
    return data_dir / p


def get_data_paths() -> Dict[str, Path]:
    """
    从配置读取数据存储目录。

    Returns:
        {"data_dir": Path, "tmp": Path, "raw": Path, "processed": Path}
    """
    from quant.config import get_config_manager

    cfg = get_config_manager()

    data_dir = _resolve(cfg.get("data.data_dir", "data"))

    tmp = _join_sub(data_dir, cfg.get("data.tmp_dir", "tmp"))
    raw = _join_sub(data_dir, cfg.get("data.raw_dir", "raw"))
    processed = _join_sub(data_dir, cfg.get("data.processed_dir", "processed"))

    # 兼容旧配置：raw_data_path / processed_data_path 为完整路径，优先使用
    legacy_raw = cfg.get("data.raw_data_path")
    if legacy_raw:
        raw = _resolve(str(legacy_raw))
    legacy_processed = cfg.get("data.processed_data_path")
    if legacy_processed:
        processed = _resolve(str(legacy_processed))

    return {
        "data_dir": data_dir,
        "tmp": tmp,
        "raw": raw,
        "processed": processed,
    }


def ensure_data_paths() -> Dict[str, Path]:
    """解析数据目录并确保存在（不存在则创建），返回路径字典"""
    paths = get_data_paths()
    for key in ("data_dir", "tmp", "raw", "processed"):
        try:
            paths[key].mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(f"创建数据目录失败: {paths[key]} ({e})")
    logger.debug(
        f"数据目录: tmp={paths['tmp']}, raw={paths['raw']}, processed={paths['processed']}"
    )
    return paths
