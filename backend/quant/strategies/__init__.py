"""
策略模块
"""
__all__ = ["MAStrategy", "RSIStrategy", "MACDStrategy", "MLStrategy"]

def __getattr__(name):
    if name == "MAStrategy":
        from .ma_strategy import MAStrategy
        return MAStrategy
    elif name == "RSIStrategy":
        from .rsi_strategy import RSIStrategy
        return RSIStrategy
    elif name == "MACDStrategy":
        from .macd_strategy import MACDStrategy
        return MACDStrategy
    elif name == "MLStrategy":
        from .ml_strategy import MLStrategy
        return MLStrategy
    raise AttributeError(f"module 'strategies' has no attribute '{name}'")
