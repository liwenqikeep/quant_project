"""
定时任务调度器
支持定时任务、周期任务、延时任务
"""
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from threading import Thread, Event, Lock
import time
from pathlib import Path
from quant.utils.logger import logger


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(Enum):
    """任务类型"""
    ONCE = "once"           # 单次任务
    PERIODIC = "periodic"   # 周期任务
    # CRON = "cron"         # Cron任务（预留，暂未实现）


@dataclass
class Task:
    """任务"""
    task_id: str
    name: str
    func: Callable
    task_type: TaskType
    interval: int = 0       # 周期（秒）
    next_run: datetime = field(default_factory=datetime.now)
    last_run: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    result: any = None
    error: str = ""
    enabled: bool = True


class TaskScheduler:
    """任务调度器"""

    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.running = False
        self.stop_event = Event()
        self.thread: Optional[Thread] = None

        logger.info("任务调度器初始化完成")

    def add_task(
        self,
        name: str,
        func: Callable,
        task_type: TaskType = TaskType.ONCE,
        interval: int = 0,
        first_run: Optional[datetime] = None
    ) -> str:
        """添加任务"""
        task_id = f"task_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

        task = Task(
            task_id=task_id,
            name=name,
            func=func,
            task_type=task_type,
            interval=interval,
            next_run=first_run or datetime.now()
        )

        self.tasks[task_id] = task

        logger.info(f"任务已添加: {name}, ID={task_id}, 类型={task_type.value}")

        return task_id

    def add_periodic_task(
        self,
        name: str,
        func: Callable,
        interval_seconds: int
    ) -> str:
        """添加周期任务"""
        return self.add_task(
            name=name,
            func=func,
            task_type=TaskType.PERIODIC,
            interval=interval_seconds
        )

    def add_daily_task(
        self,
        name: str,
        func: Callable,
        hour: int = 9,
        minute: int = 30
    ) -> str:
        """添加每日定时任务"""
        now = datetime.now()
        next_run = now.replace(hour=hour, minute=minute, second=0)

        if next_run <= now:
            next_run += timedelta(days=1)

        return self.add_task(
            name=name,
            func=func,
            task_type=TaskType.PERIODIC,
            interval=86400,
            first_run=next_run
        )

    def remove_task(self, task_id: str) -> bool:
        """移除任务"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.enabled = False
            del self.tasks[task_id]
            logger.info(f"任务已移除: {task_id}")
            return True
        return False

    def start(self):
        """启动调度器"""
        if self.running:
            logger.warning("调度器已在运行")
            return

        self.running = True
        self.stop_event.clear()

        self.thread = Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        logger.info("任务调度器已启动")

    def stop(self):
        """停止调度器"""
        if not self.running:
            return

        self.running = False
        self.stop_event.set()

        if self.thread:
            self.thread.join(timeout=5)

        logger.info("任务调度器已停止")

    def _run_loop(self):
        """运行循环"""
        while self.running:
            now = datetime.now()

            for task_id, task in list(self.tasks.items()):
                if not task.enabled:
                    continue

                if task.status == TaskStatus.RUNNING:
                    continue

                if now >= task.next_run:
                    self._execute_task(task)

            self.stop_event.wait(timeout=1)

    def _execute_task(self, task: Task):
        """执行任务"""
        task.status = TaskStatus.RUNNING

        logger.info(f"开始执行任务: {task.name}")

        try:
            result = task.func()
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.last_run = datetime.now()

            if task.task_type == TaskType.PERIODIC:
                task.next_run = task.last_run + timedelta(seconds=task.interval)

            logger.info(f"任务执行完成: {task.name}")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"任务执行失败: {task.name}, 错误: {e}")

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        task = self.tasks.get(task_id)
        if not task:
            return None

        return {
            'task_id': task.task_id,
            'name': task.name,
            'status': task.status.value,
            'task_type': task.task_type.value,
            'next_run': task.next_run.isoformat() if task.next_run else None,
            'last_run': task.last_run.isoformat() if task.last_run else None,
            'enabled': task.enabled,
            'error': task.error
        }

    def get_all_tasks(self) -> List[Dict]:
        """获取所有任务"""
        return [self.get_task_status(tid) for tid in self.tasks]

    def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        task = self.tasks.get(task_id)
        if task:
            task.enabled = False
            logger.info(f"任务已暂停: {task_id}")
            return True
        return False

    def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        task = self.tasks.get(task_id)
        if task:
            task.enabled = True
            logger.info(f"任务已恢复: {task_id}")
            return True
        return False

    def run_now(self, task_id: str) -> bool:
        """立即运行任务"""
        task = self.tasks.get(task_id)
        if task:
            self._execute_task(task)
            return True
        return False


# 预定义任务示例
class ScheduledTasks:
    """预定义任务"""

    @staticmethod
    def daily_data_update():
        """每日数据更新任务（增量同步）"""
        from quant.config import load_config
        from quant.data import DataSyncService

        try:
            load_config()
            service = DataSyncService()
            report = service.run_incremental()
            logger.info(
                f"每日数据更新完成: 成功 {report.success}/{report.total}, "
                f"失败 {report.failed}, 跳过 {report.skipped}"
            )
            return report
        except Exception as e:
            logger.error(f"每日数据更新失败: {e}")
            raise

    @staticmethod
    def rebalance_portfolio():
        """每日组合再平衡"""
        logger.info("执行组合再平衡")
        pass

    @staticmethod
    def risk_check():
        """实时风控检查"""
        logger.info("执行风控检查")
        pass

    @staticmethod
    def generate_report():
        """生成日报"""
        logger.info("生成每日报告")
        pass


# P1-04: 数据同步定时任务
class DataSyncJob:
    """
    数据同步定时任务

    职责：
    - 从配置读取 data.fetch.schedule
    - 按 weekdays 过滤（仅工作日）
    - 当日已成功则 skipped（幂等）
    - 进程内互斥（同一时刻只运行一个实例）
    - catch_up：启动时已过触发时间且当日未同步则立即补跑
    """

    def __init__(
        self,
        scheduler: TaskScheduler,
        db=None,
        config=None,
    ):
        self.scheduler = scheduler
        self.db = db
        self.config = config
        self._lock = Lock()

    def register(self) -> str | None:
        """注册定时任务，返回任务 ID 或 None（disabled）"""
        from quant.config import get_config

        cfg = get_config()
        schedule = cfg.get("data.fetch.schedule", {})
        if not schedule.get("enabled", False):
            logger.info("数据同步定时任务未启用")
            return None

        weekdays = schedule.get("weekdays", [1, 2, 3, 4, 5])
        time_str = schedule.get("time", "17:30")
        hour, minute = map(int, time_str.split(":"))
        catch_up = schedule.get("catch_up", True)
        self.weekdays = weekdays

        if catch_up:
            self._try_catch_up(hour, minute)

        task_id = self.scheduler.add_daily_task(
            name="DataSyncJob",
            func=self._run,
            hour=hour,
            minute=minute,
        )
        logger.info(f"DataSyncJob 已注册，触发时间 {hour:02d}:{minute:02d}，weekdays={weekdays}")
        return task_id

    def _run(self):
        """执行数据同步（带互斥/去重/过滤）"""
        if not self._lock.acquire(blocking=False):
            logger.info("DataSyncJob: 上次任务未结束，跳过本次执行")
            return None

        try:
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            today_weekday = now.weekday()

            if today_weekday not in self.weekdays:
                logger.info(f"DataSyncJob: 今日（周{today_weekday + 1}）不在 weekdays={self.weekdays}，跳过")
                return None

            if self._has_successful_fetch_today():
                logger.info("DataSyncJob: 当日已成功同步，跳过")
                return None

            from quant.data import DataSyncService

            service = DataSyncService(db=self.db, config=self.config)
            report = service.run_incremental()
            logger.info(
                f"DataSyncJob 完成: 成功 {report.success}/{report.total}, "
                f"失败 {report.failed}, 跳过 {report.skipped}"
            )
            return report

        except Exception as e:
            logger.error(f"DataSyncJob 执行失败: {e}")
            raise
        finally:
            self._lock.release()

    def _has_successful_fetch_today(self) -> bool:
        """检查当日是否已有成功同步记录"""
        if self.db is None:
            from quant.storage.database import Database
            self.db = Database()
        return self.db.has_successful_fetch_today()

    def _try_catch_up(self, hour: int, minute: int) -> None:
        """检查是否需要补跑"""
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if now > target and not self._has_successful_fetch_today():
            logger.info(f"DataSyncJob: 已过触发时间 {hour:02d}:{minute:02d}，当日未同步，立即补跑...")
            self._run()
