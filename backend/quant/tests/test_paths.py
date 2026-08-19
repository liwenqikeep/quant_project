"""测试数据路径解析（config.yaml 中的 tmp / raw / processed 配置）"""
import pytest

from quant.utils.paths import get_data_paths, ensure_data_paths


class FakeConfig:
    """替代 ConfigManager 的测试桩"""

    def __init__(self, data: dict):
        self._data = data

    def get(self, key: str, default=None):
        value = self._data
        for k in key.split("."):
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value


class TestDataPaths:
    """数据路径解析测试"""

    def test_default_layout(self, monkeypatch, tmp_path):
        """data_dir + tmp/raw/processed 子目录结构"""
        config = {
            "data": {
                "data_dir": str(tmp_path / "mydata"),
                "tmp_dir": "tmp",
                "raw_dir": "raw",
                "processed_dir": "processed",
            }
        }
        monkeypatch.setattr("quant.config.get_config", lambda: FakeConfig(config))

        paths = get_data_paths()
        assert paths["data_dir"] == tmp_path / "mydata"
        assert paths["tmp"] == tmp_path / "mydata" / "tmp"
        assert paths["raw"] == tmp_path / "mydata" / "raw"
        assert paths["processed"] == tmp_path / "mydata" / "processed"

    def test_custom_subdir_names(self, monkeypatch, tmp_path):
        """子目录名可自定义"""
        config = {
            "data": {
                "data_dir": str(tmp_path / "quant"),
                "tmp_dir": "scratch",
                "raw_dir": "source",
                "processed_dir": "output",
            }
        }
        monkeypatch.setattr("quant.config.get_config", lambda: FakeConfig(config))

        paths = get_data_paths()
        assert paths["tmp"] == tmp_path / "quant" / "scratch"
        assert paths["raw"] == tmp_path / "quant" / "source"
        assert paths["processed"] == tmp_path / "quant" / "output"

    def test_legacy_full_path_keys(self, monkeypatch, tmp_path):
        """兼容旧配置 raw_data_path / processed_data_path（完整路径优先）"""
        config = {
            "data": {
                "raw_data_path": str(tmp_path / "legacy_raw"),
                "processed_data_path": str(tmp_path / "legacy_processed"),
            }
        }
        monkeypatch.setattr("quant.config.get_config", lambda: FakeConfig(config))

        paths = get_data_paths()
        assert paths["raw"] == tmp_path / "legacy_raw"
        assert paths["processed"] == tmp_path / "legacy_processed"

    def test_absolute_subdir(self, monkeypatch, tmp_path):
        """子目录配置为绝对路径时直接使用"""
        config = {
            "data": {
                "data_dir": str(tmp_path / "base"),
                "tmp_dir": str(tmp_path / "elsewhere_tmp"),
            }
        }
        monkeypatch.setattr("quant.config.get_config", lambda: FakeConfig(config))

        paths = get_data_paths()
        assert paths["tmp"] == tmp_path / "elsewhere_tmp"

    def test_ensure_creates_directories(self, monkeypatch, tmp_path):
        """ensure_data_paths 会创建 tmp/raw/processed 目录"""
        config = {"data": {"data_dir": str(tmp_path / "brand_new")}}
        monkeypatch.setattr("quant.config.get_config", lambda: FakeConfig(config))

        paths = ensure_data_paths()
        for key in ("tmp", "raw", "processed"):
            assert paths[key].is_dir(), f"{key} 目录应被创建"
