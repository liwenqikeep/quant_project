"""
报告生成模块
生成HTML、PDF等格式的回测报告
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path
from quant.utils.logger import logger


class ReportGenerator:
    """报告生成器"""
    
    def __init__(self, output_dir: str = "reports"):
        """
        初始化报告生成器
        
        Args:
            output_dir: 报告输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"报告生成器初始化: 输出目录={self.output_dir}")
    
    def generate_backtest_report(
        self,
        strategy_name: str,
        backtest_results: Dict,
        trades: Optional[List[Dict]] = None,
        output_format: str = "html"
    ) -> str:
        """
        生成回测报告
        
        Args:
            strategy_name: 策略名称
            backtest_results: 回测结果
            trades: 交易记录
            output_format: 输出格式 "html" 或 "markdown"
        
        Returns:
            报告文件路径
        """
        if output_format == "html":
            return self._generate_html_report(strategy_name, backtest_results, trades)
        elif output_format == "markdown":
            return self._generate_markdown_report(strategy_name, backtest_results, trades)
        else:
            raise ValueError(f"不支持的格式: {output_format}")
    
    def _generate_html_report(
        self,
        strategy_name: str,
        results: Dict,
        trades: Optional[List[Dict]]
    ) -> str:
        """生成HTML报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{strategy_name}_{timestamp}.html"
        filepath = self.output_dir / filename
        
        html_content = self._build_html_content(strategy_name, results, trades)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"回测报告已生成: {filepath}")
        return str(filepath)
    
    def _build_html_content(
        self,
        strategy_name: str,
        results: Dict,
        trades: Optional[List[Dict]]
    ) -> str:
        """构建HTML内容"""
        # 基本信息
        initial_cash = results.get('initial_cash', 0)
        final_value = results.get('final_value', 0)
        total_return = results.get('total_return', 0)
        annual_return = results.get('annual_return', 0)
        sharpe_ratio = results.get('sharpe_ratio', 0)
        max_drawdown = results.get('max_drawdown', 0)
        win_rate = results.get('win_rate', 0)
        total_trades = results.get('total_trades', 0)
        
        html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>回测报告 - {strategy_name}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 20px;
        }}
        .header h1 {{
            margin: 0 0 10px 0;
        }}
        .header .subtitle {{
            opacity: 0.8;
            font-size: 14px;
        }}
        .section {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .section h2 {{
            margin-top: 0;
            color: #333;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .metric-card {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }}
        .metric-label {{
            color: #666;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .metric-value {{
            font-size: 24px;
            font-weight: bold;
            color: #333;
        }}
        .metric-value.positive {{
            color: #28a745;
        }}
        .metric-value.negative {{
            color: #dc3545;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #f8f9fa;
            font-weight: 600;
        }}
        .footer {{
            text-align: center;
            color: #666;
            font-size: 12px;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{strategy_name}</h1>
        <div class="subtitle">
            回测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
            回测期间: {results.get('start_date', 'N/A')} ~ {results.get('end_date', 'N/A')}
        </div>
    </div>
    
    <div class="section">
        <h2>收益概览</h2>
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">初始资金</div>
                <div class="metric-value">¥{initial_cash:,.0f}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">最终资产</div>
                <div class="metric-value">¥{final_value:,.0f}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">总收益率</div>
                <div class="metric-value {'positive' if total_return > 0 else 'negative'}">{total_return:.2%}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">年化收益率</div>
                <div class="metric-value {'positive' if annual_return > 0 else 'negative'}">{annual_return:.2%}</div>
            </div>
        </div>
    </div>
    
    <div class="section">
        <h2>风险指标</h2>
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">夏普比率</div>
                <div class="metric-value">{sharpe_ratio:.2f}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">最大回撤</div>
                <div class="metric-value negative">{max_drawdown:.2%}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">波动率</div>
                <div class="metric-value">{results.get('volatility', 0):.2%}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">卡玛比率</div>
                <div class="metric-value">{results.get('calmar_ratio', 0):.2f}</div>
            </div>
        </div>
    </div>
    
    <div class="section">
        <h2>交易统计</h2>
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">总交易次数</div>
                <div class="metric-value">{total_trades}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">胜率</div>
                <div class="metric-value">{win_rate:.2%}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">盈亏比</div>
                <div class="metric-value">{results.get('profit_loss_ratio', 0):.2f}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">平均持仓天数</div>
                <div class="metric-value">{results.get('avg_holding_days', 0):.1f}</div>
            </div>
        </div>
    </div>
"""
        
        # 添加交易记录表
        if trades and len(trades) > 0:
            html += """
    <div class="section">
        <h2>交易记录</h2>
        <table>
            <thead>
                <tr>
                    <th>日期</th>
                    <th>股票</th>
                    <th>方向</th>
                    <th>价格</th>
                    <th>数量</th>
                    <th>金额</th>
                </tr>
            </thead>
            <tbody>
"""
            for trade in trades[-20:]:  # 只显示最近20条
                html += f"""
                <tr>
                    <td>{trade.get('date', 'N/A')}</td>
                    <td>{trade.get('symbol', 'N/A')}</td>
                    <td>{'买入' if trade.get('side') == 'buy' else '卖出'}</td>
                    <td>¥{trade.get('price', 0):.2f}</td>
                    <td>{trade.get('shares', 0)}</td>
                    <td>¥{trade.get('amount', 0):,.2f}</td>
                </tr>
"""
            html += """
            </tbody>
        </table>
    </div>
"""
        
        html += f"""
    <div class="footer">
        <p>本报告由量化交易系统自动生成</p>
        <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
</body>
</html>
"""
        return html
    
    def _generate_markdown_report(
        self,
        strategy_name: str,
        results: Dict,
        trades: Optional[List[Dict]]
    ) -> str:
        """生成Markdown报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{strategy_name}_{timestamp}.md"
        filepath = self.output_dir / filename
        
        md_content = f"""# {strategy_name} 回测报告

