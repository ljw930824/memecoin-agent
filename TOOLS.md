# TOOLS.md

### BAW CLI
- 登录: `baw auth signin --image`（后台运行，QR 保存到 D:\Temp\，用户扫码确认）
- `baw wallet status` / `balance` / `address --chain {56|solana}`
- balance 字段名是 `contractAddress`（非 `address`）

### Windows Task Scheduler 静默执行规范
创建或修改定时任务时，必须同时满足以下条件，否则会弹出 CMD 窗口：
1. **安全选项**: 勾选"不管用户是否登录都要运行"（Run whether user is logged on or not）
2. **安全选项**: 勾选"使用最高权限运行"（Run with highest privileges）
3. PowerShell 参数加 `-WindowStyle Hidden`
4. Settings.Hidden = $true（Task Scheduler UI 隐藏）

⚠️ 仅靠 `-WindowStyle Hidden` 仍会闪窗，必须用 Session 0 运行模式才能彻底静默。

### onchainos
- 价格: `token price-info`（不用 swap quote 的 tokenUnitPrice，是缓存值）
- WS 不可用（reconnecting），REST 够用
- OKX 环境变量: OKX_PROD_API_KEY / OKX_PROD_SECRET_KEY / OKX_PROD_PASSPHRASE

### Telegram 插件维护
- 依赖包: `grammy` + `@grammyjs/runner` + `@grammyjs/transformer-throttler`
- 安装位置: `D:\Program Files\QClaw\resources\openclaw\node_modules\openclaw\node_modules\`
- 安装命令: `cd <上述路径>; npm install grammy --save --legacy-peer-deps`
- 排查日志: `D:\Temp\openclaw\openclaw-YYYY-MM-DD.log` 搜索 `telegram failed`
- 完整排查指南: `memory/telegram-troubleshooting-guide.md`
