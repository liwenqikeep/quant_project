"""
回撤控制模块
动态仓位调整、回撤预警、强平机制
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from quant.utils.logger import logger


class DrawdownLevel(Enum):
    """回撤等级"""
    NORMAL = "normal"          # 正常
    CAUTION = "caution"        # 注意
    WARNING = "warning"        # 警告
    DANGER = "danger"          # 危险
    FORCED_LIQUIDATION = "forced"  # 强制平仓


@dataclass
class DrawdownConfig:
    """回撤控制配置"""
    # 回撤阈值（百分比）
    caution_threshold: float = 0.05      # 5%回撤，注意
    warning_threshold: float = 0.10      # 10%回撤，警告
    danger_threshold: float = 0.15      # 15%回撤，危险
    forced_threshold: float = 0.20       # 20%回撤，强制平仓
    
    # 仓位缩减比例（每触发一级，减少这么多仓位）
    position_reduce_step: float = 0.10   # 每次缩减10%仓位
    
    # 恢复条件
    recovery_gain: float = 0.05         # 需要盈利5%才能恢复仓位
    recovery_period_days: int = 5        # 观察期天数
    
    # 其他
    max_position_reduce_ratio: float = 0.5  # 最大仓位缩减比例（不超过50%）


@dataclass
class DrawdownRecord:
    """回撤记录"""
    timestamp: datetime
    peak_value: float
    current_value: float
    drawdown: float
    level: DrawdownLevel
    action_taken: str = ""


class DrawdownController:
    """回撤控制器"""
    
    def __init__(
        self,
        config: Optional[DrawdownConfig] = None,
        on_action_callback: Optional[Callable] = None
    ):
        """
        初始化回撤控制器
        
        Args:
            config: 回撤控制配置
            on_action_callback: 触发动作时的回调函数
        """
        self.config = config or DrawdownConfig()
        self.on_action_callback = on_action_callback
        
        self.peak_value = 0
        self.current_value = 0
        self.current_drawdown = 0
        self.current_level = DrawdownLevel.NORMAL
        self.position_scale = 1.0  # 当前仓位缩放因子
        
        self.history: List[DrawdownRecord] = []
        self.recovery_start_value = 0
        self.recovery_start_time = None
        
        logger.info("回撤控制器初始化完成")
        logger.info(
            f"阈值设置: 注意={self.config.caution_threshold:.1%}, "
            f"警告={self.config.warning_threshold:.1%}, "
            f"危险={self.config.danger_threshold:.1%}, "
            f"强平={self.config.forced_threshold:.1%}"
        )
    
    def reset(self, initial_value: float = 0):
        """重置控制器"""
        self.peak_value = initial_value
        self.current_value = initial_value
        self.current_drawdown = 0
        self.current_level = DrawdownLevel.NORMAL
        self.position_scale = 1.0
        self.history = []
        self.recovery_start_value = 0
        self.recovery_start_time = None
        logger.info(f"回撤控制器已重置，初始值: {initial_value:,.2f}")
    
    def update(self, current_value: float, timestamp: Optional[datetime] = None) -> Dict:
        """
        更新当前市值，计算回撤，执行控制逻辑
        
        Args:
            current_value: 当前市值
            timestamp: 时间戳
        
        Returns:
            控制结果字典
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        self.current_value = current_value
        
        # 更新峰值
        if current_value > self.peak_value:
            self.peak_value = current_value
            # 创新高后重置恢复标记
            self.recovery_start_value = 0
            self.recovery_start_time = None
        
        # 计算回撤
        if self.peak_value > 0:
            self.current_drawdown = (current_value - self.peak_value) / self.peak_value
        else:
            self.current_drawdown = 0
        
        # 确定回撤等级
        old_level = self.current_level
        self._update_level()
        
        # 执行控制动作
        actions = []
        if self.current_level != old_level:
            actions = self._execute_control(old_level, self.current_level)
        
        # 记录历史
        record = DrawdownRecord(
            timestamp=timestamp,
            peak_value=self.peak_value,
            current_value=current_value,
            drawdown=self.current_drawdown,
            level=self.current_level,
            action_taken="; ".join(actions) if actions else ""
        )
        self.history.append(record)
        
        return {
            "drawdown": self.current_drawdown,
            "level": self.current_level.value,
            "position_scale": self.position_scale,
            "peak_value": self.peak_value,
            "current_value": current_value,
            "actions": actions
        }
    
    def _update_level(self):
        """更新回撤等级"""
        dd = abs(self.current_drawdown)  # 回撤取绝对值
        
        if dd >= self.config.forced_threshold:
            self.current_level = DrawdownLevel.FORCED_LIQUIDATION
        elif dd >= self.config.danger_threshold:
            self.current_level = DrawdownLevel.DANGER
        elif dd >= self.config.warning_threshold:
            self.current_level = DrawdownLevel.WARNING
        elif dd >= self.config.caution_threshold:
            self.current_level = DrawdownLevel.CAUTION
        else:
            self.current_level = DrawdownLevel.NORMAL
    
    def _execute_control(
        self,
        old_level: DrawdownLevel,
        new_level: DrawdownLevel
    ) -> List[str]:
        """
        执行控制动作
        
        Args:
            old_level: 旧等级
            new_level: 新等级
        
        Returns:
            执行的动作列表
        """
        actions = []
        
        # 等级上升（回撤扩大）- 需要减仓
        if new_level.value > old_level.value:
            if new_level == DrawdownLevel.CAUTION:
                actions.append("轻微减仓，注意风险")
                self._reduce_position(0.1)  # 减10%
                
            elif new_level == DrawdownLevel.WARNING:
                actions.append("减仓，控制风险")
                self._reduce_position(0.2)  # 减20%
                
            elif new_level == DrawdownLevel.DANGER:
                actions.append("大幅减仓，风险警报")
                self._reduce_position(0.3)  # 减30%
                
            elif new_level == DrawdownLevel.FORCED_LIQUIDATION:
                actions.append("强制平仓，停止交易")
                self.position_scale = 0  # 仓位归零
                logger.critical("触发强制平仓条件！")
        
        # 等级下降（回撤收窄或恢复盈利）- 可以考虑加仓
        elif new_level.value < old_level.value:
            if new_level == DrawdownLevel.NORMAL:
                # 检查是否满足恢复条件
                if self._check_recovery():
                    actions.append("恢复正常，可以考虑加仓")
                    self._increase_position()
                else:
                    actions.append("等待恢复信号")
        
        # 记录动作
        for action in actions:
            logger.warning(f"回撤控制执行: {action}, 当前缩放因子: {self.position_scale:.2%}")
        
        # 触发回调
        if self.on_action_callback and actions:
            self.on_action_callback({
                "level": new_level,
                "drawdown": self.current_drawdown,
                "position_scale": self.position_scale,
                "actions": actions
            })
        
        return actions
    
    def _reduce_position(self, ratio: float):
        """
        减少仓位
        
        Args:
            ratio: 减少比例
        """
        # 确保不超过最大缩减比例
        max_reduce = 1 - self.config.max_position_reduce_ratio
        effective_ratio = max(ratio, max_reduce)
        
        self.position_scale = max(
            self.position_scale * (1 - effective_ratio),
            self.config.max_position_reduce_ratio
        )
    
    def _increase_position(self):
        """
        增加仓位（恢复）
        """
        # 每次恢复增加20%仓位
        self.position_scale = min(
            self.position_scale * 1.2,
            1.0  # 最多恢复到100%
        )
    
    def _check_recovery(self) -> bool:
        """
        检查是否满足恢复条件
        
        Returns:
            是否可以恢复仓位
        """
        if self.recovery_start_value == 0:
            # 记录恢复开始时的市值
            self.recovery_start_value = self.current_value
            self.recovery_start_time = datetime.now()
            return False
        
        # 检查恢复幅度
        recovery_gain = (self.current_value - self.recovery_start_value) / self.recovery_start_value
        if recovery_gain >= self.config.recovery_gain:
            return True
        
        # 检查观察期
        if self.recovery_start_time:
            days_elapsed = (datetime.now() - self.recovery_start_time).days
            if days_elapsed >= self.recovery_period_days:
                # 观察期结束后，即使没有达到恢复幅度，也允许缓慢恢复
                if recovery_gain >= self.config.recovery_gain * 0.5:
                    return True
        
        return False
    
    def get_target_position(
        self,
        signal_position: float
    ) -> float:
        """
        获取风控调整后的目标仓位
        
        Args:
            signal_position: 策略信号给出的原始目标仓位
        
        Returns:
            调整后的目标仓位
        """
        return signal_position * self.position_scale
    
    def get_status(self) -> Dict:
        """获取当前状态"""
        return {
            "drawdown": self.current_drawdown,
            "level": self.current_level.value,
            "position_scale": self.position_scale,
            "peak_value": self.peak_value,
            "current_value": self.current_value,
            "recovery_start_value": self.recovery_start_value,
            "is_in_recovery": self.recovery_start_value > 0
        }
    
    def get_history_df(self) -> pd.DataFrame:
        """获取回撤历史记录"""
        if not self.history:
            return pd.DataFrame()
        
        return pd.DataFrame([
            {
                "timestamp": r.timestamp,
                "peak_value": r.peak_value,
                "current_value": r.current_value,
                "drawdown": r.drawdown,
                "level": r.level.value,
                "action": r.action_taken
            }
            for r in self.history
        ])
    
    def plot_drawdown(self, save_path: Optional[str] = None):
        """绘制回撤曲线"""
        try:
            import matplotlib.pyplot as plt
            
            df = self.get_history_df()
            if df.empty:
                logger.warning("无回撤历史数据")
                return
            
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
            
            # 市值曲线
            ax1.plot(df["timestamp"], df["current_value"], label="当前市值", linewidth=2)
            ax1.plot(df["timestamp"], df["peak_value"], label="峰值", 
                    linewidth=1, linestyle="--", alpha=0.7)
            ax1.set_ylabel("市值")
            ax1.set_title("市值曲线与峰值")
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # 回撤曲线
            ax2.fill_between(
                df["timestamp"],
                df["drawdown"] * 100,
                0,
                alpha=0.3,
                color='red',
                label="回撤"
            )
            ax2.axhline(
                y=-self.config.warning_threshold * 100,
                color='orange',
                linestyle='--',
                label=f'警告线({self.config.warning_threshold:.1%})'
            )
            ax2.axhline(
                y=-self.config.danger_threshold * 100,
                color='red',
                linestyle='--',
                label=f'危险线({self.config.danger_threshold:.1%})'
            )
            ax2.set_ylabel("回撤 (%)")
            ax2.set_xlabel("时间")
            ax2.set_title("回撤曲线")
            ax2.legend()
            ax2.grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            if save_path:
                plt.savefig(save_path, dpi=150, bbox_inches='tight')
                logger.info(f"回撤图表已保存: {save_path}")
            else:
                plt.show()
            
            plt.close()
            
        except ImportError:
            logger.warning("matplotlib未安装，无法绘图")
