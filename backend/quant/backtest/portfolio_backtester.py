"""
组合回测引擎
支持多标的组合的回测、换仓和绩效计算
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from quant.utils.logger import logger


@dataclass
class PortfolioBacktestConfig:
    """组合回测配置"""
    initial_cash: float = 1000000
    commission: float = 0.0003  # 万三佣金
    stamp_tax: float = 0.0005  # 万分之五印花税
    slippage: float = 0.0
    min_commission: float = 5.0
    min_commission_enabled: bool = True
    rebalance_threshold: float = 0.05  # 再平衡阈值（5%）


class PortfolioBacktester:
    """组合回测引擎"""
    
    def __init__(
        self,
        config: Optional[PortfolioBacktestConfig] = None,
        symbols: Optional[List[str]] = None
    ):
        """
        初始化组合回测引擎
        
        Args:
            config: 组合回测配置
            symbols: 交易标的列表
        """
        self.config = config or PortfolioBacktestConfig()
        self.symbols = symbols or []
        
        self.reset()
        logger.info(f"组合回测引擎初始化: 初始资金={self.config.initial_cash}, 标的数={len(self.symbols)}")
    
    def reset(self):
        """重置回测状态"""
        self.cash = self.config.initial_cash
        self.positions: Dict[str, int] = {s: 0 for s in self.symbols}  # 各标的持股数
        self.cost_basis: Dict[str, float] = {s: 0.0 for s in self.symbols}  # 各标的成本价
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []
    
    def _calc_commission(self, trade_value: float) -> float:
        """计算佣金"""
        commission = trade_value * self.config.commission
        if self.config.min_commission_enabled:
            commission = max(commission, self.config.min_commission)
        return commission
    
    def _apply_slippage(self, price: float, side: str) -> float:
        """应用滑点"""
        if self.config.slippage == 0:
            return price
        if side == "buy":
            return price * (1 + self.config.slippage)
        return price * (1 - self.config.slippage)
    
    def _get_position_value(self, prices: pd.Series) -> float:
        """计算当前持仓市值"""
        total = 0.0
        for symbol in self.symbols:
            if symbol in prices.index and symbol in self.positions:
                total += self.positions[symbol] * prices[symbol]
        return total
    
    def _execute_rebalance(
        self,
        date,
        prices: pd.Series,
        target_weights: Dict[str, float]
    ) -> List[Dict]:
        """
        执行再平衡
        
        Args:
            date: 日期
            prices: 当日收盘价
            target_weights: 目标权重
        
        Returns:
            交易记录列表
        """
        trades = []
        total_value = self.cash + self._get_position_value(prices)
        
        for symbol, weight in target_weights.items():
            if symbol not in prices.index:
                continue
            
            current_shares = self.positions.get(symbol, 0)
            target_value = total_value * weight
            current_value = current_shares * prices[symbol]
            
            # 需要调整的金额
            diff_value = target_value - current_value
            
            if abs(diff_value) < 100:  # 金额太小不交易
                continue
            
            side = "buy" if diff_value > 0 else "sell"
            exec_price = self._apply_slippage(prices[symbol], side)
            
            if side == "buy":
                # 买入：计算可买股数（100的整数倍）
                available_cash = self.cash * 0.95  # 预留5%资金
                if available_cash <= 0:
                    continue
                max_shares = int(available_cash / (exec_price * (1 + self.config.commission)) / 100) * 100
                shares = max_shares
                
                if shares > 0:
                    trade_value = shares * exec_price
                    commission = self._calc_commission(trade_value)
                    total_cost = trade_value + commission
                    
                    self.cash -= total_cost
                    self.positions[symbol] = self.positions.get(symbol, 0) + shares
                    self.cost_basis[symbol] = exec_price
                    
                    trades.append({
                        "date": date,
                        "symbol": symbol,
                        "side": "buy",
                        "price": exec_price,
                        "shares": shares,
                        "trade_value": trade_value,
                        "commission": commission,
                        "stamp_tax": 0,
                        "cash": self.cash
                    })
            else:
                # 卖出
                shares = min(current_shares, abs(int(diff_value / exec_price / 100) * 100))
                
                if shares > 0:
                    trade_value = shares * exec_price
                    commission = self._calc_commission(trade_value)
                    stamp_tax = trade_value * self.config.stamp_tax
                    total_proceed = trade_value - commission - stamp_tax
                    
                    self.cash += total_proceed
                    self.positions[symbol] -= shares
                    
                    trades.append({
                        "date": date,
                        "symbol": symbol,
                        "side": "sell",
                        "price": exec_price,
                        "shares": shares,
                        "trade_value": trade_value,
                        "commission": commission,
                        "stamp_tax": stamp_tax,
                        "cash": self.cash
                    })
        
        return trades
    
    def run(
        self,
        prices: pd.DataFrame,
        target_weights: pd.DataFrame,
        rebalance_dates: Optional[List] = None
    ) -> Dict:
        """
        运行组合回测
        
        Args:
            prices: 价格数据 DataFrame（日期 x 股票）
            target_weights: 目标权重 DataFrame（日期 x 股票），与 prices 索引对齐
            rebalance_dates: 再平衡日期列表（默认每日检查）
        
        Returns:
            回测结果
        """
        self.reset()
        
        if self.symbols:
            symbols_to_use = self.symbols
        else:
            symbols_to_use = list(prices.columns)
        
        # 初始化持仓
        for s in symbols_to_use:
            self.positions[s] = 0
            self.cost_basis[s] = 0.0
        
        if rebalance_dates is None:
            rebalance_dates = list(target_weights.index)
        
        # 逐日回测
        for date in prices.index:
            if date not in prices.index:
                continue
            
            day_prices = prices.loc[date]
            
            # 检查是否需要再平衡
            if date in rebalance_dates and date in target_weights.index:
                target = target_weights.loc[date].to_dict()
                # 过滤掉 NaN 和非交易标的
                target = {k: v for k, v in target.items() 
                         if pd.notna(v) and k in symbols_to_use}
                
                if target:
                    day_trades = self._execute_rebalance(date, day_prices, target)
                    self.trades.extend(day_trades)
            
            # 更新权益曲线
            position_value = sum(
                self.positions.get(s, 0) * day_prices.get(s, 0) 
                for s in symbols_to_use
            )
            total_value = self.cash + position_value
            
            self.equity_curve.append({
                "date": date,
                "cash": self.cash,
                "position_value": position_value,
                "total_value": total_value
            })
        
        return self.calculate_metrics()
    
    def calculate_metrics(self) -> Dict:
        """计算组合绩效指标"""
        equity_df = pd.DataFrame(self.equity_curve)
        
        if len(equity_df) < 2:
            return {
                "initial_cash": self.config.initial_cash,
                "final_value": self.config.initial_cash,
                "total_return": 0,
                "annual_return": 0,
                "max_drawdown": 0,
                "sharpe_ratio": 0,
                "win_rate": 0,
                "total_trades": len(self.trades),
                "equity_curve": equity_df,
                "trades": pd.DataFrame(self.trades)
            }
        
        # 收益率
        total_return = (equity_df["total_value"].iloc[-1] - self.config.initial_cash) / self.config.initial_cash
        
        days = (equity_df["date"].iloc[-1] - equity_df["date"].iloc[0]).days
        years = days / 365 if days > 0 else 1
        annual_return = (1 + total_return) ** (1 / years) - 1
        
        # 最大回撤
        peak = equity_df["total_value"].cummax()
        drawdown = (equity_df["total_value"] - peak) / peak
        max_drawdown = drawdown.min()
        
        # 夏普比率
        returns = equity_df["total_value"].pct_change().dropna()
        if len(returns) > 0 and returns.std() != 0:
            volatility = returns.std() * np.sqrt(252)
            sharpe = (returns.mean() * 252 - 0.03) / volatility
        else:
            sharpe = 0
        
        return {
            "initial_cash": self.config.initial_cash,
            "final_value": equity_df["total_value"].iloc[-1],
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe,
            "win_rate": 0,  # 组合不单独计算胜率
            "total_trades": len(self.trades),
            "equity_curve": equity_df,
            "trades": pd.DataFrame(self.trades)
        }
    
    def run_with_equal_weight(
        self,
        prices: pd.DataFrame,
        rebalance_freq: int = 5
    ) -> Dict:
        """
        等权组合回测（简化接口）
        
        Args:
            prices: 价格数据
            rebalance_freq: 再平衡频率（交易日）
        
        Returns:
            回测结果
        """
        # 生成等权目标
        symbols = list(prices.columns)
        n = len(symbols)
        if n == 0:
            return {}
        
        weight = 1.0 / n
        
        # 生成再平衡日期
        dates = list(prices.index)
        rebalance_dates = dates[::rebalance_freq]
        
        # 构建目标权重 DataFrame
        target_weights = pd.DataFrame(0.0, index=dates, columns=symbols)
        for date in dates:
            for sym in symbols:
                target_weights.loc[date, sym] = weight
        
        return self.run(prices, target_weights, rebalance_dates)
