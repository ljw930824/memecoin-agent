# Version log

## 2026-08-18 — v3.5-fast

- 将工作区路径从旧 OpenClaw/QClaw 固定目录改为仓库根目录，可用 `QCLAW_WORKSPACE` 覆盖。
- 将 OKX DEX WebSocket 设为主信号链路；健康连接空闲时不再重复阻塞 REST 轮询。
- 为持仓按代币动态订阅 OKX `price` / `price-info` 频道，价格事件只进入退出检查，不生成入场信号；平仓后自动取消订阅。
- 默认快速止盈改为 +10% 全仓退出，并保留 `FAST_EXIT_MODE=0` 兼容旧阶梯模式。
- 统一 WS/REST 时间、链、地址、交易类型字段；增加队列丢弃计数、断线重连、状态文件锁和 REST 兜底。
- 安全评分最低开仓门槛统一为 70，推荐分为 80。
- 离线验证：12 个 Python 文件通过 AST 解析，9 个单元测试通过；未连接交易所，未执行真实交易。

## 2026-08-18 — dashboard

- 新增 `scripts/dashboard/dashboard_server.py` 和 `index.html`：本地只读看板读取模拟盘状态、运行心跳、持仓、PnL、风控、交易历史和日志，每 2 秒刷新。
- 新增 `start_simulation_dashboard.ps1`，用于启动 Dashboard 和 dry-run；当前实际观察使用持续终端会话，避免受限环境回收后台子进程。
- 模拟盘加入运行心跳文件 `data/sm_monitor_runtime_dryrun.json`；REST 兜底 tracker 调用增加 8 秒超时，避免看板长期无状态更新。
- 当前环境 Python 3.7，依赖下限调整为 `websocket-client>=1.6,<2`，并安装 1.6.1。
- Dashboard API 验证通过 HTTP 200；模拟盘当前保持运行，`WS 未就绪 / REST 兜底`，原因是本地网络策略阻止 OKX 套接字（WinError 10013）。
