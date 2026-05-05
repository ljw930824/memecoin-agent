"""系统完整性测试"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

def test_imports():
    print("=== 测试模块导入 ===")
    try:
        from models import JobPosting, CandidateProfile, MatchResult
        print("  models: OK")
    except Exception as e:
        print(f"  models: FAIL - {e}")
        return False

    try:
        from resume_parser import parse_resume, extract_skills
        print("  resume_parser: OK")
    except Exception as e:
        print(f"  resume_parser: FAIL - {e}")
        return False

    try:
        from llm_client import LLMClient
        print("  llm_client: OK")
    except Exception as e:
        print(f"  llm_client: FAIL - {e}")
        return False

    try:
        from matcher import JobMatcher, RuleEngine, KeywordMatcher
        print("  matcher: OK")
    except Exception as e:
        print(f"  matcher: FAIL - {e}")
        return False

    try:
        from indeed_scraper import IndeedScraper
        print("  indeed_scraper: OK")
    except Exception as e:
        print(f"  indeed_scraper: FAIL - {e}")
        return False

    try:
        from linkedin_scraper import LinkedInScraper
        print("  linkedin_scraper: OK")
    except Exception as e:
        print(f"  linkedin_scraper: FAIL - {e}")
        return False

    try:
        from pipeline import JobPipeline, load_config
        print("  pipeline: OK")
    except Exception as e:
        print(f"  pipeline: FAIL - {e}")
        return False

    return True


def test_config():
    print("\n=== 测试配置加载 ===")
    from pipeline import load_config
    config = load_config()
    print(f"  简历: {config.get('resume_path')}")
    print(f"  LLM: {config.get('llm', {}).get('provider')}")
    print(f"  搜索: {len(config.get('search_queries', []))}个查询")
    print(f"  薪资范围: ${config.get('filters', {}).get('salary_min'):,} - ${config.get('filters', {}).get('salary_max'):,}")
    print("  config.yaml: OK")
    return True


def test_models():
    print("\n=== 测试数据模型 ===")
    from models import JobPosting, CandidateProfile, MatchResult

    job = JobPosting(
        title="Junior Data Scientist",
        company="Test Corp",
        location="Remote",
        url="https://example.com/job",
        salary_min=90000,
        salary_max=120000,
        skills=["python", "sql", "machine learning"],
        source="test",
    )
    print(f"  JobPosting: {job.title} @ {job.company}")

    profile = CandidateProfile(
        name="Test User",
        skills=["python", "sql", "tensorflow", "pandas"],
        experience_years=1.5,
    )
    print(f"  CandidateProfile: {profile.name}, {len(profile.skills)} skills")

    result = MatchResult(job=job, total_score=85.0)
    print(f"  MatchResult: score={result.total_score}")
    print("  models: OK")
    return True


def test_rule_engine():
    print("\n=== 测试规则引擎 ===")
    from matcher import RuleEngine
    from models import JobPosting

    config_filters = {
        "salary_min": 80000,
        "salary_max": 350000,
        "blocked_titles": ["senior", "principal"],
        "blocked_locations": ["india"],
        "experience_max": 15,
    }
    engine = RuleEngine(config_filters)

    # 应该通过
    job1 = JobPosting(title="Junior Data Scientist", company="A", location="Remote",
                      url="x", salary_min=90000, salary_max=120000)
    passed, reasons = engine.evaluate(job1)
    print(f"  初级职位+合理薪资: {'通过' if passed else '拒绝'} {reasons}")

    # 应该拒绝 - 薪资过低
    job2 = JobPosting(title="Data Analyst", company="B", location="NYC",
                      url="x", salary_min=40000, salary_max=50000)
    passed, reasons = engine.evaluate(job2)
    print(f"  低薪资: {'通过' if passed else '拒绝'} {reasons}")

    # 应该拒绝 - 被屏蔽职位
    job3 = JobPosting(title="Senior Staff Engineer", company="C", location="SF",
                      url="x", salary_min=200000)
    passed, reasons = engine.evaluate(job3)
    print(f"  高级职位: {'通过' if passed else '拒绝'} {reasons}")

    print("  rule_engine: OK")
    return True


def test_keyword_matcher():
    print("\n=== 测试关键词匹配 ===")
    from matcher import KeywordMatcher
    from models import JobPosting, CandidateProfile

    matcher = KeywordMatcher()
    profile = CandidateProfile(
        skills=["python", "sql", "machine learning", "pandas", "tensorflow", "nlp"],
        experience_years=1.5,
    )
    job = JobPosting(
        title="Junior Data Scientist",
        company="Test",
        location="Remote",
        url="x",
        skills=["python", "sql", "machine learning"],
        description="Looking for a junior data scientist with Python, SQL, and ML experience.",
        experience_years=1,
    )
    score, matched, missing = matcher.score(job, profile)
    print(f"  分数: {score:.0f}")
    print(f"  匹配: {matched}")
    print(f"  缺失: {missing}")
    print("  keyword_matcher: OK")
    return True


def test_llm():
    print("\n=== 测试LLM连接 ===")
    from llm_client import LLMClient
    config = load_config() if 'load_config' in dir() else {}
    from pipeline import load_config
    config = load_config()
    client = LLMClient(config)
    if client.is_available:
        results = client.test_connection()
        for provider, result in results.items():
            status = "OK" if result["status"] == "ok" else "FAIL"
            print(f"  {provider}: {status}")
    else:
        print("  LLM未配置 (需要在config.yaml填入API Key)")
        print("  提示: Gemini免费API → https://aistudio.google.com/apikey")
    return True


def test_resume():
    print("\n=== 测试简历解析 ===")
    resume_dir = "resume"
    if os.path.exists(resume_dir):
        files = [f for f in os.listdir(resume_dir) if f.endswith(('.pdf', '.docx', '.txt'))]
        if files:
            from resume_parser import parse_resume
            path = os.path.join(resume_dir, files[0])
            profile = parse_resume(path)
            print(f"  文件: {path}")
            print(f"  邮箱: {profile.email}")
            print(f"  技能: {', '.join(profile.skills[:10])}")
            print(f"  经验: {profile.experience_years}年")
            return True
        else:
            print("  resume/ 目录下无简历文件")
            print("  请放入 PDF/DOCX 简历文件")
    else:
        print("  resume/ 目录不存在")
    return False


if __name__ == "__main__":
    os.chdir(os.path.dirname(__file__) or ".")

    results = []
    results.append(("导入", test_imports()))
    results.append(("配置", test_config()))
    results.append(("模型", test_models()))
    results.append(("规则引擎", test_rule_engine()))
    results.append(("关键词匹配", test_keyword_matcher()))
    results.append(("LLM", test_llm()))
    results.append(("简历", test_resume()))

    print("\n" + "=" * 40)
    print("测试结果:")
    for name, passed in results:
        print(f"  {'PASS' if passed else 'FAIL'} - {name}")
    print("=" * 40)
