"""数据模型 - 统一的职位和简历结构"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
import json


@dataclass
class JobPosting:
    """统一职位数据模型"""
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_text: str = ""
    requirements: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    experience_years: Optional[float] = None
    is_remote: bool = False
    visa_sponsorship: Optional[bool] = None
    source: str = ""  # indeed / linkedin
    job_id: str = ""
    posted_date: str = ""
    scraped_at: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class CandidateProfile:
    """候选人画像 - 从简历解析"""
    name: str = ""
    email: str = ""
    phone: str = ""
    summary: str = ""
    skills: List[str] = field(default_factory=list)
    experience_years: float = 0.0
    experience: List[Dict[str, str]] = field(default_factory=list)
    education: List[Dict[str, str]] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    projects: List[Dict[str, str]] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MatchResult:
    """匹配结果"""
    job: JobPosting
    total_score: float = 0.0
    keyword_score: float = 0.0
    semantic_score: float = 0.0
    rule_score: float = 0.0
    matched_skills: List[str] = field(default_factory=list)
    missing_skills: List[str] = field(default_factory=list)
    rule_passed: bool = True
    rule_reasons: List[str] = field(default_factory=list)
    recommendation: str = ""  # "apply" / "review" / "skip"
    llm_analysis: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["job"] = self.job.to_dict()
        return d
