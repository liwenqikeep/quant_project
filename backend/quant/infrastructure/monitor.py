"""
系统监控模块
监控策略运行状态、性能指标、系统资源
"""
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import psutil
from pathlib import Path
from quant.utils.logger import logger


@dataclass
class SystemMetrics:
    """系统指标"""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float
    disk_percent: float


@dataclass
class StrategyMetrics:
    """策略指标"""
    strategy_id: str
    strategy_name: str
    status: str  # running, stopped, error
    start_time: Optional[datetime]
    total_trades: int
    total_pnl: float
    today_pnl: float
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    last_trade_time: Optional[datetime]


class SystemMonitor:
    """系统监控"""
    
    def __init__(
        self,
        history_size: int = 1000,
        alert_callback: Optional[Callable] = None
    ):
        """
        初始化系统监控
        
        Args:
            history_size: 历史记录大小
            alert_callback: 告警回调函数
        """
        self.history_size = history_size
        self.alert_callback = alert_callback
        
        # 系统指标历史
        self.system_metrics: deque = deque(maxlen=history_size)
        
        # 策略监控
        self.strategies: Dict[str, StrategyMetrics] = {}
        
        # 告警阈值
        self.cpu_threshold = 80  # CPU使用率阈值
        self.memory_threshold = 85  # 内存使用率阈值
        self.disk_threshold = 90  # 磁盘使用率阈值
        
        logger.info("系统监控初始化完成")
    
    def collect_system_metrics(self) -> SystemMetrics:
        """收集系统指标"""
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # 内存
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used = memory.used / (1024 * 1024)  # MB
            memory_available = memory.available / (1024 * 1024)  # MB
            
            # 磁盘
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            
            metrics = SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_used_mb=memory_used,
                memory_available_mb=memory_available,
                disk_percent=disk_percent
            )
            
            self.system_metrics.append(metrics)
            
            # 检查告警
            self._check_alerts(metrics)
            
            return metrics
            
        except Exception as e:
            logger.error(f"收集系统指标失败: {e}")
            return SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=0,
                memory_percent=0,
                memory_used_mb=0,
                memory_available_mb=0,
                disk_percent=0
            )
    
    def _check_alerts(self, metrics: SystemMetrics):
        """检查是否触发告警"""
        alerts = []
        
        if metrics.cpu_percent > self.cpu_threshold:
            alerts.append(f"CPU使用率过高: {metrics.cpu_percent:.1f}%")
        
        if metrics.memory_percent > self.memory_threshold:
            alerts.append(f"内存使用率过高: {metrics.memory_percent:.1f}%")
        
        if metrics.disk_percent > self.disk_threshold:
            alerts.append(f"磁盘使用率过高: {metrics.disk_percent:.1f}%")
        
        for alert in alerts:
            logger.warning(f"系统告警: {alert}")
            
            if self.alert_callback:
                try:
                    self.alert_callback(alert)
                except Exception as e:
                    logger.error(f"告警回调失败: {e}")
    
    def register_strategy(
        self,
        strategy_id: str,
        strategy_name: str
    ) -> StrategyMetrics:
        """注册策略"""
        metrics = StrategyMetrics(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            status="stopped",
            start_time=None,
            total_trades=0,
            total_pnl=0,
            today_pnl=0,
            win_rate=0,
            sharpe_ratio=0,
            max_drawdown=0,
            last_trade_time=None
        )
        
        self.strategies[strategy_id] = metrics
        logger.info(f"策略已注册: {strategy_name}, ID={strategy_id}")
        
        return metrics
    
    def update_strategy(
        self,
        strategy_id: str,
        **kwargs
    ):
        """更新策略指标"""
        if strategy_id not in self.strategies:
            logger.warning(f"策略未注册: {strategy_id}")
            return
        
        metrics = self.strategies[strategy_id]
        
        for key, value in kwargs.items():
            if hasattr(metrics, key):
                setattr(metrics, key, value)
    
    def start_strategy(self, strategy_id: str):
        """启动策略"""
        if strategy_id in self.strategies:
            self.strategies[strategy_id].status = "running"
            self.strategies[strategy_id].start_time = datetime.now()
            logger.info(f"策略已启动: {strategy_id}")
    
    def stop_strategy(self, strategy_id: str):
        """停止策略"""
        if strategy_id in self.strategies:
            self.strategies[strategy_id].status = "stopped"
            logger.info(f"策略已停止: {strategy_id}")
    
    def get_system_metrics_df(self) -> pd.DataFrame:
        """获取系统指标历史"""
        if not self.system_metrics:
            return pd.DataFrame()
        
        records = []
        for m in self.system_metrics:
            records.append({
                'timestamp': m.timestamp,
                'cpu_percent': m.cpu_percent,
                'memory_percent': m.memory_percent,
                'memory_used_mb': m.memory_used_mb,
                'disk_percent': m.disk_percent
            })
        
        return pd.DataFrame(records)
    
    def get_strategy_metrics(self, strategy_id: str) -> Optional[StrategyMetrics]:
        """获取策略指标"""
        return self.strategies.get(strategy_id)
    
    def get_all_strategies(self) -> List[StrategyMetrics]:
        """获取所有策略指标"""
        return list(self.strategies.values())
    
    def get_running_strategies(self) -> List[StrategyMetrics]:
        """获取运行中的策略"""
        return [s for s in self.strategies.values() if s.status == "running"]
    
    def get_monitor_report(self) -> Dict:
        """获取监控报告"""
        # 系统指标
        current_system = self.collect_system_metrics() if self.system_metrics else None
        
        # 策略汇总
        running_count = len(self.get_running_strategies())
        total_trades = sum(s.total_trades for s in self.strategies.values())
        total_pnl = sum(s.total_pnl for s in self.strategies.values())
        
        return {
            'timestamp': datetime.now(),
            'system': {
                'cpu_percent': current_system.cpu_percent if current_system else 0,
                'memory_percent': current_system.memory_percent if current_system else 0,
                'memory_used_mb': current_system.memory_used_mb if current_system else 0,
                'disk_percent': current_system.disk_percent if current_system else 0,
                'cpu_warning': current_system.cpu_percent > self.cpu_threshold if current_system else False,
                'memory_warning': current_system.memory_percent > self.memory_threshold if current_system else False
            },
            'strategies': {
                'total_count': len(self.strategies),
                'running_count': running_count,
                'stopped_count': len(self.strategies) - running_count,
                'total_trades': total_trades,
                'total_pnl': total_pnl
            }
        }
    
    def plot_system_metrics(self, save_path: Optional[str] = None):
        """绘制系统指标图表"""
        try:
            import matplotlib.pyplot as plt
            
            df = self.get_system_metrics_df()
            if df.empty:
                logger.warning("无系统指标数据")
                return
            
            fig, axes = plt.subplots(2, 1, figsize=(14, 8))
            
            # CPU和内存
            ax1 = axes[0]
            ax1.plot(df['timestamp'], df['cpu_percent'], label='CPU %', linewidth=2)
            ax1.plot(df['timestamp'], df['memory_percent'], label='Memory %', linewidth=2)
            ax1.axhline(y=self.cpu_threshold, color='r', linestyle='--', label=f'CPU阈值({self.cpu_threshold}%)')
            ax1.axhline(y=self.memory_threshold, color='orange', linestyle='--', label=f'Memory阈值({self.memory_threshold}%)')
            ax1.set_ylabel('Percentage (%)')
            ax1.set_title('CPU & Memory Usage')
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # 内存使用量
            ax2 = axes[1]
            ax2.fill_between(df['timestamp'], df['memory_used_mb'], alpha=0.3, color='blue')
            ax2.set_ylabel('Memory (MB)')
            ax2.set_xlabel('Time')
            ax2.set_title('Memory Usage')
            ax2.grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            if save_path:
                plt.savefig(save_path, dpi=150, bbox_inches='tight')
                logger.info(f"系统指标图表已保存: {save_path}")
            else:
                plt.show()
            
            plt.close()
            
        except ImportError:
            logger.warning("matplotlib未安装，无法绘图")


