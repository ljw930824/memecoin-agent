# Commit 规范

## 格式
```
<type>(<scope>): <description>

Refs: #<issue-number>
```

## Type 说明
| type | 含义 |
|------|------|
| feat | 新功能 |
| fix | Bug 修复 |
| refactor | 重构（不改功能） |
| docs | 文档 |
| chore | 构建/工具/配置 |
| test | 测试 |
| perf | 性能优化 |

## 示例
```
feat(risk): 添加阶梯止盈逻辑 Refs: #5

- +30% 卖 77% 回本
- +100% 卖 50% 收利润
- +300% 卖 50% 博大奖
```

```
fix(sell): 金额精度超 6 位导致下单失败 Refs: #2

所有 sell amount 统一 round(x, 6)
```

## 规则
1. 每次有意义的改动单独 commit，不要混在一起
2. commit message 关联 Issue 编号
3. 重要功能先建 Issue 再写代码
4. 禁止 commit 中包含 API Key / Token / Secret
