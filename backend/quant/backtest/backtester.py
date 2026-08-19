"""
回测引擎
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Literal, Callable
from pathlib import Path
from quant.utils.logger import logger


class Backtester:
    """回测引擎"""

    def __init__(
        self,
        initial_cash: float = None,
        commission: float = None,
        stamp_tax: float = None,
        slippage: float = None,
        min_commission: float = None,
        min_commission_enabled: bool = None,
        execution_price: Literal["next_open", "next_close"] = None,
        config: Dict[str, Any] = None,
        auto_load_config: bool = True,
        risk_hook: Optional[Callable] = None,
        symbol: str = ""
    ):
        """
        初始化回测引擎

        Args:
            initial_cash: 初始资金（从 config 读取或使用默认值 1000000）
            commission: 佣金费率（从 config 读取或使用默认值 0.0003）
            stamp_tax: 印花税率（从 config 读取或使用默认值 0.0005，卖出时收取）
            slippage: 滑点（bps，买入上浮、卖出下浮，默认 0）
            min_commission: 最低佣金（A股默认5元）
            min_commission_enabled: 是否启用最低佣金（默认 True）
            execution_price: 执行价格策略，"next_open"次日开盘（推荐）,"next_close"次日收盘
            config: 配置字典，支持嵌套键如 "strategy.initial_cash"
            auto_load_config: 是否自动从 config.yaml 加载配置
            risk_hook: 风控钩子函数，签名为 `func(signal, context) -> (modified_signal, allow_trade, reason)`
                   context 包含: date, cash, position, total_value, position_value
                   返回: (修改后的信号, 是否允许交易, 拒绝原因)
            symbol: 交易标的代码（用于交易记录）
        """
        self.symbol = symbol
        # 优先使用传入参数，其次从配置读取，最后使用默认值
        if config is not None:
            self.initial_cash = initial_cash if initial_cash is not None else self._get_config_value(config, "strategy.initial_cash", 1000000)
            self.commission = commission if commission is not None else self._get_config_value(config, "strategy.commission", 0.0003)
            self.stamp_tax = stamp_tax if stamp_tax is not None else self._get_config_value(config, "strategy.stamp_tax", 0.0005)
            self.slippage = slippage if slippage is not None else self._get_config_value(config, "strategy.slippage", 0.0)
            self.min_commission = min_commission if min_commission is not None else self._get_config_value(config, "strategy.min_commission", 5.0)
            self.min_commission_enabled = min_commission_enabled if min_commission_enabled is not None else self._get_config_value(config, "strategy.min_commission_enabled", True)
            self.execution_price = execution_price if execution_price is not None else self._get_config_value(config, "strategy.execution_price", "next_open")
        elif auto_load_config:
            # 自动从 config.yaml 加载
            try:
                from quant.config import get_config
                self.initial_cash = initial_cash if initial_cash is not None else get_config("strategy.initial_cash", 1000000)
                self.commission = commission if commission is not None else get_config("strategy.commission", 0.0003)
                self.stamp_tax = stamp_tax if stamp_tax is not None else get_config("strategy.stamp_tax", 0.0005)
                self.slippage = slippage if slippage is not None else get_config("strategy.slippage", 0.0)
                self.min_commission = min_commission if min_commission is not None else get_config("strategy.min_commission", 5.0)
                self.min_commission_enabled = min_commission_enabled if min_commission_enabled is not None else get_config("strategy.min_commission_enabled", True)
                self.execution_price = execution_price if execution_price is not None else get_config("strategy.execution_price", "next_open")
            except Exception:
                # 配置加载失败，使用默认值
                self.initial_cash = initial_cash if initial_cash is not None else 1000000
                self.commission = commission if commission is not None else 0.0003
                self.stamp_tax = stamp_tax if stamp_tax is not None else 0.0005
                self.slippage = slippage if slippage is not None else 0.0
                self.min_commission = min_commission if min_commission is not None else 5.0
                self.min_commission_enabled = min_commission_enabled if min_commission_enabled is not None else True
                self.execution_price = execution_price if execution_price is not None else "next_open"
        else:
            self.initial_cash = initial_cash if initial_cash is not None else 1000000
            self.commission = commission if commission is not None else 0.0003
            self.stamp_tax = stamp_tax if stamp_tax is not None else 0.0005
            self.slippage = slippage if slippage is not None else 0.0
            self.min_commission = min_commission if min_commission is not None else 5.0
            self.min_commission_enabled = min_commission_enabled if min_commission_enabled is not None else True
            self.execution_price = execution_price if execution_price is not None else "next_open"

        self.config = config
        self.risk_hook = risk_hook
        
        self.reset()

        logger.info(f"回测引擎初始化: 初始资金={self.initial_cash}, 佣金={self.commission}, 印花税={self.stamp_tax}, 滑点={self.slippage}, 最低佣金={self.min_commission if self.min_commission_enabled else '禁用'}, 执行价={self.execution_price}, 风控钩子={'已启用' if risk_hook else '未启用'}")

    @staticmethod
    def _get_config_value(config: Dict, key: str, default: Any) -> Any:
        """从嵌套配置字典中获取值"""
        keys = key.split('.')
        value = config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value if value is not None else default
    
    def reset(self):
        """重置回测状态"""
        self.cash = self.initial_cash
        self.position = 0  # 持股数量
        self.position_value = 0  # 当前持仓市值
        self.total_value = self.cash  # 总资产
        
        self.trades = []  # 交易记录
        self.equity_curve = []  # 权益曲线
        self.risk_rejections = []  # 风控拒绝记录
        
    def _apply_slippage(self, price: float, side: str) -> float:
        """
        应用滑点
        
        Args:
            price: 原始价格
            side: 交易方向，"buy" 或 "sell"
        
        Returns:
            调整后的价格
        """
        if self.slippage == 0:
            return price
        if side == "buy":
            return price * (1 + self.slippage)
        return price * (1 - self.slippage)
    
    def _calc_commission(self, trade_value: float) -> float:
        """
        计算佣金（含最低佣金）
        
        Args:
            trade_value: 成交金额
        
        Returns:
            佣金
        """
        commission = trade_value * self.commission
        if self.min_commission_enabled:
            commission = max(commission, self.min_commission)
        return commission
    
    def execute_trade(
        self, 
        date, 
        price: float, 
        signal: int, 
        position_size: int = 100
    ) -> Dict:
        """
        执行交易
        
        Args:
            date: 交易日期
            price: 交易价格
            signal: 信号（1=买入，-1=卖出）
            position_size: 每次交易股数（手）
        
        Returns:
            交易记录
        """
        trade = {
            "date": date,
            "symbol": self.symbol,
            "price": price,
            "signal": signal,
            "side": None,  # "buy" / "sell"
            "shares": 0,
            "trade_value": 0,
            "amount": 0,  # 成交金额（用于报告）
            "commission": 0,
            "stamp_tax": 0,
            "total_cost": 0,  # 总成本（买入）或总收入（卖出）
            "pnl": None,  # 盈亏（卖出时计算）
            "execution_price": self.execution_price,
            "cash": self.cash,
            "position": self.position
        }
        
        if signal == 1 and self.position == 0:  # 买入信号且当前空仓
            # 买入
            exec_price = self._apply_slippage(price, "buy")
            max_shares = int(self.cash / (exec_price * (1 + self.commission)) / 100) * 100
            shares = min(max_shares, position_size)
            
            if shares > 0:
                trade_value = shares * exec_price
                commission = self._calc_commission(trade_value)
                # A股买入不收印花税，只在卖出时收取
                stamp_tax = 0
                total_cost = trade_value + commission
                
                self.cash -= total_cost
                self.position += shares
                
                trade["price"] = exec_price
                trade["side"] = "buy"
                trade["shares"] = shares
                trade["trade_value"] = trade_value
                trade["amount"] = trade_value
                trade["commission"] = commission
                trade["stamp_tax"] = stamp_tax
                trade["total_cost"] = total_cost
                trade["cash"] = self.cash
                trade["position"] = self.position
                
                self.trades.append(trade)
                logger.debug(f"买入 {date}: 价格={exec_price:.2f}, 数量={shares}, 现金={self.cash:.2f}")
        
        elif signal == -1 and self.position > 0:  # 卖出信号且当前持仓
            # 卖出
            exec_price = self._apply_slippage(price, "sell")
            shares = min(self.position, position_size)
            trade_value = shares * exec_price
            commission = self._calc_commission(trade_value)
            stamp_tax = trade_value * self.stamp_tax
            total_proceed = trade_value - commission - stamp_tax
            
            self.cash += total_proceed
            self.position -= shares
            
            trade["price"] = exec_price
            trade["side"] = "sell"
            trade["shares"] = shares
            trade["trade_value"] = trade_value
            trade["amount"] = trade_value
            trade["commission"] = commission
            trade["stamp_tax"] = stamp_tax
            trade["total_cost"] = -total_proceed  # 负数表示收入
            trade["cash"] = self.cash
            trade["position"] = self.position
            
            self.trades.append(trade)
            logger.debug(f"卖出 {date}: 价格={exec_price:.2f}, 数量={shares}, 现金={self.cash:.2f}")
        
        return trade
    
    def run(
        self, 
        data: pd.DataFrame, 
        signals: pd.DataFrame,
        position_size: int = 100
    ) -> Dict:
        """
        运行回测
        
        Args:
            data: 价格数据（需要包含 'close' 列，'open' 用于次日开盘执行）
            signals: 信号数据（需要包含 'signal' 列）
            position_size: 每次交易股数
        
        Returns:
            回测结果字典
        """
        logger.info(f"开始回测，执行价格策略={self.execution_price}")
        
        self.reset()
        
        # 合并数据和信号（按索引对齐）
        df = data.join(signals, how='left')
        
        # 修复未来函数：信号在 t 日收盘产生，t+1 日执行
        # 将信号整体后移一天
        signals_shifted = df["signal"].shift(1)
        df["signal_delayed"] = signals_shifted
        
        # 逐行执行回测
        for idx, row in df.iterrows():
            signal = row["signal_delayed"]
            
            # 获取执行价格
            if pd.notna(signal) and signal != 0:
                # 应用风控钩子
                if self.risk_hook is not None:
                    context = {
                        "date": idx,
                        "cash": self.cash,
                        "position": self.position,
                        "total_value": self.total_value,
                        "position_value": self.position_value
                    }
                    modified_signal, allow_trade, reason = self.risk_hook(int(signal), context)
                    
                    if not allow_trade:
                        self.risk_rejections.append({
                            "date": idx,
                            "signal": int(signal),
                            "reason": reason
                        })
                        logger.info(f"风控拒绝: {idx}, 信号={int(signal)}, 原因={reason}")
                        continue
                    
                    signal = modified_signal
                
                if signal != 0:
                    if self.execution_price == "next_open" and "open" in df.columns:
                        exec_price = row["open"]
                    else:
                        exec_price = row["close"]
                    self.execute_trade(idx, exec_price, int(signal), position_size)
            
            # 更新持仓市值（使用收盘价）
            self.position_value = self.position * row["close"]
            self.total_value = self.cash + self.position_value
            
            self.equity_curve.append({
                "date": idx,
                "cash": self.cash,
                "position_value": self.position_value,
                "total_value": self.total_value,
                "position": self.position,
                "signal": row["signal"],  # 原始信号（用于分析）
                "signal_delayed": signal  # 延迟执行的信号
            })
        
        # 计算并追加回撤数据到权益曲线（用于绘图）
        self._calculate_drawdown_in_equity_curve()
        
        # 计算回测指标
        results = self.calculate_metrics()
        
        # 计算成本占比（用于检查成本是否合理）
        if results["total_trades"] > 0:
            trades_df = results["trades"]
            total_cost = trades_df["commission"].sum() + trades_df["stamp_tax"].sum()
            total_value_traded = trades_df["trade_value"].sum()
            if total_value_traded > 0:
                cost_ratio = total_cost / total_value_traded
                logger.info(f"总成本/总成交额 = {cost_ratio:.4%}")
        
        logger.info(f"回测完成: 总收益率={results['total_return']:.2%}, 夏普比率={results['sharpe_ratio']:.2f}")
        
        return results
    
    def _calculate_drawdown_in_equity_curve(self):
        """计算回撤并追加到权益曲线记录中（用于绘图）"""
        if not self.equity_curve:
            return

        equity_df = pd.DataFrame(self.equity_curve)
        equity_df["peak"] = equity_df["total_value"].cummax()
        equity_df["drawdown"] = (equity_df["total_value"] - equity_df["peak"]) / equity_df["peak"]

        # 更新权益曲线记录
        for i, record in enumerate(self.equity_curve):
            record["peak"] = equity_df["peak"].iloc[i]
            record["drawdown"] = equity_df["drawdown"].iloc[i]

    def calculate_metrics(self) -> Dict:
        """计算回测指标"""
        equity_df = pd.DataFrame(self.equity_curve)
        trades_df = pd.DataFrame(self.trades) if self.trades else pd.DataFrame()
        
        # 总收益率
        total_return = (self.total_value - self.initial_cash) / self.initial_cash
        
        # 年化收益率
        if len(equity_df) > 1:
            days = (equity_df["date"].iloc[-1] - equity_df["date"].iloc[0]).days
            years = days / 365 if days > 0 else 1
            annual_return = (1 + total_return) ** (1 / years) - 1
        else:
            annual_return = 0
        
        # 最大回撤（返回负值，与 performance.py 一致）
        equity_df["peak"] = equity_df["total_value"].cummax()
        equity_df["drawdown"] = (equity_df["total_value"] - equity_df["peak"]) / equity_df["peak"]
        max_drawdown = equity_df["drawdown"].min()  # 已经是负值
        
        # 夏普比率（统一口径：扣除 3% 无风险利率）
        if len(equity_df) > 1:
            returns = equity_df["total_value"].pct_change().dropna()
            if len(returns) > 0 and returns.std() != 0:
                annual_return = returns.mean() * 252
                volatility = returns.std() * np.sqrt(252)
                risk_free_rate = 0.03  # 统一使用 3% 无风险利率
                sharpe_ratio = (annual_return - risk_free_rate) / volatility
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0
        
        # 年化波动率
        if len(equity_df) > 1:
            returns = equity_df["total_value"].pct_change().dropna()
            volatility = returns.std() * np.sqrt(252) if len(returns) > 0 else 0
        else:
            volatility = 0
        
        # 卡玛比率
        if max_drawdown != 0:
            calmar_ratio = annual_return / abs(max_drawdown)
        else:
            calmar_ratio = 0
        
        # 盈亏比和平均持仓天数
        if len(trades_df) > 0:
            completed_pairs = 0
            winning_pairs = 0
            total_profit = 0
            total_loss = 0
            holding_days = []
            entry_stack = []

            for _, trade in trades_df.iterrows():
                if trade["signal"] == 1:
                    entry_stack.append({
                        "price": trade["price"],
                        "shares": trade["shares"],
                        "date": trade["date"],
                        "commission": trade["commission"],
                        "stamp_tax": trade["stamp_tax"]
                    })
                elif trade["signal"] == -1 and entry_stack:
                    shares_to_sell = trade["shares"]
                    sell_price = trade["price"]
                    sell_date = trade["date"]

                    while shares_to_sell > 0 and entry_stack:
                        entry = entry_stack[0]
                        matched_shares = min(shares_to_sell, entry["shares"])

                        buy_cost = entry["price"] * matched_shares + entry["commission"]
                        sell_proceed = sell_price * matched_shares - entry["stamp_tax"]
                        pnl = sell_proceed - buy_cost

                        if pnl > 0:
                            winning_pairs += 1
                            total_profit += pnl
                        else:
                            total_loss += abs(pnl)
                        completed_pairs += 1
                        
                        # 计算持仓天数
                        if entry.get("date") and sell_date:
                            days = (sell_date - entry["date"]).days
                            holding_days.append(days)

                        entry["shares"] -= matched_shares
                        shares_to_sell -= matched_shares
                        if entry["shares"] <= 0:
                            entry_stack.pop(0)

            win_rate = winning_pairs / completed_pairs if completed_pairs > 0 else 0
            profit_loss_ratio = total_profit / total_loss if total_loss > 0 else float('inf')
            avg_holding_days = np.mean(holding_days) if holding_days else 0
        else:
            win_rate = 0
            profit_loss_ratio = 0
            avg_holding_days = 0
        
        # 交易次数
        total_trades = len(trades_df)
        
        return {
            "initial_cash": self.initial_cash,
            "final_value": self.total_value,
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "win_rate": win_rate,
            "total_trades": total_trades,
            "equity_curve": equity_df,
            "trades": trades_df,
            "risk_rejections": self.risk_rejections,
            # 新增字段
            "volatility": volatility,
            "calmar_ratio": calmar_ratio,
            "profit_loss_ratio": profit_loss_ratio,
            "avg_holding_days": avg_holding_days
        }
    
    def plot_results(self, save_path: Optional[str] = None):
        """绘制回测结果图表"""
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            
            equity_df = pd.DataFrame(self.equity_curve)
            
            if equity_df.empty:
                logger.warning("无回测数据可绘图")
                return

            # 如果没有回撤数据，先计算
            if "drawdown" not in equity_df.columns:
                equity_df["peak"] = equity_df["total_value"].cummax()
                equity_df["drawdown"] = (equity_df["total_value"] - equity_df["peak"]) / equity_df["peak"]

            fig, axes = plt.subplots(3, 1, figsize=(14, 12))
            
            # 权益曲线
            ax1 = axes[0]
            ax1.plot(equity_df["date"], equity_df["total_value"], label="总资产", linewidth=2)
            ax1.plot(equity_df["date"], equity_df["cash"], label="现金", alpha=0.7)
            ax1.plot(equity_df["date"], equity_df["position_value"], label="持仓市值", alpha=0.7)
            ax1.set_title("权益曲线", fontsize=14)
            ax1.set_xlabel("日期")
            ax1.set_ylabel("金额")
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # 回撤曲线
            ax2 = axes[1]
            ax2.fill_between(equity_df["date"], equity_df["drawdown"] * 100, 0, alpha=0.3, color='red')
            ax2.set_title("回撤", fontsize=14)
            ax2.set_xlabel("日期")
            ax2.set_ylabel("回撤 (%)")
            ax2.grid(True, alpha=0.3)
            
            # 持仓状态
            ax3 = axes[2]
            ax3.fill_between(equity_df["date"], equity_df["position"], 0, alpha=0.3, color='green')
            ax3.set_title("持仓状态", fontsize=14)
            ax3.set_xlabel("日期")
            ax3.set_ylabel("持股数量")
            ax3.grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            if save_path:
                plt.savefig(save_path, dpi=150, bbox_inches='tight')
                logger.info(f"回测图表已保存: {save_path}")
            else:
                plt.show()
            
            plt.close()
            
        except ImportError:
            logger.warning("matplotlib 未安装，无法绘图")
