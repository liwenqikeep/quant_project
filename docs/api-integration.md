# 前后端联调契约文档（API Integration）

> 版本 v0.1.0 ｜ 2026-08-19 ｜ 状态：草案
> 本文档是前后端联调的“唯一事实来源”。后端实现与前端消费都以本文档为准；任何接口变更必须先改本文档。

## 1. 目标与范围

- 定义后端对外 HTTP API 的统一约定：协议、响应结构、错误码、分页、鉴权、接口清单与关键数据契约。
- 前端当前处于规划阶段，本契约先行，供前端立项、mock 与联调用。
- 现状说明：当前 `backend/quant/infrastructure/api_server.py` 仍为内存示例（路由 `/api/strategies`、`{success:true}` 响应），未接通真实链路。**实施后端 API 时按本文档统一改造**，不沿用示例格式。

## 2. 基础约定

- 协议：REST over HTTP；请求/响应均为 `application/json; charset=utf-8`。
- 基础路径：`/api/v1`；健康检查 `/health` 不带版本前缀。
- 时间：ISO 8601（`2026-08-19T10:30:00+08:00`）；日期参数 `YYYYMMDD`（与回测配置一致）。
- 金额单位：元（人民币）；比例一律小数（`0.0005` = 万分之五），禁止百分比歧义。
- 股票代码：交易所后缀格式，如 `000001.SZ`、`600519.SH`。

## 3. 统一响应结构

成功：

```json
{
  "code": 0,
  "message": "ok",
  "data": { },
  "request_id": "req_20260819103000_ab12",
  "timestamp": "2026-08-19T10:30:00+08:00"
}
```

失败：

```json
{
  "code": 40001,
  "message": "参数错误：start_date 不能晚于 end_date",
  "data": null,
  "request_id": "req_20260819103000_ab12",
  "timestamp": "2026-08-19T10:30:00+08:00"
}
```

- `code=0` 成功；非 0 失败。HTTP 状态码表达资源层语义（4xx/5xx），`code` 表达业务语义，两者并存。
- `request_id` 由后端生成并写入日志；前端在错误上报时透传。
- 后端禁止直接返回裸 dict；所有 handler 统一走响应包装。

## 4. 错误码表

| code | HTTP | 含义 |
|------|------|------|
| 0 | 200 | 成功 |
| 40000 | 400 | 通用参数错误 |
| 40001 | 400 | 参数格式错误（日期/分页等） |
| 40100 | 401 | 未认证（预留） |
| 40300 | 403 | 无权限（预留） |
| 40400 | 404 | 资源不存在（策略/任务/持仓） |
| 40900 | 409 | 资源冲突（如同名策略） |
| 50000 | 500 | 服务端内部错误 |
| 50300 | 503 | 数据源不可用（akshare/tushare） |
| 50400 | 504 | 回测任务超时（预留） |

## 5. 分页规范

- 请求：`?page=1&page_size=20`；page 从 1 起，page_size 默认 20、上限 100。
- 响应 `data` 结构：

```json
{
  "items": [],
  "total": 137,
  "page": 1,
  "page_size": 20
}
```

## 6. 鉴权（预留）

当前为本地单用户，无需鉴权。暴露公网或上线前必须增加 token/API Key 方案，届时更新本文档。

## 7. 接口清单（草案）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 存活检查 |
| GET | `/api/v1/strategies` | 策略列表 |
| POST | `/api/v1/strategies` | 创建策略 |
| GET | `/api/v1/strategies/{strategy_id}` | 策略详情 |
| POST | `/api/v1/strategies/{strategy_id}/run` | 启动策略（预留） |
| POST | `/api/v1/strategies/{strategy_id}/stop` | 停止策略（预留） |
| POST | `/api/v1/backtest` | 创建回测任务（异步） |
| GET | `/api/v1/backtest/{task_id}` | 回测任务状态/结果 |
| GET | `/api/v1/backtest` | 回测任务列表 |
| GET | `/api/v1/positions` | 当前持仓汇总 |
| GET | `/api/v1/positions/{symbol}` | 单标的持仓 |
| GET | `/api/v1/risk/summary` | 风控摘要（预留） |

## 8. 关键接口数据契约

### POST /api/v1/backtest 请求

```json
{
  "strategy": "MAStrategy",
  "symbol": "000001.SZ",
  "start_date": "20200101",
  "end_date": "20231231",
  "initial_cash": 1000000,
  "params": {
    "short_window": 10,
    "long_window": 30
  }
}
```

### GET /api/v1/backtest/{task_id} 响应 data

```json
{
  "task_id": "bt_20260819103000",
  "status": "success",
  "created_at": "2026-08-19T10:30:00+08:00",
  "finished_at": "2026-08-19T10:30:12+08:00",
  "metrics": {
    "total_return": 0.213,
    "annual_return": 0.082,
    "sharpe_ratio": 1.31,
    "max_drawdown": -0.151,
    "volatility": 0.18,
    "calmar_ratio": 0.54,
    "win_rate": 0.47,
    "profit_loss_ratio": 1.82,
    "avg_holding_days": 4.3,
    "total_cost_ratio": 0.0031
  },
  "equity_curve": [
    { "date": "2020-01-02", "total_value": 1000000.0 }
  ],
  "trades": [
    {
      "date": "2020-01-03",
      "symbol": "000001.SZ",
      "side": "buy",
      "price": 16.2,
      "amount": 20000.0,
      "pnl": null,
      "commission": 6.0
    }
  ]
}
```

口径说明：`status` 状态机为 `pending → running → success/failed`；`max_drawdown` 统一负值；信号 t+1 执行；成本含佣金/滑点/印花税；`total_cost_ratio = 总成本 / 总成交额`。

## 9. 前后端联调流程

1. 契约先行：新接口先在本文档定契约（含数据样例）再开发。
2. Mock：前端按本文档 mock 数据，不等待后端。
3. 联调：本地启动后端，跑通主链路（策略 → 回测 → 结果）。
4. 检查清单：
   - [ ] 请求/响应 JSON 与本文档一致
   - [ ] 错误按错误码表分类处理，前端不解析后端报错文本
   - [ ] 时间、金额、比例口径一致
   - [ ] 分页参数与 total 正确
   - [ ] CORS 已配置（本地开发允许 localhost 来源）
   - [ ] request_id 随错误上报
5. 变更流程：任何接口变更 → 先改本文档 → 后端实现 → 前端同步；禁止两端各改各的。

## 10. 后端实现要求

- 路由前缀统一 `/api/v1`；健康检查 `/health`。
- 所有 handler 统一响应包装（第 3 节），禁止返回裸 dict。
- 回测任务异步化（后台线程/队列），状态机 `pending → running → success/failed`。
- 日志包含 request_id；错误堆栈只写服务端日志，不返回给前端。
- 指标计算复用 `PerformanceAnalyzer` 公共实现，禁止接口层另算一套。
