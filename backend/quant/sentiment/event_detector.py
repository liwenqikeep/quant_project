"""
事件检测模块
识别重大事件并生成交易信号
"""
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from quant.utils.logger import logger


class EventType(Enum):
    """事件类型"""
    EARNINGS = "earnings"              # 财报发布
    DIVIDEND = "dividend"              # 分红送转
    SPLIT = "split"                    # 拆股合股
    IPO = "ipo"                        # 上市
    DELIST = "delist"                  # 退市
    SUSPENSION = "suspension"          # 停牌
    RESUMPTION = "resumption"          # 复牌
    BLOCK_TRADE = "block_trade"        # 大宗交易
    SHAREHOLDER_CHANGE = "shareholder"  # 股东变化
    MANAGEMENT_CHANGE = "management"   # 高管变动
    REGULATORY = "regulatory"          # 监管事件
    NEWS = "news"                      # 重大新闻


@dataclass
class Event:
    """事件"""
    event_type: EventType
    symbol: str
    title: str
    content: str
    timestamp: datetime
    impact_score: float = 0  # 影响程度 -1到1
    confidence: float = 0     # 置信度
    related_symbols: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    sentiment: str = ""       # 'positive', 'negative', 'neutral'


@dataclass
class TradingCalendarHoliday:
    """交易日历节假日"""
    date: datetime
    name: str
    holiday_type: str  # 'public', 'trading_suspended'


