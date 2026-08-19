"""
情感分析模块
基于规则和机器学习的情感分析
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import re
from pathlib import Path
from quant.utils.logger import logger

try:
    from snownlp import SnowNLP
    from transformers import pipeline
    SNOWNLP_AVAILABLE = True
except ImportError:
    SNOWNLP_AVAILABLE = False
    logger.warning("snownlp或transformers未安装，将使用规则分析")

# 情感词典
POSITIVE_WORDS = {
    # 业绩相关
    '增长', '盈利', '利润', '业绩', '超预期', '突破', '创新高', '大涨', '涨停',
    '扭亏', '减亏', '提升', '改善', '好转', '复苏', '爆发', '放量', '活跃',
    # 战略相关
    '收购', '并购', '重组', '合作', '战略', '布局', '扩张', '进军', '开拓',
    '投资', '中标', '签约', '订单', '合同', '落地', '启动', '上线', '发布',
    # 市场相关
    '看好', '买入', '推荐', '增持', '跑赢', '领先', '优势', '壁垒', '龙头',
    '竞争力', '市场份额', '品牌', '渠道', '研发', '技术', '创新', '专利',
}

NEGATIVE_WORDS = {
    # 业绩相关
    '下降', '亏损', '减少', '下滑', '低于预期', '暴跌', '跌停', '减持', '出售',
    '裁员', '关闭', '破产', '债务', '违约', '诉讼', '处罚', '整改', '问询',
    # 经营相关
    '风险', '危机', '困境', '衰退', '萎缩', '放缓', '放缓', '承压', '恶化',
    '失信', '黑名单', '违规', '造假', '欺诈', '虚假', '误导', '隐瞒', '泄露',
    # 市场相关
    '看空', '卖出', '减持', '跑输', '劣势', '竞争', '替代', '淘汰', '产能过剩',
}

INTENSIFIERS = {'大幅', '显著', '明显', '持续', '强劲', '超预期', '历史', '首次', '再创', '全面'}
NEGATORS = {'不', '非', '无', '未', '不再', '无法', '难以', '不会'}


@dataclass
class SentimentResult:
    """情感分析结果"""
    text: str
    sentiment_score: float      # -1到1，越高越正面
    sentiment_label: str        # 'positive', 'neutral', 'negative'
    confidence: float           # 置信度
    keywords: List[str]         # 关键词
    aspects: Dict[str, float]  # 方面情感 {aspect: score}


class SentimentAnalyzer:
    """情感分析器"""
    
    def __init__(self, method: str = "hybrid"):
        """
        初始化情感分析器
        
        Args:
            method: 分析方法 "rule", "ml", "hybrid"
        """
        self.method = method
        self._init_ml_model()
        
        logger.info(f"情感分析器初始化: 方法={method}")
    
    def _init_ml_model(self):
        """初始化机器学习模型"""
        self.ml_model = None
        
        if SNOWNLP_AVAILABLE and self.method in ["ml", "hybrid"]:
            try:
                # 尝试加载预训练模型
                self.ml_model = "snownlp"
                logger.info("使用snownlp进行情感分析")
            except Exception as e:
                logger.warning(f"加载snownlp模型失败: {e}")
        
        if self.ml_model is None and self.method in ["ml", "hybrid"]:
            try:
                # 尝试使用transformers
                self.ml_model = pipeline(
                    "sentiment-analysis",
                    model="uer/roberta-base-finetuned-chinanews-chinese"
                )
                logger.info("使用transformers模型进行情感分析")
            except Exception as e:
                logger.warning(f"加载transformers模型失败: {e}")
    
    def analyze(self, text: str) -> SentimentResult:
        """
        分析文本情感
        
        Args:
            text: 待分析文本
        
        Returns:
            情感分析结果
        """
        if not text or len(text.strip()) == 0:
            return SentimentResult(
                text=text,
                sentiment_score=0,
                sentiment_label="neutral",
                confidence=0,
                keywords=[],
                aspects={}
            )
        
        # 规则分析
        rule_score, keywords = self._rule_based_analysis(text)
        
        # 机器学习分析
        ml_score = 0
        if self.ml_model:
            ml_score, confidence = self._ml_analysis(text)
        else:
            confidence = abs(rule_score) * 0.5
        
        # 混合分析
        if self.method == "rule":
            final_score = rule_score
            confidence = abs(rule_score) * 0.8
        elif self.method == "ml" and self.ml_model:
            final_score = ml_score
        else:
            # hybrid: 加权平均
            if self.ml_model:
                final_score = rule_score * 0.4 + ml_score * 0.6
            else:
                final_score = rule_score
        
        # 确定标签
        if final_score > 0.1:
            label = "positive"
        elif final_score < -0.1:
            label = "negative"
        else:
            label = "neutral"
        
        # 方面情感分析
        aspects = self._extract_aspect_sentiment(text)
        
        return SentimentResult(
            text=text,
            sentiment_score=final_score,
            sentiment_label=label,
            confidence=min(abs(confidence), 1.0),
            keywords=keywords,
            aspects=aspects
        )
    
    def _rule_based_analysis(self, text: str) -> Tuple[float, List[str]]:
        """
        基于规则的情感分析
        
        Returns:
            (情感分数, 关键词列表)
        """
        text_lower = text.lower()
        found_keywords = []
        
        # 计算正面词
        positive_count = 0
        for word in POSITIVE_WORDS:
            if word in text_lower:
                positive_count += 1
                found_keywords.append(word)
        
        # 计算负面词
        negative_count = 0
        for word in NEGATIVE_WORDS:
            if word in text_lower:
                negative_count += 1
                if word not in found_keywords:
                    found_keywords.append(word)
        
        # 检查修饰词
        intensifier_count = sum(1 for w in INTENSIFIERS if w in text_lower)
        
        # 检查否定词
        negator_count = sum(1 for w in NEGATORS if w in text_lower)
        
        # 计算分数
        base_score = (positive_count - negative_count) / max(positive_count + negative_count, 1)
        
        # 应用修饰词
        if intensifier_count > 0:
            base_score *= (1 + intensifier_count * 0.2)
        
        # 应用否定词（简化处理）
        if negator_count > 0 and (positive_count > 0 or negative_count > 0):
            base_score *= -0.5
        
        # 归一化到[-1, 1]
        score = max(-1, min(1, base_score))
        
        return score, found_keywords[:10]  # 最多返回10个关键词
    
    def _ml_analysis(self, text: str) -> Tuple[float, float]:
        """
        机器学习情感分析
        
        Returns:
            (情感分数, 置信度)
        """
        if self.ml_model == "snownlp":
            try:
                s = SnowNLP(text)
                sentiment = s.sentiments  # 0-1
                return sentiment * 2 - 1, sentiment  # 转换到-1到1
            except Exception as e:
                logger.debug(f"snownlp分析失败: {e}")
                return 0, 0
        
        elif self.ml_model is not None:
            try:
                result = self.ml_model(text[:512])[0]  # 模型有token限制
                label = result['label']
                score = result['score']
                
                if label == 'positive':
                    return score, score
                else:
                    return -score, score
            except Exception as e:
                logger.debug(f"transformers分析失败: {e}")
                return 0, 0
        
        return 0, 0
    
    def _extract_aspect_sentiment(self, text: str) -> Dict[str, float]:
        """
        提取方面情感
        
        Returns:
            {方面: 情感分数}
        """
        aspects = {}
        
        aspect_keywords = {
            '业绩': ['业绩', '利润', '营收', '盈利', '增长', '收入'],
            '产品': ['产品', '研发', '技术', '创新'],
            '市场': ['市场份额', '竞争', '销售', '渠道'],
            '政策': ['政策', '监管', '合规', '许可'],
            '合作': ['合作', '并购', '收购', '战略'],
            '风险': ['风险', '诉讼', '处罚', '债务'],
        }
        
        for aspect, keywords in aspect_keywords.items():
            if any(kw in text for kw in keywords):
                # 截取相关片段进行分析
                aspect_text = text  # 简化：使用整段文本
                score, _ = self._rule_based_analysis(aspect_text)
                aspects[aspect] = score
        
        return aspects
    
    def analyze_batch(self, texts: List[str]) -> List[SentimentResult]:
        """
        批量分析文本情感
        
        Args:
            texts: 文本列表
        
        Returns:
            情感分析结果列表
        """
        return [self.analyze(text) for text in texts]
    
    def aggregate_sentiment(
        self,
        texts: List[str],
        weights: Optional[List[float]] = None
    ) -> SentimentResult:
        """
        聚合多个文本的情感
        
        Args:
            texts: 文本列表
            weights: 权重列表
        
        Returns:
            聚合后的情感结果
        """
        if not texts:
            return SentimentResult(
                text="",
                sentiment_score=0,
                sentiment_label="neutral",
                confidence=0,
                keywords=[],
                aspects={}
            )
        
        # 分析每个文本
        results = self.analyze_batch(texts)
        
        # 默认权重
        if weights is None:
            weights = [1.0] * len(results)
        else:
            weights = [w / sum(weights) for w in weights]  # 归一化
        
        # 加权平均
        total_score = sum(r.sentiment_score * w for r, w in zip(results, weights))
        total_confidence = sum(r.confidence * w for r, w in zip(results, weights))
        
        # 合并关键词
        all_keywords = []
        for r in results:
            all_keywords.extend(r.keywords)
        keywords = list(set(all_keywords))[:10]
        
        # 合并方面情感
        all_aspects = {}
        for r in results:
            for aspect, score in r.aspects.items():
                if aspect in all_aspects:
                    all_aspects[aspect].append(score)
                else:
                    all_aspects[aspect] = [score]
        
        # 平均方面情感
        aspects = {k: sum(v) / len(v) for k, v in all_aspects.items()}
        
        # 确定标签
        if total_score > 0.1:
            label = "positive"
        elif total_score < -0.1:
            label = "negative"
        else:
            label = "neutral"
        
        return SentimentResult(
            text="\n".join(texts[:3]),  # 截取前3个
            sentiment_score=total_score,
            sentiment_label=label,
            confidence=total_confidence,
            keywords=keywords,
            aspects=aspects
        )
    
    def get_sentiment_signal(
        self,
        symbol: str,
        news_list: List[Dict],
        threshold: float = 0.2
    ) -> Dict:
        """
        根据新闻情感生成交易信号
        
        Args:
            symbol: 股票代码
            news_list: 新闻列表 [{title, content, publish_time, importance}]
            threshold: 信号阈值
        
        Returns:
            信号字典
        """
        if not news_list:
            return {"action": "hold", "confidence": 0, "reason": "无新闻"}
        
        # 提取文本
        texts = [n.get('title', '') + ' ' + n.get('content', '') for n in news_list]
        weights = [n.get('importance', 1.0) for n in news_list]
        
        # 聚合情感
        result = self.aggregate_sentiment(texts, weights)
        
        # 生成信号
        if result.sentiment_score > threshold:
            action = "buy"
        elif result.sentiment_score < -threshold:
            action = "sell"
        else:
            action = "hold"
        
        return {
            "symbol": symbol,
            "action": action,
            "sentiment_score": result.sentiment_score,
            "sentiment_label": result.sentiment_label,
            "confidence": result.confidence,
            "keywords": result.keywords,
            "aspects": result.aspects,
            "news_count": len(news_list),
            "reason": f"情感{'正面' if result.sentiment_score > 0 else '负面' if result.sentiment_score < 0 else '中性'}"
        }
