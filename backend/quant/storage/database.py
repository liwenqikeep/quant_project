"""
数据库操作模块

支持 SQLite 的 SQLAlchemy 模型与 upsert 方法，承载：
- stock_daily（日线行情，唯一键 symbol+trade_date+adjust_type）
- stock_basic（股票基础信息）
- trade_calendar（交易日历）
- data_fetch_log（拉取审计/断点续拉）
- data_calibration_log（校准明细）

旧 StockData/trade_records 等模型保留兼容。
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import pandas as pd
from quant.utils.logger import logger

try:
    from sqlalchemy import (
        create_engine,
        Column,
        Float,
        Index,
        Integer,
        String,
        Text,
        DateTime,
        Date,
        JSON,
    )
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import Session, sessionmaker

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    logger.warning("SQLAlchemy 未安装，将使用简化版存储")


# ---------------------------------------------------------------------------
# 数据模型定义
# ---------------------------------------------------------------------------
if SQLALCHEMY_AVAILABLE:
    Base = declarative_base()

    class StockDaily(Base):
        """日线行情表"""

        __tablename__ = "stock_daily"

        id = Column(Integer, primary_key=True, autoincrement=True)
        symbol = Column(String(20), nullable=False)
        trade_date = Column(Date, nullable=False)
        adjust_type = Column(String(10), nullable=False, default="qfq")
        open = Column(Float)
        high = Column(Float)
        low = Column(Float)
        close = Column(Float)
        volume = Column(Float)  # 手
        amount = Column(Float)  # 元
        amplitude = Column(Float)  # 小数
        change_pct = Column(Float)  # 小数
        change_amount = Column(Float)
        turnover = Column(Float)  # 小数
        source = Column(String(50), nullable=False, default="akshare-em")
        created_at = Column(DateTime, nullable=False, default=datetime.now)
        updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

        __table_args__ = (
            # 唯一键：symbol + trade_date + adjust_type，幂等 upsert 依据
            Index("idx_stock_daily_unique", "symbol", "trade_date", "adjust_type", unique=True),
            Index("idx_stock_daily_date", "trade_date", "symbol"),
            Index("idx_stock_daily_symbol", "symbol", "trade_date"),
        )

    class StockBasic(Base):
        """股票基础信息表"""

        __tablename__ = "stock_basic"

        symbol = Column(String(20), primary_key=True)
        name = Column(String(100), nullable=False)
        exchange = Column(String(10), nullable=False)  # SH / SZ / BJ
        source = Column(String(50), nullable=False)
        updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    class TradeCalendar(Base):
        """交易日历表"""

        __tablename__ = "trade_calendar"

        trade_date = Column(Date, primary_key=True)
        source = Column(String(50), nullable=False, default="sina")

    class DataFetchLog(Base):
        """拉取审计表"""

        __tablename__ = "data_fetch_log"

        id = Column(Integer, primary_key=True, autoincrement=True)
        symbol = Column(String(20), nullable=False)
        adjust_type = Column(String(10), nullable=False)
        start_date = Column(Date)
        end_date = Column(Date)
        status = Column(String(20), nullable=False)  # success / failed / partial / stale / empty / skipped
        row_count = Column(Integer, default=0)
        error = Column(Text)
        detail = Column(Text)  # JSON 扩展字段
        duration_ms = Column(Integer)
        fetched_at = Column(DateTime, nullable=False, default=datetime.now)

        __table_args__ = (
            Index("idx_fetch_log_breakpoint", "symbol", "adjust_type", "status", "end_date"),
            Index("idx_fetch_log_symbol", "symbol", "fetched_at"),
        )

    class DataCalibrationLog(Base):
        """校准明细表"""

        __tablename__ = "data_calibration_log"

        id = Column(Integer, primary_key=True, autoincrement=True)
        symbol = Column(String(20), nullable=False)
        trade_date = Column(Date, nullable=False)
        adjust_type = Column(String(10), nullable=False)
        field = Column(String(50), nullable=False)
        old_value = Column(Float)
        new_value = Column(Float)
        diff_ratio = Column(Float)
        decision = Column(String(50), nullable=False)  # auto_correct / keep_local / backfill / drift
        message = Column(Text)
        checked_at = Column(DateTime, nullable=False, default=datetime.now)

        __table_args__ = (
            Index("idx_calib_log_symbol", "symbol", "trade_date"),
        )


    class StockData(Base):
        """股票数据表"""
        __tablename__ = 'stock_data'
        
        id = Column(Integer, primary_key=True, autoincrement=True)
        symbol = Column(String(20), nullable=False, index=True)
        trade_date = Column(Date, nullable=False, index=True)
        open = Column(Float)
        high = Column(Float)
        low = Column(Float)
        close = Column(Float)
        volume = Column(Float)
        amount = Column(Float)
        created_at = Column(DateTime, default=datetime.now)
        updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
        
        __table_args__ = (
            # 联合唯一索引
            {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
        )


    class TradeRecord(Base):
        """交易记录表"""
        __tablename__ = 'trade_records'
        
        id = Column(Integer, primary_key=True, autoincrement=True)
        order_id = Column(String(50), nullable=False, index=True)
        symbol = Column(String(20), nullable=False, index=True)
        side = Column(String(10), nullable=False)
        price = Column(Float, nullable=False)
        quantity = Column(Integer, nullable=False)
        amount = Column(Float, nullable=False)
        commission = Column(Float, default=0)
        order_type = Column(String(20))
        strategy_id = Column(String(50), index=True)
        signal_reason = Column(Text)
        status = Column(String(20), default='pending')
        create_time = Column(DateTime, default=datetime.now, index=True)
        update_time = Column(DateTime, default=datetime.now, onupdate=datetime.now)
        filled_time = Column(DateTime)
        
        __table_args__ = (
            {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
        )


    class SignalRecord(Base):
        """信号记录表"""
        __tablename__ = 'signal_records'
        
        id = Column(Integer, primary_key=True, autoincrement=True)
        symbol = Column(String(20), nullable=False, index=True)
        signal_type = Column(String(20), nullable=False)
        signal_value = Column(Float)
        confidence = Column(Float)
        price = Column(Float)
        strategy_id = Column(String(50), index=True)
        parameters = Column(JSON)
        create_time = Column(DateTime, default=datetime.now, index=True)
        
        __table_args__ = (
            {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
        )


    class BacktestResult(Base):
        """回测结果表"""
        __tablename__ = 'backtest_results'
        
        id = Column(Integer, primary_key=True, autoincrement=True)
        strategy_id = Column(String(50), nullable=False, index=True)
        start_date = Column(Date, nullable=False)
        end_date = Column(Date, nullable=False)
        initial_cash = Column(Float, nullable=False)
        final_value = Column(Float, nullable=False)
        total_return = Column(Float)
        annual_return = Column(Float)
        sharpe_ratio = Column(Float)
        max_drawdown = Column(Float)
        win_rate = Column(Float)
        total_trades = Column(Integer)
        parameters = Column(JSON)
        metrics = Column(JSON)
        create_time = Column(DateTime, default=datetime.now)
        
        __table_args__ = (
            {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
        )


class SimpleDatabase:
    """简化版数据库（使用JSON文件存储）"""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from quant.utils.paths import get_data_paths
            db_path = get_data_paths()["processed"] / "database"
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.stock_data_file = self.db_path / "stock_data.json"
        self.trade_records_file = self.db_path / "trade_records.json"
        self.signals_file = self.db_path / "signals.json"
        self.backtest_file = self.db_path / "backtest_results.json"
        
        # 初始化文件
        self._init_files()
        logger.info(f"简化数据库初始化: {self.db_path}")
    
    def _init_files(self):
        """初始化数据库文件"""
        for file_path in [self.stock_data_file, self.trade_records_file, 
                          self.signals_file, self.backtest_file]:
            if not file_path.exists():
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({}, f)
    
    def _load_data(self, file_path: Path) -> Dict:
        """加载数据"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载数据失败: {file_path}, {e}")
            return {}
    
    def _save_data(self, file_path: Path, data: Dict):
        """保存数据"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    def save_stock_data(self, symbol: str, df: pd.DataFrame):
        """保存股票数据"""
        data = self._load_data(self.stock_data_file)
        
        records = []
        for _, row in df.iterrows():
            records.append({
                "date": row.name.isoformat() if hasattr(row.name, 'isoformat') else str(row.name),
                "open": float(row.get('open', 0)),
                "high": float(row.get('high', 0)),
                "low": float(row.get('low', 0)),
                "close": float(row.get('close', 0)),
                "volume": float(row.get('volume', 0)),
                "amount": float(row.get('amount', 0))
            })
        
        data[symbol] = records
        self._save_data(self.stock_data_file, data)
        logger.info(f"股票数据已保存: {symbol}, {len(records)}条")
    
    def get_stock_data(self, symbol: str, start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> pd.DataFrame:
        """获取股票数据"""
        data = self._load_data(self.stock_data_file)
        
        if symbol not in data:
            return pd.DataFrame()
        
        records = data[symbol]
        
        # 过滤日期
        if start_date:
            records = [r for r in records if r['date'] >= start_date]
        if end_date:
            records = [r for r in records if r['date'] <= end_date]
        
        if not records:
            return pd.DataFrame()
        
        df = pd.DataFrame(records)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df = df.sort_index()
        
        return df
    
    def save_trade_record(self, record: Dict):
        """保存交易记录"""
        data = self._load_data(self.trade_records_file)
        
        order_id = record.get('order_id', f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}")
        data[order_id] = record
        
        self._save_data(self.trade_records_file, data)
        return order_id
    
    def get_trade_records(self, symbol: Optional[str] = None,
                         start_date: Optional[str] = None,
                         strategy_id: Optional[str] = None) -> List[Dict]:
        """获取交易记录"""
        data = self._load_data(self.trade_records_file)
        records = list(data.values())
        
        if symbol:
            records = [r for r in records if r.get('symbol') == symbol]
        if start_date:
            records = [r for r in records if r.get('create_time', '') >= start_date]
        if strategy_id:
            records = [r for r in records if r.get('strategy_id') == strategy_id]
        
        return records


class Database:
    """数据库封装类"""
    
    def __init__(self, db_url: Optional[str] = None):
        """
        初始化数据库
        
        Args:
            db_url: 数据库连接URL
        """
        self.db_url = db_url
        self.engine = None
        self.session_factory = None
        self.simple_db = None  # 显式初始化，避免 AttributeError
        
        if SQLALCHEMY_AVAILABLE:
            try:
                if db_url is None:
                    from quant.utils.paths import get_data_paths
                    db_url = f"sqlite:///{get_data_paths()['processed'].as_posix()}/quant.db"
                    self.db_url = db_url
                
                self.engine = create_engine(
                    db_url,
                    echo=False,
                    pool_pre_ping=True,
                    pool_recycle=3600
                )
                Base.metadata.create_all(self.engine)
                Session = sessionmaker(bind=self.engine)
                self.session_factory = Session
                logger.info(f"数据库连接成功: {db_url}")
            except Exception as e:
                logger.error(f"数据库连接失败: {e}")
                self._use_simple_db()
        else:
            self._use_simple_db()
    
    def _use_simple_db(self):
        """使用简化版数据库"""
        self.simple_db = SimpleDatabase()
        logger.info("使用简化版数据库")
    
    def get_session(self):
        """获取数据库会话"""
        if self.simple_db is not None:
            return self.simple_db
        if self.session_factory is not None:
            return self.session_factory()
        raise RuntimeError("数据库未初始化")
    
    def save_stock_data(self, symbol: str, df: pd.DataFrame):
        """保存股票数据"""
        if self.simple_db:
            return self.simple_db.save_stock_data(symbol, df)
        
        session = self.get_session()
        try:
            records = []
            for idx, row in df.iterrows():
                record = StockData(
                    symbol=symbol,
                    trade_date=idx.date() if hasattr(idx, 'date') else idx,
                    open=row.get('open'),
                    high=row.get('high'),
                    low=row.get('low'),
                    close=row.get('close'),
                    volume=row.get('volume'),
                    amount=row.get('amount')
                )
                records.append(record)
            
            session.bulk_save_objects(records)
            session.commit()
            logger.info(f"股票数据已保存: {symbol}, {len(records)}条")
            
        except Exception as e:
            session.rollback()
            logger.error(f"保存股票数据失败: {e}")
        finally:
            session.close()
    
    def get_stock_data(self, symbol: str, start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> pd.DataFrame:
        """获取股票数据"""
        if self.simple_db:
            return self.simple_db.get_stock_data(symbol, start_date, end_date)
        
        session = self.get_session()
        try:
            query = session.query(StockData).filter(StockData.symbol == symbol)
            
            if start_date:
                query = query.filter(StockData.trade_date >= start_date)
            if end_date:
                query = query.filter(StockData.trade_date <= end_date)
            
            records = query.order_by(StockData.trade_date).all()
            
            if not records:
                return pd.DataFrame()
            
            data = [{
                'date': r.trade_date,
                'open': r.open,
                'high': r.high,
                'low': r.low,
                'close': r.close,
                'volume': r.volume,
                'amount': r.amount
            } for r in records]
            
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            
            return df
            
        except Exception as e:
            logger.error(f"获取股票数据失败: {e}")
            return pd.DataFrame()
        finally:
            session.close()
    
    def save_backtest_result(self, result: Dict) -> int:
        """保存回测结果"""
        if self.simple_db:
            return 0
        
        session = self.get_session()
        try:
            record = BacktestResult(
                strategy_id=result.get('strategy_id'),
                start_date=result.get('start_date'),
                end_date=result.get('end_date'),
                initial_cash=result.get('initial_cash'),
                final_value=result.get('final_value'),
                total_return=result.get('total_return'),
                annual_return=result.get('annual_return'),
                sharpe_ratio=result.get('sharpe_ratio'),
                max_drawdown=result.get('max_drawdown'),
                win_rate=result.get('win_rate'),
                total_trades=result.get('total_trades'),
                parameters=result.get('parameters'),
                metrics=result.get('metrics')
            )
            
            session.add(record)
            session.commit()
            
            result_id = record.id
            logger.info(f"回测结果已保存: ID={result_id}")
            return result_id
            
        except Exception as e:
            session.rollback()
            logger.error(f"保存回测结果失败: {e}")
            return -1
        finally:
            session.close()
    
    def get_backtest_results(self, strategy_id: Optional[str] = None,
                            limit: int = 100) -> List[Dict]:
        """获取回测结果"""
        if self.simple_db:
            return []
        
        session = self.get_session()
        try:
            query = session.query(BacktestResult)
            
            if strategy_id:
                query = query.filter(BacktestResult.strategy_id == strategy_id)
            
            records = query.order_by(
                BacktestResult.create_time.desc()
            ).limit(limit).all()
            
            return [{
                'id': r.id,
                'strategy_id': r.strategy_id,
                'start_date': r.start_date,
                'end_date': r.end_date,
                'total_return': r.total_return,
                'annual_return': r.annual_return,
                'sharpe_ratio': r.sharpe_ratio,
                'max_drawdown': r.max_drawdown,
                'create_time': r.create_time
            } for r in records]
            
        except Exception as e:
            logger.error(f"获取回测结果失败: {e}")
            return []
        finally:
            session.close()
    
    # -------------------------------------------------------------------------
    # 新增：日线 upsert 与断点查询（满足 AKShare 数据获取设计）
    # -------------------------------------------------------------------------

    def upsert_stock_daily(self, bars: list[dict]) -> int:
        """
        批量 upsert 日线行情 (INSERT ... ON CONFLICT DO UPDATE，幂等)

        Args:
            bars: DailyBar 字典列表，键对应 StockDaily 列

        Returns:
            写入行数
        """
        if not bars:
            return 0

        session = self.get_session()
        try:
            stmt = sqlite_insert(StockDaily).values(bars)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "trade_date", "adjust_type"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "amount": stmt.excluded.amount,
                    "amplitude": stmt.excluded.amplitude,
                    "change_pct": stmt.excluded.change_pct,
                    "change_amount": stmt.excluded.change_amount,
                    "turnover": stmt.excluded.turnover,
                    "source": stmt.excluded.source,
                    "updated_at": datetime.now(),
                },
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount  # type: ignore[attr-defined]
        except Exception as e:
            session.rollback()
            logger.error(f"upsert_stock_daily 失败: {e}")
            raise
        finally:
            session.close()

    def get_stock_daily(
        self,
        symbol: str,
        start: date,
        end: date,
        adjust_type: str = "qfq"
    ) -> pd.DataFrame:
        """
        查询日线行情

        Returns:
            DataFrame，列：symbol/trade_date/open/high/low/close/volume/amount/
            amplitude/change_pct/change_amount/turnover/source，
            index=trade_date（date 类型），按日期升序
        """
        if self.simple_db:
            return pd.DataFrame()

        session = self.get_session()
        try:
            rows = (
                session.query(StockDaily)
                .filter(
                    StockDaily.symbol == symbol,
                    StockDaily.adjust_type == adjust_type,
                    StockDaily.trade_date >= start,
                    StockDaily.trade_date <= end,
                )
                .order_by(StockDaily.trade_date)
                .all()
            )
            if not rows:
                return pd.DataFrame()

            data = [
                {
                    "symbol": r.symbol,
                    "trade_date": r.trade_date,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                    "amount": r.amount,
                    "amplitude": r.amplitude,
                    "change_pct": r.change_pct,
                    "change_amount": r.change_amount,
                    "turnover": r.turnover,
                    "source": r.source,
                }
                for r in rows
            ]
            df = pd.DataFrame(data)
            df.set_index("trade_date", inplace=True)
            return df
        except Exception as e:
            logger.error(f"get_stock_daily 失败: {e}")
            return pd.DataFrame()
        finally:
            session.close()

    def get_latest_success_fetch(
        self,
        symbol: str,
        adjust_type: str
    ) -> Optional[Dict]:
        """
        查询最近一次成功的拉取记录（用于增量断点）

        Returns:
            dict（含 end_date, fetched_at）或 None
        """
        if self.simple_db:
            return None

        session = self.get_session()
        try:
            row = (
                session.query(DataFetchLog)
                .filter(
                    DataFetchLog.symbol == symbol,
                    DataFetchLog.adjust_type == adjust_type,
                    DataFetchLog.status.in_(["success", "partial"]),
                )
                .order_by(DataFetchLog.fetched_at.desc())
                .first()
            )
            if row is None:
                return None
            return {
                "end_date": row.end_date,
                "fetched_at": row.fetched_at,
                "row_count": row.row_count,
            }
        except Exception as e:
            logger.error(f"get_latest_success_fetch 失败: {e}")
            return None
        finally:
            session.close()

    def insert_fetch_log(self, log: Dict) -> int:
        """
        写入拉取审计日志

        Args:
            log: 字段字典，对应 DataFetchLog 列
        """
        if self.simple_db:
            return 0

        session = self.get_session()
        try:
            record = DataFetchLog(**log)
            session.add(record)
            session.commit()
            return record.id  # type: ignore[return-value]
        except Exception as e:
            session.rollback()
            logger.error(f"insert_fetch_log 失败: {e}")
            return -1
        finally:
            session.close()

    def get_latest_trade_date(
        self,
        symbol: str,
        adjust_type: str = "qfq"
    ) -> Optional[date]:
        """查询库中某标的最新有数据的交易日"""
        if self.simple_db:
            return None

        session = self.get_session()
        try:
            row = (
                session.query(StockDaily.trade_date)
                .filter(
                    StockDaily.symbol == symbol,
                    StockDaily.adjust_type == adjust_type,
                )
                .order_by(StockDaily.trade_date.desc())
                .first()
            )
            return row[0] if row else None
        except Exception as e:
            logger.error(f"get_latest_trade_date 失败: {e}")
            return None
        finally:
            session.close()

    def save_calibration_logs(self, issues: List[Dict]) -> int:
        """
        批量写入校准差异日志

        Args:
            issues: 字段字典列表，对应 DataCalibrationLog 列
        """
        if not issues or self.simple_db:
            return 0

        session = self.get_session()
        try:
            records = [DataCalibrationLog(**issue) for issue in issues]
            session.bulk_save_objects(records)
            session.commit()
            return len(records)
        except Exception as e:
            session.rollback()
            logger.error(f"save_calibration_logs 失败: {e}")
            return 0
        finally:
            session.close()

    def has_successful_fetch_today(
        self,
        symbol: str | None = None,
        adjust_type: str | None = None,
    ) -> bool:
        """
        检查是否存在今日成功的拉取记录

        Args:
            symbol: 标的，None 表示任意标的
            adjust_type: 复权类型，None 表示任意类型
        """
        if self.simple_db:
            return False

        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        session = self.get_session()
        try:
            today_start = datetime.now(ZoneInfo("Asia/Shanghai")).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today_end = today_start + timedelta(days=1)

            query = session.query(DataFetchLog).filter(
                DataFetchLog.fetched_at >= today_start,
                DataFetchLog.fetched_at < today_end,
                DataFetchLog.status.in_(["success", "partial"]),
            )
            if symbol:
                query = query.filter(DataFetchLog.symbol == symbol)
            if adjust_type:
                query = query.filter(DataFetchLog.adjust_type == adjust_type)

            return session.query(query.exists()).scalar() is True
        except Exception as e:
            logger.error(f"has_successful_fetch_today 失败: {e}")
            return False
        finally:
            session.close()

    def close(self):
        """关闭数据库连接"""
        if self.engine:
            self.engine.dispose()
            logger.info("数据库连接已关闭")
