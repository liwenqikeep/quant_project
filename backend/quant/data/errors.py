"""
数据获取错误定义

统一新链路异常语义，呼应设计第十一节红线：
"数据获取失败必须抛 DataFetchError 或返回失败清单"
"""


class DataFetchError(Exception):
    """
    数据获取错误

    Attributes:
        symbol: 标的代码
        interval: 请求区间描述
        source: 数据源名称
    """

    def __init__(
        self,
        message: str,
        symbol: str | None = None,
        interval: str | None = None,
        source: str | None = None,
    ):
        super().__init__(message)
        self.symbol = symbol
        self.interval = interval
        self.source = source

    def __repr__(self) -> str:
        parts = [super().__repr__()]
        if self.symbol:
            parts.append(f"symbol={self.symbol}")
        if self.interval:
            parts.append(f"interval={self.interval}")
        if self.source:
            parts.append(f"source={self.source}")
        return f"DataFetchError({' '.join(parts)})"
