"""
消息面模块
包含新闻采集、情感分析、事件驱动等功能
"""

from .news_collector import NewsCollector
from .sentiment_analyzer import SentimentAnalyzer
from .event_detector import EventDetector, Event

__all__ = [
    'NewsCollector',
    'SentimentAnalyzer',
    'EventDetector',
    'Event',
]
