# TOOLS.md

### BAW CLI
- 登录: `baw auth signin --image`（后台运行，QR 保存到 D:\Temp\，用户扫码确认）
- `baw wallet status` / `balance` / `address --chain {56|solana}`
- balance 字段名是 `contractAddress`（非 `address`）

### onchainos
- 价格: `token price-info`（不用 swap quote 的 tokenUnitPrice，是缓存值）
- WS 不可用（reconnecting），REST 够用
- OKX 环境变量: OKX_PROD_API_KEY / OKX_PROD_SECRET_KEY / OKX_PROD_PASSPHRASE
