"""
分析报告模块
包含绩效分析、因子分析、报告生成等功能
"""

from .performance import PerformanceAnalyzer
from .factor_analysis import FactorAnalyzer
from .report_generator import ReportGenerator

__all__ = [
    'PerformanceAnalyzer',
    'FactorAnalyzer',
    'ReportGenerator'
]
