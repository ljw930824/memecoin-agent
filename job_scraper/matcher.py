"""
智能匹配引擎
- Layer 1: 硬性筛选规则 (一票否决)
- Layer 2: 关键词匹配 + TF评分
- Layer 3: LLM语义理解
- 综合评分 → 推荐/待审核/跳过
"""
import re
import json
from typing import List, Tuple
from models import JobPosting, CandidateProfile, MatchResult
from llm_client import LLMClient


class RuleEngine:
    """规则引擎 - Layer 1 硬性筛选"""

    def __init__(self, filters: dict):
        self.filters = filters

    def evaluate(self, job: JobPosting) -> Tuple[bool, List[str]]:
        """
        评估职位是否通过硬性筛选。
        返回 (是否通过, 原因列表)
        """
        reasons = []
        passed = True

        # 薪资筛选
        if job.salary_min and job.salary_max:
            sal_min = self.filters.get("salary_min", 0)
            sal_max = self.filters.get("salary_max", 999999)
            if job.salary_max < sal_min:
                reasons.append(f"薪资过低: ${job.salary_max:,.0f} < ${sal_min:,.0f}")
                passed = False
            if job.salary_min > sal_max:
                reasons.append(f"薪资过高: ${job.salary_min:,.0f} > ${sal_max:,.0f}")
                passed = False

        # 地点筛选
        blocked_locs = [l.lower() for l in self.filters.get("blocked_locations", [])]
        if blocked_locs and job.location:
            loc_lower = job.location.lower()
            for blocked in blocked_locs:
                if blocked in loc_lower:
                    reasons.append(f"被屏蔽地区: {job.location}")
                    passed = False
                    break

        # 职位名筛选
        blocked_titles = [t.lower() for t in self.filters.get("blocked_titles", [])]
        if blocked_titles:
            title_lower = job.title.lower()
            for blocked in blocked_titles:
                if blocked in title_lower:
                    reasons.append(f"被屏蔽职位类型: {job.title}")
                    passed = False
                    break

        # 公司筛选
        blocked_companies = [c.lower() for c in self.filters.get("blocked_companies", [])]
        if blocked_companies and job.company:
            if job.company.lower() in blocked_companies:
                reasons.append(f"被屏蔽公司: {job.company}")
                passed = False

        # 经验要求筛选
        if job.experience_years is not None:
            exp_min = self.filters.get("experience_min", 0)
            exp_max = self.filters.get("experience_max", 99)
            if job.experience_years > exp_max:
                reasons.append(f"经验要求过高: {job.experience_years}年 > {exp_max}年")
                passed = False

        # 签证筛选
        if self.filters.get("require_visa_sponsorship") and job.visa_sponsorship is False:
            reasons.append("不提供签证sponsor")
            passed = False

        # 安全许可
        if self.filters.get("reject_security_clearance"):
            desc_lower = job.description.lower()
            clearance_terms = ["security clearance", "top secret", "ts/sci", "dod clearance"]
            for term in clearance_terms:
                if term in desc_lower:
                    reasons.append("需要安全许可")
                    passed = False
                    break

        # 发布时间
        max_age = self.filters.get("max_posting_age_days", 30)
        if job.posted_date and max_age:
            # 简单检查: 如果包含 "30+", "30 days" 等
            age_match = re.search(r'(\d+)\+?\s*(?:day|天)', job.posted_date.lower())
            if age_match and int(age_match.group(1)) > max_age:
                reasons.append(f"发布时间过久: {job.posted_date}")
                passed = False

        return passed, reasons


