"""
数据获取模块

支持多种数据源，通过配置或参数选择数据源
"""
import pandas as pd
from typing import List, Tuple

from quant.utils.logger import logger

# 导入数据源适配器
from .base_data_source import AkshareAdapter, TushareAdapter
from .errors import DataFetchError


class DataFetcher:
    """
    数据获取器

    支持多种数据源，默认使用 AKShare
    可通过 config 或 source 参数切换数据源
    """

    def __init__(
        self,
        source: str = None,
        config: dict = None
    ):
        """
        初始化数据获取器

        Args:
            source: 数据源名称，"akshare" 或 "tushare"
            config: 配置字典，用于读取数据源设置
        """
        # 从配置读取或使用默认
        if config:
            self.source = source or config.get("data.sources.default", "akshare")
        else:
            self.source = source or "akshare"

        # 初始化适配器
        self._adapters = {}
        self._current_adapter = None
        self._init_adapters(config)

        logger.info(f"数据获取器初始化，数据源: {self.source}")

    def _init_adapters(self, config: dict = None):
        """初始化数据源适配器"""
        # AKShare 适配器
        self._adapters["akshare"] = AkshareAdapter()

        # Tushare 适配器（需要 token）
        tushare_token = None
        if config:
            tushare_token = config.get("data.sources.tushare.token")
        self._adapters["tushare"] = TushareAdapter(token=tushare_token)

        # 设置当前适配器
        if self.source in self._adapters:
            self._current_adapter = self._adapters[self.source]
        else:
            logger.warning(f"未知数据源: {self.source}，使用 akshare")
            self._current_adapter = self._adapters["akshare"]

    def set_source(self, source: str):
        """切换数据源"""
        if source in self._adapters:
            self.source = source
            self._current_adapter = self._adapters[source]
            logger.info(f"数据源切换为: {source}")
        else:
            raise ValueError(f"未知数据源: {source}")

    def get_stock_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
        retry: int = 3
    ) -> pd.DataFrame:
        """
        获取股票历史数据

        Args:
            symbol: 股票代码，如 "000001.SZ"
            start_date: 开始日期，格式 "YYYYMMDD"
            end_date: 结束日期，格式 "YYYYMMDD"
            adjust: 复权类型，"qfq"前复权，"hfq"后复权，""不复权
            retry: 失败重试次数

        Returns:
            DataFrame，包含 OHLCV 数据

        Raises:
            DataFetchError: 获取失败时抛出
        """
        if self._current_adapter is None:
            raise DataFetchError(f"未初始化数据源适配器: {symbol}")

        if not self._current_adapter.is_available():
            raise DataFetchError(f"当前数据源不可用: {self.source}, {symbol}")

        last_error = None
        for attempt in range(retry):
            try:
                df = self._current_adapter.get_stock_history(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust
                )
                if df.empty:
                    raise DataFetchError(
                        f"{symbol}: [{start_date}-{end_date}] 数据为空",
                        symbol=symbol,
                        interval=f"{start_date}-{end_date}",
                    )
                logger.info(f"成功获取 {symbol} 数据，共 {len(df)} 条记录")
                return df
            except DataFetchError:
                raise
            except Exception as e:
                last_error = e
                logger.warning(f"获取 {symbol} 数据失败 (尝试 {attempt + 1}/{retry}): {e}")
                if attempt < retry - 1:
                    import time
                    time.sleep(1 * (attempt + 1))  # 指数退避

        raise DataFetchError(f"{symbol}: {last_error}", symbol=symbol) from last_error

    def get_stock_batch(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        stop_on_error: bool = False
    ) -> Tuple[dict, List[str]]:
        """
        批量获取多只股票数据

        Args:
            symbols: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            stop_on_error: 是否在遇到错误时停止（默认False，记录失败并继续）

        Returns:
            (results, failures) 元组
            - results: dict，key 为股票代码，value 为 DataFrame
            - failures: list，获取失败的股票代码列表
        """
        results = {}
        failures = []
        
        for symbol in symbols:
            try:
                df = self.get_stock_history(symbol, start_date, end_date)
                if not df.empty:
                    results[symbol] = df
            except DataFetchError as e:
                logger.error(f"批量获取 {symbol} 失败: {e}")
                failures.append(symbol)
                if stop_on_error:
                    break
        
        if failures:
            logger.warning(f"批量获取完成: 成功 {len(results)}/{len(symbols)}, 失败 {failures}")
        
        return results, failures
