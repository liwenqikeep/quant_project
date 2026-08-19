"""
新闻数据采集模块
从多种来源采集财经新闻和公告
"""
import pandas as pd
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
import json
import time
from quant.utils.logger import logger

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    logger.warning("AKShare未安装，新闻功能受限")


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    content: str
    publish_time: datetime
    source: str
    url: str = ""
    symbols: List[str] = field(default_factory=list)
    sentiment_score: float = 0  # 情感分数
    sentiment_label: str = ""   # 情感标签
    importance: float = 1.0     # 重要性


class NewsCollector:
    """新闻采集器"""
    
    def __init__(self, cache_dir: str = "data/news"):
        """
        初始化新闻采集器
        
        Args:
            cache_dir: 缓存目录
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.news_cache: List[NewsItem] = []
        self._load_cache()
        
        logger.info("新闻采集器初始化完成")
    
    def _load_cache(self):
        """加载本地缓存"""
        cache_file = self.cache_dir / "news_cache.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.news_cache = [
                        NewsItem(
                            title=n['title'],
                            content=n['content'],
                            publish_time=datetime.fromisoformat(n['publish_time']),
                            source=n['source'],
                            url=n.get('url', ''),
                            symbols=n.get('symbols', []),
                            sentiment_score=n.get('sentiment_score', 0),
                            sentiment_label=n.get('sentiment_label', ''),
                            importance=n.get('importance', 1.0)
                        )
                        for n in data
                    ]
                    logger.info(f"已加载 {len(self.news_cache)} 条新闻缓存")
            except Exception as e:
                logger.warning(f"加载新闻缓存失败: {e}")
    
    def _save_cache(self):
        """保存缓存到本地"""
        cache_file = self.cache_dir / "news_cache.json"
        try:
            data = [
                {
                    'title': n.title,
                    'content': n.content,
                    'publish_time': n.publish_time.isoformat(),
                    'source': n.source,
                    'url': n.url,
                    'symbols': n.symbols,
                    'sentiment_score': n.sentiment_score,
                    'sentiment_label': n.sentiment_label,
                    'importance': n.importance
                }
                for n in self.news_cache[-1000:]  # 只保留最近1000条
            ]
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存新闻缓存失败: {e}")
    
    def collect_stock_news(
        self,
        symbol: str,
        days: int = 7
    ) -> List[NewsItem]:
        """
        采集指定股票的新闻
        
        Args:
            symbol: 股票代码
            days: 回溯天数
        
        Returns:
            新闻列表
        """
        if not AKSHARE_AVAILABLE:
            logger.warning("AKShare未安装，无法采集新闻")
            return []
        
        news_list = []
        
        try:
            # 使用AKShare获取新闻
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
            
            # 企业公告
            try:
                announcements = ak.stock_notice_report(
                    symbol=symbol.replace(".SZ", "").replace(".SH", ""),
                    start_date=start_date,
                    end_date=end_date
                )
                
                for _, row in announcements.iterrows():
                    news = NewsItem(
                        title=row.get('公告标题', ''),
                        content=row.get('公告内容', ''),
                        publish_time=datetime.now(),  # AKShare可能不提供精确时间
                        source="公司公告",
                        symbols=[symbol],
                        importance=2.0  # 公告通常更重要
                    )
                    news_list.append(news)
            except Exception as e:
                logger.debug(f"获取公告失败: {e}")
            
            # 新闻资讯
            try:
                news_df = ak.stock_news_em(symbol=symbol.replace(".SZ", "").replace(".SH", ""))
                for _, row in news_df.head(20).iterrows():
                    news = NewsItem(
                        title=row.get('新闻标题', ''),
                        content=row.get('新闻内容', ''),
                        publish_time=datetime.now(),
                        source=row.get('文章来源', '财经网站'),
                        symbols=[symbol],
                        url=row.get('新闻链接', '')
                    )
                    news_list.append(news)
            except Exception as e:
                logger.debug(f"获取新闻失败: {e}")
            
            logger.info(f"已采集 {len(news_list)} 条{symbol}相关新闻")
            
        except Exception as e:
            logger.error(f"采集新闻失败: {e}")
        
        return news_list
    
    def collect_market_news(self, hours: int = 24) -> List[NewsItem]:
        """
        采集市场新闻
        
        Args:
            hours: 回溯小时数
        
        Returns:
            新闻列表
        """
        if not AKSHARE_AVAILABLE:
            return []
        
        news_list = []
        
        try:
            # 获取财经新闻
            try:
                news_df = ak.stock_news_all(indicator="国内财经")
                for _, row in news_df.head(50).iterrows():
                    news = NewsItem(
                        title=row.get('新闻标题', ''),
                        content=row.get('新闻内容', ''),
                        publish_time=datetime.now(),
                        source=row.get('文章来源', '财经网站')
                    )
                    news_list.append(news)
            except Exception as e:
                logger.debug(f"获取财经新闻失败: {e}")
            
            # 获取宏观新闻
            try:
                macro_df = ak.macro_china_news()
                for _, row in macro_df.head(30).iterrows():
                    news = NewsItem(
                        title=row.get('新闻标题', ''),
                        content=row.get('新闻内容', ''),
                        publish_time=datetime.now(),
                        source="宏观新闻"
                    )
                    news_list.append(news)
            except Exception as e:
                logger.debug(f"获取宏观新闻失败: {e}")
            
            logger.info(f"已采集 {len(news_list)} 条市场新闻")
            
        except Exception as e:
            logger.error(f"采集市场新闻失败: {e}")
        
        return news_list
    
    def collect_concept_news(self, concept: str) -> List[NewsItem]:
        """
        采集概念板块新闻
        
        Args:
            concept: 概念名称
        
        Returns:
            新闻列表
        """
        # 简化实现：基于关键字搜索
        all_news = self.collect_market_news()
        
        # 过滤相关新闻
        related_news = [
            n for n in all_news
            if concept.lower() in n.title.lower() or concept.lower() in n.content.lower()
        ]
        
        return related_news
    
    def get_news_sentiment_summary(
        self,
        symbols: List[str],
        days: int = 7
    ) -> Dict:
        """
        获取股票新闻情感摘要
        
        Args:
            symbols: 股票代码列表
            days: 回溯天数
        
        Returns:
            情感摘要
        """
        all_news = []
        
        for symbol in symbols:
            news = self.collect_stock_news(symbol, days)
            all_news.extend(news)
        
        if not all_news:
            return {
                "total_news": 0,
                "positive_count": 0,
                "neutral_count": 0,
                "negative_count": 0,
                "avg_sentiment": 0,
                "symbols_mentioned": []
            }
        
        # 统计情感
        positive = [n for n in all_news if n.sentiment_label == 'positive']
        neutral = [n for n in all_news if n.sentiment_label == 'neutral']
        negative = [n for n in all_news if n.sentiment_label == 'negative']
        
        all_symbols = []
        for n in all_news:
            all_symbols.extend(n.symbols)
        
        return {
            "total_news": len(all_news),
            "positive_count": len(positive),
            "neutral_count": len(neutral),
            "negative_count": len(negative),
            "avg_sentiment": sum(n.sentiment_score for n in all_news) / len(all_news),
            "positive_ratio": len(positive) / len(all_news) if all_news else 0,
            "symbols_mentioned": list(set(all_symbols)),
            "latest_news": [
                {
                    "title": n.title,
                    "source": n.source,
                    "sentiment": n.sentiment_label,
                    "symbols": n.symbols
                }
                for n in all_news[:10]
            ]
        }
    
    def search_news(
        self,
        keyword: str,
        days: int = 30
    ) -> List[NewsItem]:
        """
        搜索新闻
        
        Args:
            keyword: 搜索关键字
            days: 回溯天数
        
        Returns:
            相关新闻列表
        """
        results = []
        
        # 从缓存中搜索
        cutoff = datetime.now() - timedelta(days=days)
        for news in self.news_cache:
            if news.publish_time < cutoff:
                continue
            if keyword.lower() in news.title.lower() or keyword.lower() in news.content.lower():
                results.append(news)
        
        return results
    
    def add_news(self, news: NewsItem):
        """添加新闻到缓存"""
        self.news_cache.append(news)
        if len(self.news_cache) > 1000:
            self.news_cache = self.news_cache[-1000:]
        self._save_cache()
    
    def get_news_df(self) -> pd.DataFrame:
        """获取新闻DataFrame"""
        if not self.news_cache:
            return pd.DataFrame()
        
        records = []
        for news in self.news_cache:
            records.append({
                "title": news.title,
                "content": news.content,
                "publish_time": news.publish_time,
                "source": news.source,
                "symbols": ",".join(news.symbols),
                "sentiment_score": news.sentiment_score,
                "sentiment_label": news.sentiment_label,
                "importance": news.importance
            })
        
        df = pd.DataFrame(records)
        df = df.sort_values("publish_time", ascending=False)
        return df