## 基本信息

- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **回测期间**: {results.get('start_date', 'N/A')} ~ {results.get('end_date', 'N/A')}

## 收益指标

| 指标 | 值 |
|------|-----|
| 初始资金 | ¥{results.get('initial_cash', 0):,.0f} |
| 最终资产 | ¥{results.get('final_value', 0):,.0f} |
| 总收益率 | {results.get('total_return', 0):.2%} |
| 年化收益率 | {results.get('annual_return', 0):.2%} |

## 风险指标

| 指标 | 值 |
|------|-----|
| 夏普比率 | {results.get('sharpe_ratio', 0):.2f} |
| 最大回撤 | {results.get('max_drawdown', 0):.2%} |
| 波动率 | {results.get('volatility', 0):.2%} |
| 卡玛比率 | {results.get('calmar_ratio', 0):.2f} |

## 交易统计

| 指标 | 值 |
|------|-----|
| 总交易次数 | {results.get('total_trades', 0)} |
| 胜率 | {results.get('win_rate', 0):.2%} |
| 盈亏比 | {results.get('profit_loss_ratio', 0):.2f} |
| 平均持仓天数 | {results.get('avg_holding_days', 0):.1f}天 |
"""
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        logger.info(f"Markdown报告已生成: {filepath}")
        return str(filepath)
    
    def generate_comparison_report(
        self,
        strategies: Dict[str, Dict],
        output_format: str = "html"
    ) -> str:
        """
        生成策略对比报告
        
        Args:
            strategies: {策略名: 回测结果}
            output_format: 输出格式
        
        Returns:
            报告文件路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"comparison_{timestamp}.html"
        filepath = self.output_dir / filename
        
        # 构建表格
        rows = []
        for name, results in strategies.items():
            rows.append(f"""<tr>
                <td>{name}</td>
                <td class="{'positive' if results.get('total_return', 0) > 0 else 'negative'}">{results.get('total_return', 0):.2%}</td>
                <td>{results.get('annual_return', 0):.2%}</td>
                <td>{results.get('sharpe_ratio', 0):.2f}</td>
                <td class="negative">{results.get('max_drawdown', 0):.2%}</td>
                <td>{results.get('win_rate', 0):.2%}</td>
            </tr>""")
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>策略对比报告</title>
    <style>
        body {{ font-family: sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f5f5f5; }}
        .positive {{ color: #28a745; }}
        .negative {{ color: #dc3545; }}
    </style>
</head>
<body>
    <h1>策略对比报告</h1>
    <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <table>
        <thead>
            <tr>
                <th>策略</th>
                <th>总收益</th>
                <th>年化收益</th>
                <th>夏普比率</th>
                <th>最大回撤</th>
                <th>胜率</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
</body>
</html>
"""
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        
        logger.info(f"对比报告已生成: {filepath}")
        return str(filepath)
