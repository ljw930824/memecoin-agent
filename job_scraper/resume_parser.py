"""简历解析器 - 支持 PDF/DOCX → 结构化候选人画像"""
import re
import os
from pathlib import Path
from typing import List
from models import CandidateProfile

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from docx import Document
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False


# 常见技能关键词库 (用于关键词提取)
SKILL_KEYWORDS = {
    # 编程语言
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "rust",
    "r", "sql", "scala", "kotlin", "swift", "matlab", "sas", "julia",
    # 数据科学 & ML
    "machine learning", "deep learning", "nlp", "natural language processing",
    "computer vision", "data science", "data analysis", "data engineering",
    "tensorflow", "pytorch", "keras", "scikit-learn", "sklearn", "xgboost",
    "lightgbm", "pandas", "numpy", "scipy", "matplotlib", "seaborn",
    "plotly", "tableau", "power bi", "looker", "superset",
    "spark", "pyspark", "hadoop", "hive", "kafka", "airflow", "dbt",
    "llm", "large language model", "transformer", "bert", "gpt",
    "hugging face", "langchain", "rag", "vector database", "pinecone",
    "openai", "gemini", "fine-tuning", "prompt engineering",
    # Web开发
    "react", "angular", "vue", "node.js", "django", "flask", "fastapi",
    "spring boot", "express", "next.js", "html", "css",
    # 云 & DevOps
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes",
    "terraform", "jenkins", "github actions", "cicd", "ci/cd",
    "linux", "git", "github", "gitlab",
    # 数据库
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "cassandra", "dynamodb", "snowflake", "bigquery", "redshift",
    "databricks", "delta lake",
    # 其他
    "agile", "scrum", "jira", "confluence",
    "rest api", "graphql", "microservices",
    "a/b testing", "experiment design", "statistics",
    "regression", "classification", "clustering", "recommendation system",
    "time series", "forecasting", "optimization",
}


def extract_text_from_pdf(filepath: str) -> str:
    """从PDF提取文本 (PyMuPDF)"""
    if not HAS_PYMUPDF:
        raise ImportError("需要安装 pymupdf: pip install pymupdf")
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def extract_text_from_docx(filepath: str) -> str:
    """从DOCX提取文本"""
    if not HAS_DOCX:
        raise ImportError("需要安装 python-docx: pip install python-docx")
    doc = Document(filepath)
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text(filepath: str) -> str:
    """自动识别格式并提取文本"""
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    elif ext in (".docx", ".doc"):
        return extract_text_from_docx(filepath)
    elif ext == ".txt":
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def extract_email(text: str) -> str:
    m = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
    return m.group(0) if m else ""


def extract_phone(text: str) -> str:
    m = re.search(r'[\+]?[(]?[0-9]{1,4}[)]?[-\s\./0-9]{7,15}', text)
    return m.group(0) if m else ""


def extract_skills(text: str) -> List[str]:
    """从简历文本中提取技能关键词"""
    text_lower = text.lower()
    found = []
    for skill in SKILL_KEYWORDS:
        # 使用词边界匹配，避免误匹配
        pattern = r'\b' + re.escape(skill.lower()) + r'\b'
        if re.search(pattern, text_lower):
            found.append(skill)
    return sorted(set(found))


def extract_experience_years(text: str) -> float:
    """估算工作年限"""
    patterns = [
        r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience|exp)',
        r'(?:experience|exp)\s*[:：]\s*(\d+)\+?\s*(?:years?|yrs?)',
        r'(\d+)\+?\s*年.*?(?:经验|工作)',
    ]
    years = []
    for p in patterns:
        matches = re.findall(p, text.lower())
        years.extend(int(m) for m in matches)
    return max(years) if years else 0.0


def extract_sections(text: str) -> dict:
    """识别简历的各个部分"""
    section_headers = {
        "experience": r"(?:work\s+)?experience|employment|工作经历|职业经历",
        "education": r"education|教育背景|学历",
        "skills": r"skills?|technologies|technical\s+skills?|技能",
        "projects": r"projects?|项目",
        "certifications": r"certifications?|licenses?|证书",
        "summary": r"summary|objective|profile|about\s+me|个人简介",
    }
    sections = {}
    lines = text.split("\n")
    current_section = "header"
    current_content = []

    for line in lines:
        line_stripped = line.strip().lower()
        matched = False
        for section, pattern in section_headers.items():
            if re.search(pattern, line_stripped, re.IGNORECASE) and len(line_stripped) < 60:
                if current_section and current_content:
                    sections[current_section] = "\n".join(current_content)
                current_section = section
                current_content = []
                matched = True
                break
        if not matched:
            current_content.append(line)

    if current_section and current_content:
        sections[current_section] = "\n".join(current_content)

    return sections


def parse_resume(filepath: str, llm_client=None) -> CandidateProfile:
    """
    解析简历文件，返回结构化候选人画像。

    如果提供 llm_client，则使用LLM增强解析（提取结构化信息）。
    否则使用纯规则解析。
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"简历文件不存在: {filepath}")

    raw_text = extract_text(filepath)
    sections = extract_sections(raw_text)

    profile = CandidateProfile(
        name="",  # 姓名通常在第一行，但规则很难准确提取
        email=extract_email(raw_text),
        phone=extract_phone(raw_text),
        summary=sections.get("summary", "")[:500],
        skills=extract_skills(raw_text),
        experience_years=extract_experience_years(raw_text),
        raw_text=raw_text[:5000],  # 保留前5000字符供LLM分析
    )

    # 如果有LLM客户端，使用LLM增强解析
    if llm_client:
        try:
            enhanced = _enhance_with_llm(raw_text, llm_client)
            if enhanced:
                profile.name = enhanced.get("name", profile.name)
                profile.summary = enhanced.get("summary", profile.summary)
                if enhanced.get("skills"):
                    profile.skills = sorted(set(profile.skills + enhanced["skills"]))
                if enhanced.get("experience_years", 0) > 0:
                    profile.experience_years = enhanced["experience_years"]
                profile.experience = enhanced.get("experience", [])
                profile.education = enhanced.get("education", [])
        except Exception as e:
            print(f"  [WARN] LLM简历解析增强失败: {e}")

    return profile


def _enhance_with_llm(raw_text: str, llm_client) -> dict:
    """使用LLM从简历文本中提取结构化信息"""
    prompt = f"""分析以下简历内容，提取结构化信息。返回JSON格式。

简历内容:
{raw_text[:4000]}

请返回以下JSON格式（不要包含markdown代码块）：
{{
    "name": "候选人姓名",
    "summary": "一句话总结（50字以内）",
    "skills": ["技能1", "技能2", ...],
    "experience_years": 0.0,
    "experience": [
        {{"company": "公司名", "title": "职位", "duration": "时长", "highlights": "主要成就"}}
    ],
    "education": [
        {{"school": "学校", "degree": "学位", "major": "专业", "year": "年份"}}
    ]
}}

只返回JSON，不要其他内容。"""

    response = llm_client.chat(prompt)
    import json
    # 清理可能的markdown代码块
    cleaned = re.sub(r'```(?:json)?\s*', '', response).strip()
    return json.loads(cleaned)


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "resume/resume.pdf"
    if os.path.exists(path):
        profile = parse_resume(path)
        print(f"姓名: {profile.name or '(未识别)'}")
        print(f"邮箱: {profile.email}")
        print(f"电话: {profile.phone}")
        print(f"经验: {profile.experience_years}年")
        print(f"技能 ({len(profile.skills)}): {', '.join(profile.skills[:20])}")
    else:
        print(f"文件不存在: {path}")
        print("请将简历放到 resume/ 目录下")