class KeywordMatcher:
    """关键词匹配 - Layer 2"""

    def __init__(self):
        self.weights = {
            "title": 0.30,
            "skills": 0.40,
            "description": 0.20,
            "experience": 0.10,
        }

    def score(self, job: JobPosting, profile: CandidateProfile) -> Tuple[float, List[str], List[str]]:
        """
        计算关键词匹配分数。
        返回 (分数0-100, 匹配技能, 缺失技能)
        """
        matched = []
        missing = []

        # 1. 技能匹配 (Jaccard + 命中率)
        job_skills = set(s.lower() for s in job.skills)
        candidate_skills = set(s.lower() for s in profile.skills)

        # 从职位描述中提取技能
        desc_skills = self._extract_skills_from_text(job.description)
        job_all_skills = job_skills | desc_skills

        if job_all_skills:
            intersection = job_all_skills & candidate_skills
            matched = list(intersection)
            missing = list(job_all_skills - candidate_skills)
            skill_score = len(intersection) / len(job_all_skills) * 100
        else:
            skill_score = 50  # 没有明确技能要求，给中间分

        # 2. 职位名匹配
        title_score = self._title_match(job.title, profile)

        # 3. 描述关键词匹配
        desc_score = self._desc_keyword_match(job.description, profile)

        # 4. 经验匹配
        exp_score = self._experience_match(job, profile)

        # 加权总分
        total = (
            title_score * self.weights["title"] +
            skill_score * self.weights["skills"] +
            desc_score * self.weights["description"] +
            exp_score * self.weights["experience"]
        )

        return min(total, 100), matched, missing

    def _extract_skills_from_text(self, text: str) -> set:
        """从文本中提取技能关键词"""
        from resume_parser import SKILL_KEYWORDS
        text_lower = text.lower()
        found = set()
        for skill in SKILL_KEYWORDS:
            if re.search(r'\b' + re.escape(skill) + r'\b', text_lower):
                found.add(skill)
        return found

    def _title_match(self, title: str, profile: CandidateProfile) -> float:
        """职位名匹配评分"""
        title_lower = title.lower()
        # 初级职位加分
        junior_terms = ["junior", "entry", "associate", "i", "new grad", "graduate",
                        "trainee", "intern", "analyst", "coordinator"]
        senior_terms = ["senior", "sr", "lead", "principal", "staff", "manager",
                       "director", "head", "vp", "architect"]

        score = 50  # 基础分

        for term in junior_terms:
            if term in title_lower:
                score += 10
                break

        for term in senior_terms:
            if term in title_lower:
                score -= 20
                break

        # 如果候选人经验少于2年，初级职位加分
        if profile.experience_years <= 2:
            for term in junior_terms:
                if term in title_lower:
                    score += 10
                    break

        return max(0, min(100, score))

    def _desc_keyword_match(self, description: str, profile: CandidateProfile) -> float:
        """描述关键词匹配"""
        if not description or not profile.skills:
            return 50

        desc_lower = description.lower()
        matches = sum(1 for s in profile.skills if s.lower() in desc_lower)
        total_skills = len(profile.skills)

        if total_skills == 0:
            return 50
        return min(100, (matches / total_skills) * 100)

    def _experience_match(self, job: JobPosting, profile: CandidateProfile) -> float:
        """经验要求匹配"""
        if job.experience_years is None:
            return 70  # 没写经验要求

        if profile.experience_years >= job.experience_years:
            return 100
        elif profile.experience_years >= job.experience_years - 1:
            return 70
        elif profile.experience_years >= job.experience_years - 2:
            return 40
        else:
            return 10


class SemanticMatcher:
    """LLM语义匹配 - Layer 3"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def score(self, job: JobPosting, profile: CandidateProfile) -> Tuple[float, str]:
        """
        使用LLM评估职位匹配度。
        返回 (分数0-100, 分析文本)
        """
        prompt = f"""你是一位资深HR和职业顾问。请评估以下候选人与职位的匹配度。

## 职位信息
职位: {job.title}
公司: {job.company}
地点: {job.location}
薪资: {job.salary_text or '未提供'}
经验要求: {job.experience_years or '未指定'}年

职位描述:
{job.description[:2000]}

## 候选人信息
经验: {profile.experience_years}年
技能: {', '.join(profile.skills[:30])}
简介: {profile.summary[:300]}

## 评估要求
请从以下维度评估:
1. 技能匹配度 (硬技能是否满足)
2. 经验匹配度 (年限和方向)
3. 职位适合度 (是否对口候选人的职业阶段)
4. 成长潜力 (候选人能否胜任并成长)

返回JSON格式（不要包含markdown代码块）:
{{
    "score": 85,
    "analysis": "一句话分析",
    "strengths": ["优势1", "优势2"],
    "concerns": ["担忧1"],
    "recommendation": "apply"
}}

