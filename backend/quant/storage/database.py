"""
数据库操作模块
基于SQLAlchemy的数据持久化
"""
import pandas as pd
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from dataclasses import dataclass
from pathlib import Path
import json
from quant.utils.logger import logger

try:
    from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Date, Text, JSON
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker, Session
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    logger.warning("SQLAlchemy未安装，将使用简化版存储")


# 数据模型定义
if SQLALCHEMY_AVAILABLE:
    Base = declarative_base()


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
    
    def close(self):
        """关闭数据库连接"""
        if self.engine:
            self.engine.dispose()
            logger.info("数据库连接已关闭")
