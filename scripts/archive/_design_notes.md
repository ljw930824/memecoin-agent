# 数据归档策略设计与实现

## 目标
解决 data/ 目录膨胀问题（901文件，852个state备份），设计文件归档策略。

## 问题分析
- `smart-money-state_bak_*`: 852个文件，5min间隔自动备份，10MB
- `sm_wallets.json`: 10.4MB，每次sim加载1-2s
- 清仓记录没有归档，混合在 state 中
- 回测数据没有从归档读取的机制

## 实现: scripts/archive/data_archive_manager.py

### 时间衰减规则
- <24h: 全部保留（5min精度）
- 24h-7d: 保留每小时1个（144个）
- 7d-30d: 保留每天1个（23个）
- >30d: 删除（已归档）

### 归档目录结构
```
data/
  archive/
    backups/           # 旧state备份
    closed_positions/  # 按日期归档的清仓记录
      closed_2026-05-01.json
      closed_2026-05-02.json
    wallet_snapshots/  # 钱包快照（时间衰减）
    logs/              # 旧日志
```

### 集成API
- `auto_archive(state_file, decay_interval=12)` — monitor每cycle调用
- `on_sell_closed(position_data)` — 清仓后调用
- `load_closed_positions(chain, date_from, date_to)` — 回测读取
- `run_full_archive(dry_run=False)` — 完整归档

### 实际效果
- Before: 901 files (852 backups)
- After: 180 files in data/ (133 backups) + 719 in archive/
- 文件数减少 721 (-80%)

### 下一步
- [ ] 集成到 realtime_sm_monitor.py 和 sm_monitor_sim.py
- [ ] 交易日志轮转（超过30天的移入archive/logs/）
- [ ] 钱包文件精简（sim只读需要的字段，不加载全部10MB）
