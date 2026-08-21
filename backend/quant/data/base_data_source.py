"""
数据源抽象层

定义统一的数据源接口，支持多种数据源适配器
AKShare 东财日线返回 12 列：日期、股票代码、开盘、收盘、最高、最低、
成交量(手)、成交额(元)、振幅(%)、涨跌幅(%)、涨跌额(元)、换手率(%)
"""
import time

import pandas as pd
from abc import ABC, abstractmethod

from quant.data.errors import DataFetchError
from quant.utils.logger import logger


class BaseDataSource(ABC):
    """数据源基类"""

    @abstractmethod
    def get_stock_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq"
    ) -> pd.DataFrame:
        """获取股票历史数据"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        pass


class AkshareAdapter(BaseDataSource):
    """
    AKShare 数据源适配器

    适配接口：akshare 1.18.92 东财日线 stock_zh_a_hist
    列映射（原始 → 规范）：日期→date、开盘→open、收盘→close、最高→high、
    最低→low、成交量→volume(手)、成交额→amount(元)、振幅→amplitude(小数)、
    涨跌幅→change_pct(小数)、涨跌额→change_amount(元)、换手率→turnover(小数)
    """

    def __init__(self, config: dict | None = None):
        """
        Args:
            config: 配置字典，支持键：retry(int)、timeout_seconds(float)、backoff_base_seconds(float)
        """
        self._available: bool | None = None
        self._retry = 3
        self._timeout_seconds = 20.0
        self._backoff_base_seconds = 1.0
        if config:
            self._retry = config.get("data.fetch.retry", 3)
            self._timeout_seconds = config.get("data.fetch.timeout_seconds", 20.0)
            self._backoff_base_seconds = config.get("data.fetch.backoff_base_seconds", 1.0)

    def is_available(self) -> bool:
        if self._available is None:
            try:
                import akshare as ak  # noqa: F401
                self._available = True
            except ImportError:
                self._available = False
                logger.warning("AKShare 未安装")
        return self._available

    def get_stock_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq"
    ) -> pd.DataFrame:
        """
        获取股票历史数据（规范化）

        Args:
            symbol: 带后缀股票代码，如 "600519.SH"
            start_date: 开始日期，"YYYYMMDD"
            end_date: 结束日期，"YYYYMMDD"
            adjust: 复权类型，"" | "qfq" | "hfq"

        Returns:
            DataFrame，规范列：date/open/close/high/low/volume/amount/
            amplitude/change_pct/change_amount/turnover
            index=date，sorted

        Raises:
            RuntimeError: 数据源不可用或全部重试失败
        """
        if not self.is_available():
            raise DataFetchError("AKShare 数据源不可用", symbol=symbol, source="akshare")

        code = self._to_raw_code(symbol)
        last_error: Exception | None = None

        for attempt in range(self._retry):
            try:
                df = self._fetch_once(code, start_date, end_date, adjust)
                if df is not None:
                    return df
            except Exception as e:  # noqa: BLE001
                last_error = e
                logger.warning(
                    f"AKShare 获取 {symbol} 失败 (尝试 {attempt + 1}/{self._retry}): {e}"
                )
                if attempt < self._retry - 1:
                    backoff = self._backoff_base_seconds * (2 ** attempt)
                    time.sleep(backoff)

        raise DataFetchError(
            f"重试 {self._retry} 次后仍失败: {last_error}",
            symbol=symbol,
            interval=f"{start_date}-{end_date}",
            source="akshare",
        ) from last_error

    def _fetch_once(
        self,
        code: str,
        start_date: str,
        end_date: str,
        adjust: str
    ) -> pd.DataFrame | None:
        """单次拉取（带超时），成功返回规范化 DataFrame，失败返回 None"""
        import akshare as ak
        from threading import Thread
        from typing import Any

        result: dict[str, Any] = {"df": None, "error": None}

        def _target() -> None:
            try:
                result["df"] = ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust,
                )
            except Exception as e:  # noqa: BLE001
                result["error"] = e

        t = Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout=self._timeout_seconds)

        if t.is_alive():
            # 超时：线程仍在运行（akshare 阻塞），视为超时错误
            raise TimeoutError(f"请求超时 {self._timeout_seconds}s")

        if result["error"]:
            raise result["error"]

        df = result["df"]
        if df is None or df.empty:
            return None

        return self._normalize(df)

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        列映射 + 单位换算

        东财原始列（12列）→ 规范列：
        - 振幅(%) → amplitude(小数): ÷100
        - 涨跌幅(%) → change_pct(小数): ÷100
        - 换手率(%) → turnover(小数): ÷100
        - symbol 加交易所后缀
        """
        # 原始列名 → 规范列名映射（显式取列，防位置错位）
        column_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "振幅": "amplitude",
            "涨跌幅": "change_pct",
            "涨跌额": "change_amount",
            "换手率": "turnover",
        }

        # 检查必要列是否存在
        missing = [k for k in column_map if k not in df.columns]
        if missing:
            raise DataFetchError(
                f"AKShare 返回列缺失: {missing}，实际列: {list(df.columns)}",
                source="akshare",
            )

        df = df[list(column_map.keys())].rename(columns=column_map)

        # 单位换算：百分比 → 小数
        for pct_col in ("amplitude", "change_pct", "turnover"):
            if pct_col in df.columns:
                df[pct_col] = df[pct_col] / 100.0

        # 日期处理
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df.set_index("date", inplace=True)
        df.sort_index(inplace=True)

        return df

    def _to_raw_code(self, symbol: str) -> str:
        """内部代码（去掉 .SH/.SZ/.BJ 后缀）"""
        for suffix in (".SH", ".SZ", ".BJ"):
            if symbol.endswith(suffix):
                return symbol[: -len(suffix)]
        return symbol


class TushareAdapter(BaseDataSource):
    """Tushare 数据源适配器（规划中）"""

    def __init__(self, token: str | None = None):
        self.token = token
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is None:
            if not self.token:
                self._available = False
                logger.warning("Tushare token 未配置")
            else:
                try:
                    import tushare as ts
                    ts.set_token(self.token)
                    self._available = True
                except ImportError:
                    self._available = False
                    logger.warning("Tushare 未安装")
        return self._available

    def get_stock_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq"
    ) -> pd.DataFrame:
        if not self.is_available():
            raise RuntimeError("Tushare 数据源不可用，请配置 token")

        import tushare as ts
        pro = ts.pro()

        # Tushare 接口需要转换日期格式
        start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

        df = pro.daily(
            ts_code=symbol,
            start_date=start,
            end_date=end
        )

        df["date"] = pd.to_datetime(df["trade_date"])
        df.set_index("date", inplace=True)
        df.sort_index(inplace=True)

        return df
