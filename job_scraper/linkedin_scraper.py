"""LinkedIn 职位爬虫 - 支持Playwright MCP和静态HTML两种模式"""
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

MCP_PLAYWRIGHT_URL = os.environ.get("MCP_PLAYWRIGHT_URL", "")


class LinkedInScraper:
    """LinkedIn职位爬虫"""

    def __init__(self, config: dict):
        li_config = config.get("linkedin", {})
        self.base_url = li_config.get("base_url", "https://www.linkedin.com")
        self.max_pages = li_config.get("max_pages", 10)
        self.delay_range = li_config.get("request_delay", [5, 12])
        self.filters = config.get("filters", {})
        self.seen_jobs = set()
        self._browser = None
        self._page = None
        self._logged_in = False

        # LinkedIn 登录
        self.email = li_config.get("email", "")
        self.password = li_config.get("password", "")
        self.use_login = li_config.get("use_login", False)

    def search(self, query: str, location: str = "United States",
               max_pages: int = None) -> List[JobPosting]:
        """搜索LinkedIn职位"""
        pages = max_pages or self.max_pages
        all_jobs = []

        print(f"  [LinkedIn] 搜索: '{query}' @ {location}")

        for page in range(pages):
            try:
                start = page * 25
                url = self._build_url(query, location, start)
                html = self._fetch_page(url)

                if not html:
                    print(f"  [LinkedIn] 第{page+1}页获取失败")
                    break

                jobs = self._parse_search_page(html)

                if not jobs:
                    print(f"  [LinkedIn] 第{page+1}页无结果，停止")
                    break

                new_jobs = []
                for job in jobs:
                    job_hash = self._job_hash(job)
                    if job_hash not in self.seen_jobs:
                        self.seen_jobs.add(job_hash)
                        new_jobs.append(job)

                all_jobs.extend(new_jobs)
                print(f"  [LinkedIn] 第{page+1}页: {len(new_jobs)}个新职位 (累计{len(all_jobs)})")

                delay = random.uniform(*self.delay_range)
                time.sleep(delay)

            except Exception as e:
                print(f"  [LinkedIn] 第{page+1}页出错: {e}")
                time.sleep(5)
                continue

        return all_jobs

    def get_job_detail(self, url: str) -> Optional[JobPosting]:
        """获取LinkedIn职位详情"""
        try:
            html = self._fetch_page(url)
            if html:
                return self._parse_job_detail(html, url)
        except Exception as e:
            print(f"  [LinkedIn] 获取详情失败: {e}")
        return None

    def _build_url(self, query: str, location: str, start: int = 0) -> str:
        """构建LinkedIn搜索URL"""
        params = {
            "keywords": query,
            "location": location,
            "start": start,
            "sortBy": "DD",  # 按日期排序
            "f_TPR": f"r{self.filters.get('max_posting_age_days', 14) * 86400}",  # 时间范围(秒)
        }

        # 远程筛选
        allowed = [l.lower() for l in self.filters.get("allowed_locations", [])]
        if "remote" in allowed:
            params["f_WT"] = "2"  # Remote

        # 初级筛选
        exp_level = ""
        exp_max = self.filters.get("experience_max", 15)
        if exp_max <= 2:
            exp_level = "1"  # Internship
        elif exp_max <= 5:
            exp_level = "2"  # Entry level
        if exp_level:
            params["f_E"] = exp_level

        return f"{self.base_url}/jobs/search/?{urlencode(params)}"

    def _fetch_page(self, url: str) -> Optional[str]:
        """获取页面 - 多模式"""
        if HAS_PLAYWRIGHT:
            return self._fetch_via_playwright(url)
        elif HAS_REQUESTS:
            return self._fetch_via_requests(url)
        return None

    def _fetch_via_requests(self, url: str) -> Optional[str]:
        """通过requests获取LinkedIn (公开页面)"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.text
            print(f"  [LinkedIn] HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [LinkedIn] requests失败: {e}")
        return None

    def _fetch_via_playwright(self, url: str) -> Optional[str]:
        """通过Playwright获取"""
        try:
            if not self._browser:
                pw = sync_playwright().start()
                self._browser = pw.chromium.launch(headless=True)
                context = self._browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    viewport={"width": 1920, "height": 1080},
                )
                self._page = context.new_page()

                # 如果配置了登录，先登录
                if self.use_login and self.email and self.password:
                    self._login()

            self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # 处理可能的登录墙
            if "authwall" in self._page.url or "login" in self._page.url:
                print("  [LinkedIn] 遇到登录墙，尝试公开搜索...")
                # 尝试公开搜索URL
                public_url = url.replace("/jobs/search/", "/jobs-guest/jobs/api/jobPosting/")
                self._page.goto(public_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)

            return self._page.content()
        except Exception as e:
            print(f"  [LinkedIn] Playwright失败: {e}")
            return None

    def _login(self):
        """LinkedIn登录"""
        try:
            self._page.goto(f"{self.base_url}/login", wait_until="domcontentloaded")
            time.sleep(2)
            self._page.fill("#username", self.email)
            self._page.fill("#password", self.password)
            self._page.click("button[type='submit']")
            time.sleep(5)
            self._logged_in = True
            print("  [LinkedIn] 登录成功")
        except Exception as e:
            print(f"  [LinkedIn] 登录失败: {e}")

    def _parse_search_page(self, html: str) -> List[JobPosting]:
        """解析搜索结果页"""
        soup = BeautifulSoup(html, "html.parser")
        jobs = []

        # LinkedIn职位卡片
        cards = soup.select("div.base-card, li div.base-search-card, div.job-search-card")

        for card in cards:
            try:
                job = self._parse_job_card(card)
                if job:
                    jobs.append(job)
            except Exception:
                continue

        # 备选: 从JSON-LD或script提取
        if not jobs:
            jobs = self._parse_from_json_ld(soup)

        return jobs

    def _parse_job_card(self, card) -> Optional[JobPosting]:
        """解析单个LinkedIn职位卡片"""
        # 标题
        title_el = card.select_one("h3.base-search-card__title, h3 a, a.base-card__full-link")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)

        # 链接
        link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        href = link_el.get("href", "") if link_el else ""
        if href and not href.startswith("http"):
            href = self.base_url + href

        # 公司
        company_el = card.select_one("h4.base-search-card__subtitle a, h4 a")
        company = company_el.get_text(strip=True) if company_el else ""

        # 地点
        location_el = card.select_one("span.job-search-card__location, span.base-search-card__metadata")
        location = location_el.get_text(strip=True) if location_el else ""

        # 日期
        time_el = card.select_one("time, span.job-search-card__listdate")
        posted_date = ""
        if time_el:
            posted_date = time_el.get("datetime", "") or time_el.get_text(strip=True)

        # 薪资
        salary_el = card.select_one("span.job-search-card__salary-info, div.salary")
        salary_text = salary_el.get_text(strip=True) if salary_el else ""

        job_id = hashlib.md5(href.encode()).hexdigest()[:12] if href else hashlib.md5(title.encode()).hexdigest()[:12]

        salary_min, salary_max = self._parse_salary(salary_text)

        return JobPosting(
            title=title,
            company=company,
            location=location,
            url=href,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_text=salary_text,
            source="linkedin",
            job_id=job_id,
            posted_date=posted_date,
            scraped_at=datetime.now().isoformat(),
            is_remote="remote" in location.lower(),
        )

    def _parse_from_json_ld(self, soup: BeautifulSoup) -> List[JobPosting]:
        """从JSON-LD结构化数据解析"""
        jobs = []
        scripts = soup.select("script[type='application/ld+json']")
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get("@type") == "JobPosting":
                    jobs.append(JobPosting(
                        title=data.get("title", ""),
                        company=data.get("hiringOrganization", {}).get("name", ""),
                        location=data.get("jobLocation", {}).get("address", {}).get("addressLocality", ""),
                        url=data.get("url", ""),
                        description=data.get("description", ""),
                        source="linkedin",
                        job_id=hashlib.md5(data.get("url", "").encode()).hexdigest()[:12],
                        scraped_at=datetime.now().isoformat(),
                    ))
            except:
                continue
        return jobs

    def _parse_job_detail(self, html: str, url: str) -> Optional[JobPosting]:
        """解析LinkedIn职位详情页"""
        soup = BeautifulSoup(html, "html.parser")

        title_el = soup.select_one("h1.top-card-layout__title, h1")
        title = title_el.get_text(strip=True) if title_el else ""

        company_el = soup.select_one("a.topcard__org-name-link, span.topcard__flavor")
        company = company_el.get_text(strip=True) if company_el else ""

        desc_el = soup.select_one("div.description__text, div.show-more-less-html, div.jobs-description")
        description = desc_el.get_text(strip=True) if desc_el else ""

        location_el = soup.select_one("span.topcard__flavor--bullet, span.jobs-unified-top-card__bullet")
        location = location_el.get_text(strip=True) if location_el else ""

        salary_el = soup.select_one("div.salary, span.salary")
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
            source="linkedin",
            job_id=job_id,
            scraped_at=datetime.now().isoformat(),
            is_remote="remote" in (location + description).lower(),
        )

    def _parse_salary(self, text: str) -> tuple:
        """解析薪资文本"""
        if not text:
            return None, None
        text = text.replace(",", "").replace("$", "").lower()

        m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*(?:a\s*year|/year|per\s*year|annually)', text)
        if m:
            return float(m.group(1)), float(m.group(2))

        m = re.search(r'(\d+)\s*(?:a\s*year|/year|per\s*year|annually)', text)
        if m:
            val = float(m.group(1))
            return val, val

        m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*(?:an?\s*hour|/hour)', text)
        if m:
            return float(m.group(1)) * 2080, float(m.group(2)) * 2080

        m = re.search(r'(\d+)\s*(?:an?\s*hour|/hour)', text)
        if m:
            val = float(m.group(1)) * 2080
            return val, val

        return None, None

    def _job_hash(self, job: JobPosting) -> str:
        key = f"{job.title.lower()}_{job.company.lower()}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

    def close(self):
        if self._browser:
            try:
                self._browser.close()
            except:
                pass
