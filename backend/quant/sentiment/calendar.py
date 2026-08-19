"""
交易日历模块

注意：此文件已迁移到 quant.utils.calendar
此处保留用于向后兼容，新代码请使用 quant.utils.calendar
"""
from quant.utils.calendar import TradingCalendar, get_calendar

__all__ = ['TradingCalendar', 'get_calendar']
