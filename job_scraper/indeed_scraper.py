"""Indeed 职位爬虫 - 支持Playwright MCP和静态HTML两种模式"""
import os
import json
import time
import random
import re
import hashlib
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlencode, quote_plus
from models import JobPosting
from bs4 import BeautifulSoup

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# MCP Playwright 配置
MCP_PLAYWRIGHT_URL = os.environ.get("MCP_PLAYWRIGHT_URL", "")


class IndeedScraper:
    """Indeed职位爬虫 - 多模式支持"""

    def __init__(self, config: dict):
        indeed_config = config.get("indeed", {})
        self.base_url = indeed_config.get("base_url", "https://www.indeed.com")
        self.max_pages = indeed_config.get("max_pages", 20)
        self.delay_range = indeed_config.get("request_delay", [3, 7])
        self.sort_by = indeed_config.get("sort_by", "date")
        self.filters = config.get("filters", {})
        self.seen_jobs = set()  # 去重
        self._browser = None
        self._page = None

    def search(self, query: str, location: str = "United States",
               max_pages: int = None) -> List[JobPosting]:
        """搜索职位"""
        pages = max_pages or self.max_pages
        all_jobs = []

        print(f"  [Indeed] 搜索: '{query}' @ {location}")

        for page in range(pages):
            try:
                start = page * 10
                url = self._build_url(query, location, start)
                html = self._fetch_page(url)

                if not html:
                    print(f"  [Indeed] 第{page+1}页获取失败，停止")
                    break

                jobs = self._parse_search_page(html)

                if not jobs:
                    print(f"  [Indeed] 第{page+1}页无结果，停止")
                    break

                # 去重
                new_jobs = []
                for job in jobs:
                    job_hash = self._job_hash(job)
                    if job_hash not in self.seen_jobs:
                        self.seen_jobs.add(job_hash)
                        new_jobs.append(job)

                all_jobs.extend(new_jobs)
                print(f"  [Indeed] 第{page+1}页: {len(new_jobs)}个新职位 (累计{len(all_jobs)})")

                # 请求间隔
                delay = random.uniform(*self.delay_range)
                time.sleep(delay)

            except Exception as e:
                print(f"  [Indeed] 第{page+1}页出错: {e}")
                time.sleep(5)
                continue

        return all_jobs

    def get_job_detail(self, url: str) -> Optional[JobPosting]:
        """获取职位详情"""
        try:
            html = self._fetch_page(url)
            if html:
                return self._parse_job_detail(html, url)
        except Exception as e:
            print(f"  [Indeed] 获取详情失败: {e}")
        return None

    def _build_url(self, query: str, location: str, start: int = 0) -> str:
        """构建搜索URL"""
        params = {
            "q": query,
            "l": location,
            "start": start,
            "sort": self.sort_by,
            "fromage": self.filters.get("max_posting_age_days", 14),
        }
        # 远程筛选
        if any(loc.lower() == "remote" for loc in self.filters.get("allowed_locations", [])):
            params["remotejob"] = "032b3046-06a3-4876-8dfd-474eb5e7ed11"

        return f"{self.base_url}/jobs?{urlencode(params)}"

    def _fetch_page(self, url: str) -> Optional[str]:
        """获取页面HTML - 多种模式"""
        # 模式1: Playwright MCP (最可靠)
        if MCP_PLAYWRIGHT_URL:
            return self._fetch_via_mcp(url)
        # 模式2: 本地Playwright
        elif HAS_PLAYWRIGHT:
            return self._fetch_via_playwright(url)
        # 模式3: requests (可能被反爬)
        elif HAS_REQUESTS:
            return self._fetch_via_requests(url)
        else:
            print("  [Indeed] 无可用的页面获取方式")
            return None

    def _fetch_via_requests(self, url: str) -> Optional[str]:
        """通过requests获取"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.text
            print(f"  [Indeed] HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [Indeed] requests失败: {e}")
        return None

    def _fetch_via_playwright(self, url: str) -> Optional[str]:
        """通过本地Playwright获取"""
        try:
            if not self._browser:
                pw = sync_playwright().start()
                self._browser = pw.chromium.launch(headless=True)
                self._page = self._browser.new_page()
                self._page.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                })

            self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)  # 等待动态加载
            return self._page.content()
        except Exception as e:
            print(f"  [Indeed] Playwright失败: {e}")
            return None

    def _fetch_via_mcp(self, url: str) -> Optional[str]:
        """通过MCP Playwright获取 - 需要手动调用"""
        # MCP模式下，由pipeline统一管理浏览器
        return self._fetch_via_requests(url)

    def _parse_search_page(self, html: str) -> List[JobPosting]:
        """解析搜索结果页面"""
        soup = BeautifulSoup(html, "html.parser")
        jobs = []

        # Indeed的职位卡片选择器 (会随时间变化)
        cards = soup.select("div.job_seen_beacon, div.jobsearch-ResultsList div.resultContent, td.resultContent")

        for card in cards:
            try:
                job = self._parse_job_card(card)
                if job:
                    jobs.append(job)
            except Exception:
                continue

        # 如果标准选择器没找到，尝试MosaicProvider模式
        if not jobs:
            jobs = self._parse_mosaic_pattern(html)

        return jobs

    def _parse_job_card(self, card) -> Optional[JobPosting]:
        """解析单个职位卡片"""
        # 标题
        title_el = card.select_one("h2.jobTitle a, h2 a, a.jcs-JobTitle")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        url = href if href.startswith("http") else self.base_url + href

        # 公司
        company_el = card.select_one("span[data-testid='company-name'], span.companyName, span.company")
        company = company_el.get_text(strip=True) if company_el else ""

        # 地点
        location_el = card.select_one("div[data-testid='text-location'], div.companyLocation, span.location")
        location = location_el.get_text(strip=True) if location_el else ""

        # 薪资
        salary_el = card.select_one("div.salary-snippet-container, div.metadata.salary-snippet-container, span.estimated-salary, div.salaryOnly")
        salary_text = salary_el.get_text(strip=True) if salary_el else ""

        # 摘要
        summary_el = card.select_one("div.job-snippet, td.resultContent div.summary, ul.jobsearch-ListInlineLayout")
        summary = summary_el.get_text(strip=True) if summary_el else ""

        # 职位ID
        job_id = hashlib.md5(url.encode()).hexdigest()[:12]

        # 日期
        date_el = card.select_one("span.date, span[data-testid='myJobsStateDate']")
        posted_date = date_el.get_text(strip=True) if date_el else ""

        salary_min, salary_max = self._parse_salary(salary_text)

        return JobPosting(
            title=title,
            company=company,
            location=location,
            url=url,
            description=summary,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_text=salary_text,
            source="indeed",
            job_id=job_id,
            posted_date=posted_date,
            scraped_at=datetime.now().isoformat(),
            is_remote="remote" in location.lower(),
        )

    def _parse_mosaic_pattern(self, html: str) -> List[JobPosting]:
        """备选解析: 从script标签提取JSON数据"""
        jobs = []
        # Indeed有时在script标签中嵌入mosaic-data
        pattern = r'"jobkey":\s*"([^"]+)".*?"title":\s*"([^"]+)".*?"company":\s*"([^"]+)"'
        matches = re.findall(pattern, html)
        for jobkey, title, company in matches:
            url = f"{self.base_url}/viewjob?jk={jobkey}"
            jobs.append(JobPosting(
                title=title.replace("\\u0026", "&"),
                company=company.replace("\\u0026", "&"),
                location="",
                url=url,
                source="indeed",
                job_id=jobkey,
                scraped_at=datetime.now().isoformat(),
            ))
        return jobs

    def _parse_job_detail(self, html: str, url: str) -> Optional[JobPosting]:
        """解析职位详情页"""
        soup = BeautifulSoup(html, "html.parser")

        title_el = soup.select_one("h1.jobsearch-JobInfoHeader-title, h1")
        title = title_el.get_text(strip=True) if title_el else ""

        company_el = soup.select_one("div[data-testid='inlineHeader-companyName'], a.jobsearch-InlineCompanyRating-companyName, div.icl-u-lg-mr--sm")
        company = company_el.get_text(strip=True) if company_el else ""

        desc_el = soup.select_one("div#jobDescriptionText, div.jobsearch-jobDescriptionText")
        description = desc_el.get_text(strip=True) if desc_el else ""

        location_el = soup.select_one("div[data-testid='inlineHeader-companyLocation'], div.jobsearch-CompanyInfoWithoutHeaderImage")
        location = location_el.get_text(strip=True) if location_el else ""

        salary_el = soup.select_one("div.jobsearch-JobMetadataHeader-item span, div.salary-snippet-container")
        salary_text = salary_el.get_text(strip=True) if salary_el else ""

        job_id = hashlib.md5(url.encode()).hexdigest()[:12]

        salary_min, salary_max = self._parse_salary(salary_text)

        return JobPosting(
            title=title,
            company=company,
            location=location,
            url=url,
            description=description,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_text=salary_text,
            source="indeed",
            job_id=job_id,
            scraped_at=datetime.now().isoformat(),
            is_remote="remote" in (location + description).lower(),
        )

    def _parse_salary(self, text: str) -> tuple:
        """解析薪资文本"""
        if not text:
            return None, None

        # 清理
        text = text.replace(",", "").replace("$", "").lower()

        # 年薪范围: "80000 - 120000 a year"
        m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*(?:a\s*year|/year|per\s*year|annually)', text)
        if m:
            return float(m.group(1)), float(m.group(2))

        # 年薪单值: "100000 a year"
        m = re.search(r'(\d+)\s*(?:a\s*year|/year|per\s*year|annually)', text)
        if m:
            val = float(m.group(1))
            return val, val

        # 时薪: "$25 - $35 an hour"
        m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*(?:an?\s*hour|/hour|per\s*hour)', text)
        if m:
            return float(m.group(1)) * 2080, float(m.group(2)) * 2080

        # 时薪单值
        m = re.search(r'(\d+)\s*(?:an?\s*hour|/hour|per\s*hour)', text)
        if m:
            val = float(m.group(1)) * 2080
            return val, val

        return None, None

    def _job_hash(self, job: JobPosting) -> str:
        """生成职位hash用于去重"""
        key = f"{job.title.lower()}_{job.company.lower()}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

    def close(self):
        """清理资源"""
        if self._browser:
            try:
                self._browser.close()
            except:
                pass
