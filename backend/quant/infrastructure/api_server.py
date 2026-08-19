"""
API服务器模块
提供REST API接口
"""
import json
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from quant.utils.logger import logger

try:
    from flask import Flask, request, jsonify
    from flask_cors import CORS
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    logger.warning("Flask未安装，API服务功能受限")


@dataclass
class APIRoute:
    """API路由"""
    path: str
    method: str
    handler: Callable
    description: str = ""


class APIServer:
    """API服务器"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
        """
        初始化API服务器
        
        Args:
            host: 监听地址
            port: 监听端口
        """
        self.host = host
        self.port = port
        self.app = None
        self.routes: List[APIRoute] = []
        
        if FLASK_AVAILABLE:
            self.app = Flask(__name__)
            CORS(self.app)
            self._register_default_routes()
            logger.info(f"API服务器初始化: {host}:{port}")
        else:
            logger.warning("Flask未安装，无法启动API服务")
    
    def _register_default_routes(self):
        """注册默认路由"""
        @self.app.route('/health', methods=['GET'])
        def health():
            return jsonify({
                'status': 'healthy',
                'timestamp': datetime.now().isoformat()
            })
        
        @self.app.route('/api/info', methods=['GET'])
        def info():
            return jsonify({
                'name': '量化交易系统API',
                'version': '1.0.0',
                'timestamp': datetime.now().isoformat()
            })
    
    def add_route(
        self,
        path: str,
        method: str = 'GET',
        handler: Optional[Callable] = None
    ):
        """添加路由"""
        if handler is None:
            def decorator(f):
                self._add_handler(path, method, f)
                return f
            return decorator
        else:
            self._add_handler(path, method, handler)
    
    def _add_handler(self, path: str, method: str, handler: Callable):
        """添加处理器"""
        if not FLASK_AVAILABLE:
            return
        
        def wrapped_handler(*args, **kwargs):
            try:
                result = handler(*args, **kwargs)
                return jsonify({'success': True, 'data': result})
            except Exception as e:
                logger.error(f"API处理错误: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        if method == 'GET':
            self.app.add_url_rule(path, path, wrapped_handler, methods=['GET'])
        elif method == 'POST':
            self.app.add_url_rule(path, path, wrapped_handler, methods=['POST'])
        elif method == 'PUT':
            self.app.add_url_rule(path, path, wrapped_handler, methods=['PUT'])
        elif method == 'DELETE':
            self.app.add_url_rule(path, path, wrapped_handler, methods=['DELETE'])
        else:
            self.app.add_url_rule(path, path, wrapped_handler, methods=[method])
        
        self.routes.append(APIRoute(path=path, method=method, handler=handler))
        logger.info(f"已注册路由: {method} {path}")
    
    def get(self, path: str):
        """添加GET路由装饰器"""
        return self.add_route(path, 'GET')
    
    def post(self, path: str):
        """添加POST路由装饰器"""
        return self.add_route(path, 'POST')
    
    def put(self, path: str):
        """添加PUT路由装饰器"""
        return self.add_route(path, 'PUT')
    
    def delete(self, path: str):
        """添加DELETE路由装饰器"""
        return self.add_route(path, 'DELETE')
    
    def run(self, debug: bool = False):
        """启动服务器"""
        if not FLASK_AVAILABLE:
            logger.error("Flask未安装，无法启动服务器")
            return
        
        logger.info(f"启动API服务器: {self.host}:{self.port}")
        self.app.run(host=self.host, port=self.port, debug=debug)
    
    def stop(self):
        """停止服务器"""
        logger.info("API服务器已停止")
    
    def get_routes(self) -> List[Dict]:
        """获取路由列表"""
        return [
            {'path': r.path, 'method': r.method, 'description': r.description}
            for r in self.routes
        ]


# 策略API示例
class StrategyAPI:
    """策略API"""
    
    def __init__(self, server: APIServer):
        self.server = server
        self.strategies = {}
        self._register_routes()
    
    def _register_routes(self):
        """注册策略相关路由"""
        @self.server.get('/api/strategies')
        def list_strategies():
            return list(self.strategies.keys())
        
        @self.server.get('/api/strategies/<name>')
        def get_strategy(name: str):
            if name not in self.strategies:
                return {'error': '策略不存在'}, 404
            return self.strategies[name]
        
        @self.server.post('/api/strategies')
        def create_strategy():
            data = request.get_json()
            name = data.get('name')
            if not name:
                return {'error': '策略名称不能为空'}, 400
            self.strategies[name] = data
            return {'success': True, 'strategy': data}
        
        @self.server.post('/api/strategies/<name>/run')
        def run_strategy(name: str):
            if name not in self.strategies:
                return {'error': '策略不存在'}, 404
            # 执行策略逻辑
            return {'success': True, 'message': f'策略{name}已启动'}
        
        @self.server.post('/api/strategies/<name>/stop')
        def stop_strategy(name: str):
            if name not in self.strategies:
                return {'error': '策略不存在'}, 404
            # 停止策略逻辑
            return {'success': True, 'message': f'策略{name}已停止'}


# 持仓API示例
class PositionAPI:
    """持仓API"""
    
    def __init__(self, server: APIServer, position_tracker=None):
        self.server = server
        self.position_tracker = position_tracker
        self._register_routes()
    
    def _register_routes(self):
        """注册持仓相关路由"""
        @self.server.get('/api/positions')
        def list_positions():
            if self.position_tracker:
                return self.position_tracker.get_position_summary()
            return {}
        
        @self.server.get('/api/positions/<symbol>')
        def get_position(symbol: str):
            if self.position_tracker:
                pos = self.position_tracker.get_position(symbol)
                if pos:
                    return {
                        'symbol': pos.symbol,
                        'shares': pos.shares,
                        'avg_cost': pos.avg_cost,
                        'market_value': pos.market_value,
                        'unrealized_pnl': pos.unrealized_pnl
                    }
            return {'error': '持仓不存在'}, 404


# 回测API示例
class BacktestAPI:
    """回测API"""
    
    def __init__(self, server: APIServer):
        self.server = server
        self.backtests = {}
        self._register_routes()
    
    def _register_routes(self):
        """注册回测相关路由"""
        @self.server.post('/api/backtest')
        def create_backtest():
            data = request.get_json()
            task_id = f"bt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            self.backtests[task_id] = {
                'task_id': task_id,
                'status': 'running',
                'created_at': datetime.now().isoformat()
            }
            return {'success': True, 'task_id': task_id}
        
        @self.server.get('/api/backtest/<task_id>')
        def get_backtest(task_id: str):
            if task_id not in self.backtests:
                return {'error': '回测任务不存在'}, 404
            return self.backtests[task_id]
        
        @self.server.get('/api/backtest')
        def list_backtests():
            return list(self.backtests.values())


if __name__ == '__main__':
    # 示例用法
    server = APIServer(host='0.0.0.0', port=5000)
    
    # 添加自定义路由
    @server.get('/api/hello')
    def hello():
        return {'message': 'Hello from Quant System'}
    
    # 启动服务器
    server.run(debug=True)
