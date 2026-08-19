"""
因子分析模块
因子有效性分析、IC分析、分组回测
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
from quant.utils.logger import logger


@dataclass
class FactorAnalysisResult:
    """因子分析结果"""
    factor_name: str
    ic_mean: float              # IC均值
    ic_std: float              # IC标准差
    ic_ir: float              # IC信息比率
    cumulative_return: float   # 因子收益
    long_short_return: float   # 多空收益
    top_return: float         # 高因子组合收益
    bottom_return: float       # 低因子组合收益
    turnover: float           # 换手率
    win_rate: float           # IC胜率


class FactorAnalyzer:
    """因子分析器"""
    
    def __init__(self):
        logger.info("因子分析器初始化完成")
    
    def calculate_ic(
        self,
        factor_data: pd.Series,
        forward_returns: pd.Series,
        method: str = "spearman"
    ) -> Tuple[float, float, float]:
        """
        计算IC（信息系数）
        
        Args:
            factor_data: 因子值
            forward_returns: 未来收益
            method: 相关性方法 "spearman" 或 "pearson"
        
        Returns:
            (IC均值, IC标准差, IC_IR)
        """
        # 对齐数据
        aligned = pd.DataFrame({
            'factor': factor_data,
            'returns': forward_returns
        }).dropna()
        
        if len(aligned) < 10:
            logger.warning("数据不足，无法计算IC")
            return 0, 0, 0
        
        # 计算相关系数
        if method == "spearman":
            ic_series = aligned['factor'].rolling(20).corr(
                aligned['returns'], method='spearman'
            )
        else:
            ic_series = aligned['factor'].rolling(20).corr(aligned['returns'])
        
        ic_mean = ic_series.mean()
        ic_std = ic_series.std()
        ic_ir = ic_mean / ic_std if ic_std != 0 else 0
        
        return ic_mean, ic_std, ic_ir
    
    def calculate_group_returns(
        self,
        factor_data: pd.DataFrame,
        returns: pd.DataFrame,
        n_groups: int = 5
    ) -> pd.DataFrame:
        """
        计算分组收益
        
        Args:
            factor_data: 因子值DataFrame
            returns: 收益率DataFrame
            n_groups: 分组数量
        
        Returns:
            分组收益DataFrame
        """
        # 对齐日期
        common_dates = factor_data.index.intersection(returns.index)
        factor_aligned = factor_data.loc[common_dates]
        returns_aligned = returns.loc[common_dates]
        
        group_returns = []
        
        for date in common_dates:
            factor_row = factor_aligned.loc[date]
            returns_row = returns_aligned.loc[date]
            
            # 分组
            try:
                groups = pd.qcut(factor_row, q=n_groups, labels=False, duplicates='drop')
            except:
                continue
            
            # 计算每组收益
            for g in range(n_groups):
                group_mask = groups == g
                if group_mask.sum() > 0:
                    group_ret = returns_row[group_mask].mean()
                    group_returns.append({
                        'date': date,
                        'group': g,
                        'return': group_ret
                    })
        
        return pd.DataFrame(group_returns)
    
    def analyze_factor(
        self,
        factor_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
        factor_name: str = "factor"
    ) -> FactorAnalysisResult:
        """
        完整因子分析
        
        Args:
            factor_data: 因子值
            forward_returns: 未来收益
            factor_name: 因子名称
        
        Returns:
            分析结果
        """
        # 计算IC
        ic_values = []
        for col in factor_data.columns:
            ic_mean, ic_std, ic_ir = self.calculate_ic(
                factor_data[col], forward_returns[col]
            )
            ic_values.append({
                'symbol': col,
                'ic_mean': ic_mean,
                'ic_std': ic_std,
                'ic_ir': ic_ir
            })
        
        avg_ic_mean = np.mean([x['ic_mean'] for x in ic_values])
        avg_ic_std = np.mean([x['ic_std'] for x in ic_values])
        avg_ic_ir = avg_ic_mean / avg_ic_std if avg_ic_std != 0 else 0
        
        # 计算分组收益
        group_returns = self.calculate_group_returns(
            factor_data, forward_returns
        )
        
        if not group_returns.empty:
            top_returns = group_returns[group_returns['group'] == group_returns['group'].max()]['return']
            bottom_returns = group_returns[group_returns['group'] == 0]['return']
            
            top_return = top_returns.mean() * 252 if len(top_returns) > 0 else 0
            bottom_return = bottom_returns.mean() * 252 if len(bottom_returns) > 0 else 0
            long_short = top_return - bottom_return
            
            # 换手率估算
            turnover = abs(group_returns['return'].diff()).mean()
            
            # IC胜率
            ic_win_rate = (avg_ic_mean > 0)
        else:
            top_return = 0
            bottom_return = 0
            long_short = 0
            turnover = 0
            ic_win_rate = 0
        
        return FactorAnalysisResult(
            factor_name=factor_name,
            ic_mean=avg_ic_mean,
            ic_std=avg_ic_std,
            ic_ir=avg_ic_ir,
            cumulative_return=0,  # 需要更长时间序列
            long_short_return=long_short,
            top_return=top_return,
            bottom_return=bottom_return,
            turnover=turnover,
            win_rate=ic_win_rate
        )
    
    def factor_portfolio_analysis(
        self,
        factor_data: pd.DataFrame,
        prices: pd.DataFrame,
        n_groups: int = 5,
        top_pct: float = 0.2
    ) -> Dict:
        """
        因子组合分析
        
        Args:
            factor_data: 因子值
            prices: 价格数据
            n_groups: 分组数
            top_pct: 头部比例
        
        Returns:
            分析结果字典
        """
        # 计算收益率
        returns = prices.pct_change().shift(-1)
        
        results = {}
        
        for col in factor_data.columns:
            if col not in returns.columns:
                continue
            
            factor = factor_data[col].dropna()
            ret = returns[col].dropna()
            
            # 对齐
            common_idx = factor.index.intersection(ret.index)
            factor = factor.loc[common_idx]
            ret = ret.loc[common_idx]
            
            if len(factor) < 30:
                continue
            
            # 计算IC
            ic_mean, ic_std, ic_ir = self.calculate_ic(factor, ret)
            
            # 分组
            try:
                groups = pd.qcut(factor, q=n_groups, labels=False, duplicates='drop')
            except:
                continue
            
            group_results = []
            for g in range(n_groups):
                mask = groups == g
                if mask.sum() > 0:
                    group_ret = ret[mask].mean()
                    group_results.append({
                        'group': g,
                        'mean_return': group_ret.mean(),
                        'count': mask.sum()
                    })
            
            # 头部组合
            top_threshold = factor.quantile(1 - top_pct)
            top_mask = factor >= top_threshold
            bottom_threshold = factor.quantile(top_pct)
            bottom_mask = factor <= bottom_threshold
            
            top_return = ret[top_mask].mean() if top_mask.sum() > 0 else 0
            bottom_return = ret[bottom_mask].mean() if bottom_mask.sum() > 0 else 0
            
            results[col] = {
                'ic_mean': ic_mean,
                'ic_std': ic_std,
                'ic_ir': ic_ir,
                'top_return': top_return,
                'bottom_return': bottom_return,
                'long_short': top_return - bottom_return,
                'groups': group_results
            }
        
        return results
    
    def get_factor_report(self, analysis_result: FactorAnalysisResult) -> str:
        """生成因子分析报告"""
        report = f"""
{'='*50}
因子分析报告: {analysis_result.factor_name}
{'='*50}

【IC指标】
- IC均值: {analysis_result.ic_mean:.4f}
- IC标准差: {analysis_result.ic_std:.4f}
- IC_IR: {analysis_result.ic_ir:.4f}

【收益指标】
- 多空收益: {analysis_result.long_short_return:.2%}
- 高因子组合: {analysis_result.top_return:.2%}
- 低因子组合: {analysis_result.bottom_return:.2%}

【其他指标】
- 换手率: {analysis_result.turnover:.2%}
- IC胜率: {analysis_result.win_rate:.2%}

{'='*50}
"""
        return report