recommendation 可选值: "apply"(推荐投递), "review"(待审核), "skip"(不推荐)
只返回JSON。"""

        try:
            result = self.llm.chat_json(prompt)
            score = float(result.get("score", 50))
            analysis = result.get("analysis", "")
            return min(100, max(0, score)), analysis
        except Exception as e:
            return 50.0, f"LLM评分失败: {str(e)[:100]}"


class JobMatcher:
    """智能匹配引擎 - 整合三层评分"""

    def __init__(self, config: dict, llm_client: LLMClient = None):
        scoring = config.get("scoring", {})
        self.keyword_weight = scoring.get("keyword_weight", 0.30)
        self.semantic_weight = scoring.get("semantic_weight", 0.40)
        self.rule_weight = scoring.get("rule_weight", 0.30)
        self.auto_threshold = scoring.get("auto_apply_threshold", 80)
        self.review_threshold = scoring.get("review_threshold", 60)

        self.rule_engine = RuleEngine(config.get("filters", {}))
        self.keyword_matcher = KeywordMatcher()
        self.semantic_matcher = SemanticMatcher(llm_client) if llm_client else None

    def match(self, job: JobPosting, profile: CandidateProfile) -> MatchResult:
        """对单个职位进行匹配评分"""
        result = MatchResult(job=job)

        # Layer 1: 规则筛选
        passed, reasons = self.rule_engine.evaluate(job)
        result.rule_passed = passed
        result.rule_reasons = reasons
        result.rule_score = 100 if passed else 0

        if not passed:
            result.total_score = 0
            result.recommendation = "skip"
            return result

        # Layer 2: 关键词匹配
        kw_score, matched, missing = self.keyword_matcher.score(job, profile)
        result.keyword_score = kw_score
        result.matched_skills = matched
        result.missing_skills = missing

        # Layer 3: LLM语义匹配
        if self.semantic_matcher:
            try:
                sem_score, analysis = self.semantic_matcher.score(job, profile)
                result.semantic_score = sem_score
                result.llm_analysis = analysis
            except Exception as e:
                result.semantic_score = kw_score  # 降级: 用关键词分替代
                result.llm_analysis = f"LLM不可用，使用关键词分数: {e}"
                self.semantic_weight = self.keyword_weight  # 权重调整
        else:
            # 无LLM: 关键词占70%，规则占30%
            result.semantic_score = kw_score
            result.llm_analysis = "LLM未配置，仅使用关键词匹配"

        # 综合评分
        result.total_score = (
            result.keyword_score * self.keyword_weight +
            result.semantic_score * self.semantic_weight +
            result.rule_score * self.rule_weight
        )

        # 推荐等级
        if result.total_score >= self.auto_threshold:
            result.recommendation = "apply"
        elif result.total_score >= self.review_threshold:
            result.recommendation = "review"
        else:
            result.recommendation = "skip"

        return result

    def match_batch(self, jobs: List[JobPosting], profile: CandidateProfile,
                    batch_size: int = 5) -> List[MatchResult]:
        """
        批量匹配。对高分候选使用LLM批量分析以节省API调用。
        """
        results = []

        # 先用关键词快速筛选
        for job in jobs:
            passed, reasons = self.rule_engine.evaluate(job)
            kw_score, matched, missing = self.keyword_matcher.score(job, profile)

            result = MatchResult(
                job=job,
                rule_passed=passed,
                rule_reasons=reasons,
                rule_score=100 if passed else 0,
                keyword_score=kw_score,
                matched_skills=matched,
                missing_skills=missing,
            )

            if not passed:
                result.total_score = 0
                result.recommendation = "skip"
            else:
                result.total_score = kw_score * (self.keyword_weight + self.semantic_weight) + \
                                   result.rule_score * self.rule_weight
                results.append(result)

        # 按关键词分数排序，只对top N使用LLM
        results.sort(key=lambda r: r.keyword_score, reverse=True)

        if self.semantic_matcher:
            llm_candidates = [r for r in results[:batch_size * 3] if r.rule_passed]
            for result in llm_candidates:
                try:
                    sem_score, analysis = self.semantic_matcher.score(result.job, profile)
                    result.semantic_score = sem_score
                    result.llm_analysis = analysis
                    result.total_score = (
                        result.keyword_score * self.keyword_weight +
                        result.semantic_score * self.semantic_weight +
                        result.rule_score * self.rule_weight
                    )
                except Exception:
                    result.semantic_score = result.keyword_score

                if result.total_score >= self.auto_threshold:
                    result.recommendation = "apply"
                elif result.total_score >= self.review_threshold:
                    result.recommendation = "review"
                else:
                    result.recommendation = "skip"

        # 剩余的只用关键词分
        for result in results[len(llm_candidates) if self.semantic_matcher else 0:]:
            result.semantic_score = result.keyword_score
            result.total_score = (
                result.keyword_score * (self.keyword_weight + self.semantic_weight) +
                result.rule_score * self.rule_weight
            )
            if result.total_score >= self.auto_threshold:
                result.recommendation = "apply"
            elif result.total_score >= self.review_threshold:
                result.recommendation = "review"
            else:
                result.recommendation = "skip"

        results.sort(key=lambda r: r.total_score, reverse=True)
        return results
