"""
交易日历模块
交易日判断、节假日管理、财报日历
"""
import pandas as pd
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
from pathlib import Path
import json
from quant.utils.logger import logger

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False


class TradingCalendar:
    """交易日历"""
    
    def __init__(self, data_dir: str = "data/calendar"):
        """
        初始化交易日历
        
        Args:
            data_dir: 数据存储目录
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 交易日历
        self.trading_days: List[date] = []
        self.holidays: Dict[date, str] = {}  # date -> holiday_name
        
        # 加载日历
        self._load_calendar()
        
        logger.info(f"交易日历初始化完成: {len(self.trading_days)} 个交易日")
    
    def _load_calendar(self):
        """加载日历数据"""
        calendar_file = self.data_dir / "trading_days.json"
        
        if calendar_file.exists():
            try:
                with open(calendar_file, 'r') as f:
                    data = json.load(f)
                    self.trading_days = [date.fromisoformat(d) for d in data.get('trading_days', [])]
                    self.holidays = {date.fromisoformat(k): v for k, v in data.get('holidays', {}).items()}
                    logger.info(f"已加载本地日历: {len(self.trading_days)} 个交易日")
                    return
            except Exception as e:
                logger.warning(f"加载本地日历失败: {e}")
        
        # 生成默认日历（简化版）
        self._generate_default_calendar()
    
    def _save_calendar(self):
        """保存日历数据"""
        calendar_file = self.data_dir / "trading_days.json"
        
        try:
            data = {
                'trading_days': [d.isoformat() for d in self.trading_days],
                'holidays': {k.isoformat(): v for k, v in self.holidays.items()}
            }
            with open(calendar_file, 'w') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"日历已保存: {calendar_file}")
        except Exception as e:
            logger.error(f"保存日历失败: {e}")
    
    def _generate_default_calendar(self):
        """生成默认日历（2020-2025年）"""
        start_year = 2020
        end_year = 2025
        
        # A股主要节假日（简化版，实际应从数据源获取）
        public_holidays = {
            # 元旦
            (1, 1): "元旦",
            # 春节（每年变化，需要手动设置）
            # 清明节
            (4, 4): "清明节", (4, 5): "清明节", (4, 6): "清明节",
            # 劳动节
            (5, 1): "劳动节", (5, 2): "劳动节", (5, 3): "劳动节",
            # 端午节
            (6, 22): "端午节", (6, 23): "端午节", (6, 24): "端午节",
            # 中秋节（每年变化）
            (9, 18): "中秋节", (9, 19): "中秋节", (9, 20): "中秋节",
            # 国庆节
            (10, 1): "国庆节", (10, 2): "国庆节", (10, 3): "国庆节",
            (10, 4): "国庆节", (10, 5): "国庆节", (10, 6): "国庆节", (10, 7): "国庆节",
        }
        
        self.trading_days = []
        self.holidays = {}
        
        for year in range(start_year, end_year + 1):
            for month in range(1, 13):
                for day in range(1, 32):
                    try:
                        d = date(year, month, day)
                    except ValueError:
                        break
                    
                    # 只处理工作日（周一到周五）
                    if d.weekday() < 5:
                        # 检查是否节假日
                        holiday_name = public_holidays.get((month, day))
                        if holiday_name:
                            self.holidays[d] = holiday_name
                        else:
                            self.trading_days.append(d)
        
        logger.info(f"已生成默认日历: {len(self.trading_days)} 个交易日")
    
    def update_calendar(self, start_date: str = None, end_date: str = None):
        """从数据源更新日历"""
        if not AKSHARE_AVAILABLE:
            logger.warning("AKShare未安装，无法更新日历")
            return
        
        try:
            # 获取交易日历
            df = ak.tool_trade_date_hist_sina()
            
            self.trading_days = []
            for _, row in df.iterrows():
                trade_date = row['trade_date']
                if isinstance(trade_date, str):
                    self.trading_days.append(date.fromisoformat(trade_date.replace('/', '-')))
            
            self._save_calendar()
            logger.info(f"日历已更新: {len(self.trading_days)} 个交易日")
            
        except Exception as e:
            logger.error(f"更新日历失败: {e}")
    
    def is_trading_day(self, check_date: date) -> bool:
        """判断是否为交易日"""
        return check_date in self.trading_days
    
    def is_trading_day_str(self, date_str: str) -> bool:
        """判断是否为交易日（字符串格式）"""
        if isinstance(date_str, str):
            check_date = date.fromisoformat(date_str.replace('/', '-'))
        else:
            check_date = date_str
        return self.is_trading_day(check_date)
    
    def is_holiday(self, check_date: date) -> bool:
        """判断是否为节假日"""
        return check_date in self.holidays
    
    def get_holiday_name(self, check_date: date) -> Optional[str]:
        """获取节假日名称"""
        return self.holidays.get(check_date)
    
    def get_next_trading_day(self, from_date: date, n: int = 1) -> date:
        """
        获取下一个交易日
        
        Args:
            from_date: 起始日期
            n: 跳过的天数
        
        Returns:
            下一个交易日
        """
        current = from_date + timedelta(days=1)
        count = 0
        
        while count < n:
            if self.is_trading_day(current):
                count += 1
            if count < n:
                current += timedelta(days=1)
        
        return current
    
    def get_previous_trading_day(self, from_date: date, n: int = 1) -> date:
        """
        获取上一个交易日
        
        Args:
            from_date: 起始日期
            n: 跳过的天数
        
        Returns:
            上一个交易日
        """
        current = from_date - timedelta(days=1)
        count = 0
        
        while count < n:
            if self.is_trading_day(current):
                count += 1
            if count < n:
                current -= timedelta(days=1)
        
        return current
    
    def get_trading_days_between(
        self,
        start_date: date,
        end_date: date
    ) -> List[date]:
        """
        获取两个日期之间的交易日
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            交易日列表
        """
        return [d for d in self.trading_days if start_date <= d <= end_date]
    
    def get_recent_trading_days(self, count: int = 30) -> List[date]:
        """获取最近N个交易日"""
        today = date.today()
        trading_days = [d for d in self.trading_days if d <= today]
        return sorted(trading_days, reverse=True)[:count]
    
    def get_calendar_days(
        self,
        start_date: date,
        end_date: date,
        include_holidays: bool = True
    ) -> pd.DataFrame:
        """
        获取日历DataFrame
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            include_holidays: 是否包含节假日
        
        Returns:
            日历DataFrame
        """
        records = []
        current = start_date
        
        while current <= end_date:
            records.append({
                'date': current,
                'is_trading_day': self.is_trading_day(current),
                'is_holiday': self.is_holiday(current),
                'holiday_name': self.holidays.get(current, ''),
                'weekday': current.weekday(),
                'weekday_name': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][current.weekday()]
            })
            current += timedelta(days=1)
        
        df = pd.DataFrame(records)
        
        if not include_holidays:
            df = df[df['is_trading_day']]
        
        return df


# 创建全局实例
_global_calendar: Optional[TradingCalendar] = None


def get_calendar() -> TradingCalendar:
    """获取全局交易日历实例"""
    global _global_calendar
    if _global_calendar is None:
        _global_calendar = TradingCalendar()
    return _global_calendar