class EventDetector:
    """事件检测器"""
    
    def __init__(self):
        self.detected_events: List[Event] = []
        self.event_handlers: Dict[EventType, List[Callable]] = {}
        
        logger.info("事件检测器初始化完成")
    
    def register_handler(self, event_type: EventType, handler: Callable):
        """注册事件处理器"""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
        logger.info(f"已注册事件处理器: {event_type.value}")
    
    def detect_events(self, data: Dict) -> List[Event]:
        """
        检测事件
        
        Args:
            data: 包含各类数据的字典
        
        Returns:
            检测到的事件列表
        """
        events = []
        
        # 检测各类事件
        if 'stock_data' in data:
            events.extend(self._detect_price_events(data['stock_data']))
        
        if 'news' in data:
            events.extend(self._detect_news_events(data['news']))
        
        if 'announcements' in data:
            events.extend(self._detect_announcement_events(data['announcements']))
        
        if 'block_trades' in data:
            events.extend(self._detect_block_trade_events(data['block_trades']))
        
        # 处理事件
        for event in events:
            self._process_event(event)
        
        return events
    
    def _detect_price_events(self, data: pd.DataFrame) -> List[Event]:
        """检测价格相关事件"""
        events = []
        
        if len(data) < 2:
            return events
        
        # 检测涨跌停
        data['pct_change'] = data['close'].pct_change()
        
        for idx, row in data.iterrows():
            pct = row.get('pct_change', 0)
            
            if pct >= 0.095:  # 涨停
                event = Event(
                    event_type=EventType.NEWS,  # 简化
                    symbol=row.get('symbol', ''),
                    title=f"涨停事件",
                    content=f"股票涨停，涨幅{pct:.2%}",
                    timestamp=idx if isinstance(idx, datetime) else datetime.now(),
                    impact_score=0.5,
                    confidence=0.9,
                    tags=['涨停', '技术面'],
                    sentiment='positive'
                )
                events.append(event)
            
            elif pct <= -0.095:  # 跌停
                event = Event(
                    event_type=EventType.NEWS,
                    symbol=row.get('symbol', ''),
                    title=f"跌停事件",
                    content=f"股票跌停，跌幅{pct:.2%}",
                    timestamp=idx if isinstance(idx, datetime) else datetime.now(),
                    impact_score=-0.5,
                    confidence=0.9,
                    tags=['跌停', '技术面'],
                    sentiment='negative'
                )
                events.append(event)
        
        return events
    
    def _detect_news_events(self, news_data: List[Dict]) -> List[Event]:
        """检测新闻事件"""
        events = []
        
        # 高相关性关键词
        impact_keywords = {
            '重大利好': {'keywords': ['收购', '重组', '中标', '订单', '超预期', '涨停'], 'score': 0.5},
            '重大利空': {'keywords': ['处罚', '诉讼', '造假', '召回', '暴跌', '跌停'], 'score': -0.5},
            '一般利好': {'keywords': ['增长', '合作', '签约', '研发', '突破'], 'score': 0.2},
            '一般利空': {'keywords': ['下降', '亏损', '裁员', '放缓', '风险'], 'score': -0.2},
        }
        
        for news in news_data:
            title = news.get('title', '').lower()
            content = news.get('content', '').lower()
            text = title + ' ' + content
            
            for impact_type, config in impact_keywords.items():
                if any(kw in text for kw in config['keywords']):
                    event = Event(
                        event_type=EventType.NEWS,
                        symbol=news.get('symbol', ''),
                        title=news.get('title', '重大新闻'),
                        content=news.get('content', ''),
                        timestamp=news.get('publish_time', datetime.now()),
                        impact_score=config['score'],
                        confidence=0.7,
                        sentiment='positive' if config['score'] > 0 else 'negative' if config['score'] < 0 else 'neutral',
                        tags=[impact_type]
                    )
                    events.append(event)
                    break  # 每条新闻只匹配一个最高优先级
        
        return events
    
    def _detect_announcement_events(self, announcements: List[Dict]) -> List[Event]:
        """检测公告事件"""
        events = []
        
        # 公告类型映射
        announcement_types = {
            '业绩预告': {'score': 0.3, 'sentiment': 'neutral'},
            '分红': {'score': 0.2, 'sentiment': 'positive'},
            '送转': {'score': 0.2, 'sentiment': 'positive'},
            '定向增发': {'score': -0.1, 'sentiment': 'neutral'},
            '股份回购': {'score': 0.3, 'sentiment': 'positive'},
            '股权激励': {'score': 0.2, 'sentiment': 'positive'},
            '高管辞职': {'score': -0.2, 'sentiment': 'negative'},
            '审计': {'score': -0.3, 'sentiment': 'negative'},
        }
        
        for ann in announcements:
            title = ann.get('title', '')
            
            for ann_type, config in announcement_types.items():
                if ann_type in title:
                    event = Event(
                        event_type=EventType.EARNINGS,
                        symbol=ann.get('symbol', ''),
                        title=f"公告: {title}",
                        content=ann.get('content', ''),
                        timestamp=ann.get('publish_time', datetime.now()),
                        impact_score=config['score'],
                        confidence=0.8,
                        sentiment=config['sentiment'],
                        tags=[ann_type, '公告']
                    )
                    events.append(event)
                    break
        
        return events
    
    def _detect_block_trade_events(self, block_trades: List[Dict]) -> List[Event]:
        """检测大宗交易事件"""
        events = []
        
        for trade in block_trades:
            volume = trade.get('volume', 0)
            turnover = trade.get('turnover', 0)
            
            # 大宗交易阈值：成交量超过流通股本1%或成交额超过500万
            if turnover > 5000000 or volume > 100000:
                event = Event(
                    event_type=EventType.BLOCK_TRADE,
                    symbol=trade.get('symbol', ''),
                    title=f"大宗交易",
                    content=f"大宗交易: {trade.get('shares', 0)}股, 金额{turnover/10000:.2f}万",
                    timestamp=trade.get('trade_time', datetime.now()),
                    impact_score=0.1 if trade.get('side') == 'buy' else -0.1,
                    confidence=0.9,
                    sentiment='positive' if trade.get('side') == 'buy' else 'negative',
                    tags=['大宗交易', '机构动向']
                )
                events.append(event)
        
        return events
    
    def _process_event(self, event: Event):
        """处理事件"""
        self.detected_events.append(event)
        
        # 触发处理器
        if event.event_type in self.event_handlers:
            for handler in self.event_handlers[event.event_type]:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"事件处理器执行失败: {e}")
        
        logger.info(
            f"事件检测: {event.event_type.value}, {event.symbol}, "
            f"影响={event.impact_score:.2f}, 情感={event.sentiment}"
        )
    
    def get_events_by_symbol(self, symbol: str, days: int = 30) -> List[Event]:
        """获取指定股票的事件"""
        cutoff = datetime.now() - timedelta(days=days)
        return [
            e for e in self.detected_events
            if e.symbol == symbol and e.timestamp >= cutoff
        ]
    
    def get_events_by_type(self, event_type: EventType, days: int = 30) -> List[Event]:
        """获取指定类型的事件"""
        cutoff = datetime.now() - timedelta(days=days)
        return [
            e for e in self.detected_events
            if e.event_type == event_type and e.timestamp >= cutoff
        ]
    
    def get_event_signals(self) -> pd.DataFrame:
        """生成事件信号"""
        if not self.detected_events:
            return pd.DataFrame()
        
        records = []
        for event in self.detected_events:
            records.append({
                "timestamp": event.timestamp,
                "symbol": event.symbol,
                "event_type": event.event_type.value,
                "title": event.title,
                "impact_score": event.impact_score,
                "confidence": event.confidence,
                "sentiment": event.sentiment,
                "tags": ",".join(event.tags)
            })
        
        df = pd.DataFrame(records)
        return df.sort_values("timestamp", ascending=False)
    
    def clear_old_events(self, days: int = 90):
        """清理旧事件"""
        cutoff = datetime.now() - timedelta(days=days)
        old_count = len(self.detected_events)
        
        self.detected_events = [
            e for e in self.detected_events
            if e.timestamp >= cutoff
        ]
        
        removed = old_count - len(self.detected_events)
        if removed > 0:
            logger.info(f"已清理 {removed} 个旧事件")
