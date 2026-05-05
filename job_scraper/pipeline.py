"""
主流程管线
加载简历 → 搜索职位 → 智能匹配 → 输出推荐
支持断点续传、多站点聚合
"""
import os
import sys
import json
import time
import yaml
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from models import JobPosting, CandidateProfile, MatchResult

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))


def load_config(config_path: str = None) -> dict:
    """加载配置"""
    if config_path is None:
        config_path = str(Path(__file__).parent / "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_checkpoint(path: str = "checkpoint.json") -> dict:
    """加载断点"""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_queries": [], "seen_urls": [], "last_run": None}


def save_checkpoint(checkpoint: dict, path: str = "checkpoint.json"):
    """保存断点"""
    checkpoint["last_run"] = datetime.now().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


class JobPipeline:
    """求职管线"""

    def __init__(self, config: dict = None, config_path: str = None):
        self.config = config or load_config(config_path)
        self.checkpoint = load_checkpoint()
        self.results: List[MatchResult] = []
        self.all_jobs: List[JobPosting] = []
        self.profile: CandidateProfile = None
        self.llm_client = None
        self.matcher = None

    def run(self, skip_scraping: bool = False, resume_path: str = None):
        """
        运行完整管线。
        
        Args:
            skip_scraping: 跳过爬取，使用已有数据（用于调试匹配逻辑）
            resume_path: 简历文件路径（覆盖配置）
        """
        print("=" * 60)
        print("  智能求职匹配系统 v2.0")
        print("=" * 60)
        start_time = time.time()

        # 1. 初始化LLM
        print("\n[1/6] 初始化LLM...")
        self._init_llm()

        # 2. 解析简历
        print("\n[2/6] 解析简历...")
        self._load_resume(resume_path)

        # 3. 爬取职位
        if not skip_scraping:
            print("\n[3/6] 爬取职位...")
            self._scrape_jobs()
        else:
            print("\n[3/6] 跳过爬取 (skip_scraping=True)")
            self._load_existing_jobs()

        # 4. 智能匹配
        print(f"\n[4/6] 智能匹配 ({len(self.all_jobs)}个职位)...")
        self._match_jobs()

        # 5. 输出结果
        print("\n[5/6] 输出结果...")
        self._save_results()

        # 6. 统计摘要
        elapsed = time.time() - start_time
        print(f"\n[6/6] 完成! 耗时 {elapsed:.0f}秒")
        self._print_summary()

    def _init_llm(self):
        """初始化LLM客户端"""
        try:
            from llm_client import LLMClient
            self.llm_client = LLMClient(self.config)
            if self.llm_client.is_available:
                print(f"  LLM已就绪: {self.llm_client.provider}")
            else:
                print("  [WARN] LLM未配置API Key，将使用纯关键词匹配")
                print("  提示: 在config.yaml中填入Gemini API Key启用语义匹配")
                self.llm_client = None
        except ImportError:
            print("  [WARN] openai包未安装，LLM不可用")
            self.llm_client = None

    def _load_resume(self, resume_path: str = None):
        """加载并解析简历"""
        from resume_parser import parse_resume

        path = resume_path or self.config.get("resume_path", "resume/resume.pdf")
        if not os.path.exists(path):
            # 尝试在resume/目录下找任意文件
            resume_dir = Path("resume")
            if resume_dir.exists():
                files = list(resume_dir.glob("*.*"))
                if files:
                    path = str(files[0])

        if not os.path.exists(path):
            print(f"  [ERROR] 未找到简历文件: {path}")
            print("  请将简历 (PDF/DOCX) 放到 resume/ 目录下")
            sys.exit(1)

        self.profile = parse_resume(path, self.llm_client)
        print(f"  简历: {path}")
        print(f"  姓名: {self.profile.name or '(未识别)'}")
        print(f"  邮箱: {self.profile.email}")
        print(f"  经验: {self.profile.experience_years}年")
        print(f"  技能: {', '.join(self.profile.skills[:15])}")
        if len(self.profile.skills) > 15:
            print(f"        ...共{len(self.profile.skills)}项")

    def _scrape_jobs(self):
        """爬取职位"""
        queries = self.config.get("search_queries", [])
        completed = set(self.checkpoint.get("completed_queries", []))

        for i, q in enumerate(queries):
            query = q.get("query", "")
            location = q.get("location", "United States")
            site = q.get("site", "indeed")
            query_key = f"{site}:{query}@{location}"

            if query_key in completed:
                print(f"  跳过已完成: {query_key}")
                continue

            print(f"\n  --- [{i+1}/{len(queries)}] {query_key} ---")

            jobs = []
            if site == "indeed":
                jobs = self._scrape_indeed(query, location)
            elif site == "linkedin":
                jobs = self._scrape_linkedin(query, location)

            self.all_jobs.extend(jobs)

            # 更新断点
            completed.add(query_key)
            self.checkpoint["completed_queries"] = list(completed)
            save_checkpoint(self.checkpoint)

        # 去重
        seen = set()
        unique_jobs = []
        for job in self.all_jobs:
            key = f"{job.title.lower()}_{job.company.lower()}"
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)
        self.all_jobs = unique_jobs

        # 保存原始数据
        self._save_raw_jobs()
        print(f"\n  总计: {len(self.all_jobs)}个去重职位")

    def _scrape_indeed(self, query: str, location: str) -> List[JobPosting]:
        """爬取Indeed"""
        try:
            from indeed_scraper import IndeedScraper
            scraper = IndeedScraper(self.config)
            jobs = scraper.search(query, location)
            scraper.close()
            return jobs
        except Exception as e:
            print(f"  Indeed爬取出错: {e}")
            return []

    def _scrape_linkedin(self, query: str, location: str) -> List[JobPosting]:
        """爬取LinkedIn"""
        try:
            from linkedin_scraper import LinkedInScraper
            scraper = LinkedInScraper(self.config)
            jobs = scraper.search(query, location)
            scraper.close()
            return jobs
        except Exception as e:
            print(f"  LinkedIn爬取出错: {e}")
            return []

    def _load_existing_jobs(self):
        """从文件加载已有职位数据"""
        path = "scraped_jobs.json"
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.all_jobs = [JobPosting(**j) for j in data]
            print(f"  加载了 {len(self.all_jobs)} 个职位")
        else:
            print("  无已有数据，请先运行爬取")

    def _match_jobs(self):
        """智能匹配"""
        from matcher import JobMatcher
        self.matcher = JobMatcher(self.config, self.llm_client)

        if not self.all_jobs:
            print("  无职位可匹配")
            return

        # 使用批量匹配（节省LLM调用）
        self.results = self.matcher.match_batch(
            self.all_jobs, self.profile,
            batch_size=5
        )

        # 统计
        apply_count = sum(1 for r in self.results if r.recommendation == "apply")
        review_count = sum(1 for r in self.results if r.recommendation == "review")
        skip_count = sum(1 for r in self.results if r.recommendation == "skip")
        print(f"  推荐投递: {apply_count} | 待审核: {review_count} | 跳过: {skip_count}")

    def _save_results(self):
        """保存匹配结果"""
        output_dir = self.config.get("output", {}).get("directory", "matched_jobs")
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 全部结果
        all_path = os.path.join(output_dir, f"all_results_{timestamp}.json")
        with open(all_path, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in self.results], f, ensure_ascii=False, indent=2)

        # 推荐投递的
        apply_results = [r for r in self.results if r.recommendation == "apply"]
        if apply_results:
            apply_path = os.path.join(output_dir, f"recommended_{timestamp}.json")
            with open(apply_path, "w", encoding="utf-8") as f:
                json.dump([r.to_dict() for r in apply_results], f, ensure_ascii=False, indent=2)

        # 推荐投递的 (Markdown)
        md_path = os.path.join(output_dir, f"report_{timestamp}.md")
        self._save_markdown_report(md_path)

        print(f"  结果保存至: {output_dir}/")
        print(f"  - 全部结果: {len(self.results)}条")
        print(f"  - 推荐投递: {len(apply_results)}条")
        print(f"  - 报告: {md_path}")

    def _save_markdown_report(self, path: str):
        """生成Markdown报告"""
        lines = [
            f"# 智能求职匹配报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"候选人: {self.profile.name or '(未识别)'} | 经验: {self.profile.experience_years}年",
            f"技能: {', '.join(self.profile.skills[:20])}",
            "",
            "---",
            "",
        ]

        for rec_type, label in [("apply", "## 推荐投递"), ("review", "## 待审核"), ("skip", "## 已跳过")]:
            results = [r for r in self.results if r.recommendation == rec_type]
            if not results:
                continue
            lines.append(f"{label} ({len(results)}个)")
            lines.append("")

            for i, r in enumerate(results[:20], 1):
                job = r.job
                lines.append(f"### {i}. {job.title} @ {job.company}")
                lines.append(f"- **分数**: {r.total_score:.0f}/100")
                lines.append(f"- **地点**: {job.location} | **薪资**: {job.salary_text or '未标注'}")
                lines.append(f"- **来源**: {job.source} | **匹配技能**: {', '.join(r.matched_skills[:10]) or '无'}")
                if r.missing_skills:
                    lines.append(f"- **缺失技能**: {', '.join(r.missing_skills[:5])}")
                if r.llm_analysis:
                    lines.append(f"- **AI分析**: {r.llm_analysis}")
                lines.append(f"- **链接**: [{job.title}]({job.url})")
                lines.append("")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _save_raw_jobs(self):
        """保存原始爬取数据"""
        if self.all_jobs:
            with open("scraped_jobs.json", "w", encoding="utf-8") as f:
                json.dump([j.to_dict() for j in self.all_jobs], f, ensure_ascii=False, indent=2)

    def _print_summary(self):
        """打印统计摘要"""
        print("\n" + "=" * 60)
        print("  匹配结果摘要")
        print("=" * 60)

        if not self.results:
            print("  无结果")
            return

        apply_results = [r for r in self.results if r.recommendation == "apply"]
        review_results = [r for r in self.results if r.recommendation == "review"]

        if apply_results:
            print(f"\n  推荐投递 ({len(apply_results)}个):")
            for i, r in enumerate(apply_results[:10], 1):
                job = r.job
                print(f"    {i}. [{r.total_score:.0f}分] {job.title} @ {job.company}")
                print(f"       {job.location} | {job.salary_text or '薪资未标注'} | {job.source}")

        if review_results:
            print(f"\n  待审核 ({len(review_results)}个):")
            for i, r in enumerate(review_results[:5], 1):
                job = r.job
                print(f"    {i}. [{r.total_score:.0f}分] {job.title} @ {job.company}")

        # 技能差距分析
        all_missing = {}
        for r in self.results:
            if r.recommendation in ("apply", "review"):
                for skill in r.missing_skills:
                    all_missing[skill] = all_missing.get(skill, 0) + 1

        if all_missing:
            print(f"\n  常见技能差距 (推荐职位要求但你缺少的):")
            sorted_missing = sorted(all_missing.items(), key=lambda x: -x[1])[:10]
            for skill, count in sorted_missing:
                print(f"    - {skill}: 出现在{count}个职位中")


def main():
    """入口"""
    import argparse
    parser = argparse.ArgumentParser(description="智能求职匹配系统")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--resume", default=None, help="简历文件路径")
    parser.add_argument("--skip-scraping", action="store_true", help="跳过爬取，使用已有数据")
    parser.add_argument("--test-llm", action="store_true", help="测试LLM连接")
    args = parser.parse_args()

    if args.test_llm:
        from llm_client import LLMClient
        config = load_config(args.config)
        client = LLMClient(config)
        results = client.test_connection()
        for provider, result in results.items():
            status = "OK" if result["status"] == "ok" else "FAIL"
            print(f"  {provider}: {status}")
            if result["status"] == "ok":
                print(f"    模型: {result.get('model', '?')}")
                print(f"    响应: {result.get('response', '')[:80]}")
            else:
                print(f"    错误: {result.get('error', '')[:100]}")
        return

    pipeline = JobPipeline(config_path=args.config)
    pipeline.run(skip_scraping=args.skip_scraping, resume_path=args.resume)


if __name__ == "__main__":
    main()
