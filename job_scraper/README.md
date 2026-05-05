# 智能求职匹配系统 v2.0

## 功能
- **简历解析**: PDF/DOCX → 结构化候选人画像（技能、经验、教育）
- **智能匹配**: 三层评分（关键词30% + LLM语义40% + 规则30%）
- **多站聚合**: Indeed + LinkedIn 统一搜索
- **自动降级**: LLM免费API优先 → 付费API兜底 → 纯关键词匹配
- **断点续传**: 中断后继续上次进度

## 快速开始

### 1. 放入简历
```
cp your_resume.pdf job_scraper/resume/resume.pdf
```

### 2. 配置API Key（可选，不配也能用）
编辑 `config.yaml`，填入免费的 Gemini API Key：
```yaml
llm:
  gemini:
    api_key: "your-key"  # 从 https://aistudio.google.com/apikey 获取
```

### 3. 运行
```bash
cd job_scraper
python pipeline.py
```

### 命令行参数
```bash
python pipeline.py                           # 完整运行
python pipeline.py --skip-scraping           # 跳过爬取，只重新匹配
python pipeline.py --resume path/to/resume   # 指定简历
python pipeline.py --test-llm                # 测试LLM连接
```

## 文件结构
```
job_scraper/
├── config.yaml          # 配置（API、筛选规则、权重）
├── models.py            # 数据模型
├── resume_parser.py     # 简历解析器
├── llm_client.py        # 多LLM客户端（自动降级）
├── matcher.py           # 智能匹配引擎
├── indeed_scraper.py    # Indeed爬虫
├── linkedin_scraper.py  # LinkedIn爬虫
├── pipeline.py          # 主流程
├── resume/              # 放简历文件
└── matched_jobs/        # 输出结果
```

## 配置说明

### 筛选规则
- `salary_min/max`: 薪资范围过滤
- `blocked_titles`: 屏蔽职位（如 senior、intern）
- `blocked_locations`: 屏蔽地区
- `require_visa_sponsorship`: 是否需要签证
- `max_posting_age_days`: 最大发布天数

### 匹配权重
- `keyword_weight`: 关键词匹配权重（默认30%）
- `semantic_weight`: LLM语义匹配权重（默认40%）
- `rule_weight`: 规则匹配权重（默认30%）
- `auto_apply_threshold`: ≥80分自动推荐
- `review_threshold`: ≥60分标记待审核

### 免费LLM API
| Provider | 免费额度 | 获取地址 |
|----------|---------|---------|
| Gemini 2.0 Flash | 15 RPM, 100万tokens/月 | https://aistudio.google.com/apikey |
| 智谱GLM-4 Flash | 免费试用额度 | https://open.bigmodel.cn |
| 通义千问 | 免费额度 | https://dashscope.aliyuncs.com |

降级顺序: Gemini → 智谱 → 通义 → DeepSeek
