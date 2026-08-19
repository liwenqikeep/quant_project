"""
数据源抽象层

定义统一的数据源接口，支持多种数据源适配器
"""
import pandas as pd
from abc import ABC, abstractmethod
from typing import Optional
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
    """AKShare 数据源适配器"""

    def __init__(self):
        self._available = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                import akshare as ak
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
        if not self.is_available():
            raise RuntimeError("AKShare 数据源不可用")

        import akshare as ak

        # 转换代码格式
        code = symbol.replace(".SZ", "").replace(".SH", "")

        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=adjust
        )

        # 重命名列
        df.columns = [
            "date", "open", "close", "high", "low",
            "volume", "amount", "amplitude", "change_pct",
            "change_amount", "turnover"
        ]

        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        df.sort_index(inplace=True)

        return df


class TushareAdapter(BaseDataSource):
    """Tushare 数据源适配器（规划中）"""

    def __init__(self, token: str = None):
        self.token = token
        self._available = None

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
