"""
风控模块
包含风控引擎、仓位限制、回撤控制、敞口监控等功能
"""
__all__ = [
    'RiskEngine',
    'PositionLimits',
    'DrawdownController',
    'ExposureMonitor'
]

def __getattr__(name):
    if name == "RiskEngine":
        from .risk_engine import RiskEngine
        return RiskEngine
    elif name == "PositionLimits":
        from .position_limits import PositionLimits
        return PositionLimits
    elif name == "DrawdownController":
        from .drawdown_control import DrawdownController
        return DrawdownController
    elif name == "ExposureMonitor":
        from .exposure_monitor import ExposureMonitor
        return ExposureMonitor
    raise AttributeError(f"module 'risk' has no attribute '{name}'")