# 告警示例
class AlertManager:
    """告警管理器"""
    
    def __init__(self):
        self.alerts: deque = deque(maxlen=100)
        logger.info("告警管理器初始化完成")
    
    def handle_alert(self, alert: str):
        """处理告警"""
        alert_record = {
            'timestamp': datetime.now(),
            'message': alert,
            'level': self._determine_level(alert)
        }
        
        self.alerts.append(alert_record)
        
        # 记录日志
        if alert_record['level'] == 'critical':
            logger.critical(f"严重告警: {alert}")
        elif alert_record['level'] == 'warning':
            logger.warning(f"告警: {alert}")
        else:
            logger.info(f"通知: {alert}")
    
    def _determine_level(self, alert: str) -> str:
        """判断告警级别"""
        alert_lower = alert.lower()
        
        if any(kw in alert_lower for kw in ['critical', '严重', '崩溃', '停止']):
            return 'critical'
        elif any(kw in alert_lower for kw in ['warning', '警告', '过高', '危险']):
            return 'warning'
        else:
            return 'info'
    
    def get_recent_alerts(self, hours: int = 24) -> List[Dict]:
        """获取最近告警"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            {'timestamp': a['timestamp'], 'message': a['message'], 'level': a['level']}
            for a in self.alerts
            if a['timestamp'] >= cutoff
        ]
