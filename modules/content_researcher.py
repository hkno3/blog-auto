"""
콘텐츠 리서치 모듈
- 네이버 검색 API (뉴스 + 블로그)로 관련 자료 수집
- 크롤링 가능한 페이지 본문 추출
- AI에게 넘길 리서치 컨텍스트 구성
- 유명인 + 카테고리 뉴스 탐색 (발행일 + 검색량 포함)
"""
import re
import email.utils
import requests
from bs4 import BeautifulSoup
from config import get_api_key
from database.db import add_log

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MAX_SCRAPE_CHARS = 1500
MAX_ARTICLES = 5

# 카테고리별 검색 쿼리
CATEGORY_QUERIES = {
    "건강": ["배우 건강", "가수 건강", "선수 건강 관리", "연예인 건강 비결", "스타 건강"],
    "다이어트": ["배우 다이어트", "가수 다이어트", "연예인 식단", "스타 체중", "연예인 몸매 비결"],
    "부동산": ["연예인 부동산", "배우 아파트", "가수 집 매입", "스타 부동산", "연예인 주택"],
    "사업": ["배우 창업", "가수 사업", "연예인 브랜드", "스타 사업 시작", "연예인 회사"],
    "투자": ["연예인 투자", "배우 재테크", "가수 주식", "스타 자산 관리"],
    "패션": ["배우 패션", "가수 스타일", "연예인 패션 비결", "스타 코디"],
    "피부": ["배우 피부 관리", "가수 피부", "연예인 피부 비결", "스타 피부 관리법"],
    "운동": ["배우 운동", "가수 운동 루틴", "선수 트레이닝", "연예인 헬스", "스타 운동법"],
}


def _get_naver_headers() -> dict:
    client_id = get_api_key("naver_client_id")
    client_secret = get_api_key("naver_client_secret")
    if not client_id or not client_secret:
        return {}
    return {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&[a-z#\d]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_MONTHS = {
    "Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
    "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12",
}

def _date_sortkey(date_str: str) -> str:
    """정렬용 YYYYMMDD 문자열 반환"""
    if not date_str:
        return "00000000"
    if re.match(r"^\d{8}$", date_str):
        return date_str
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        return dt.strftime("%Y%m%d%H%M%S")
    except Exception:
        pass
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", date_str)
    if m:
        day, mon, year = m.group(1), m.group(2)[:3].capitalize(), m.group(3)
        return f"{year}{_MONTHS.get(mon,'00')}{day.zfill(2)}"
    return "00000000"
    """다양한 날짜 형식 → YYYY.MM.DD"""
    if not date_str:
        return ""
    # 블로그: "20260516"
    if re.match(r"^\d{8}$", date_str):
        return f"{date_str[:4]}.{date_str[4:6]}.{date_str[6:]}"
    # RFC 2822: "Wed, 29 Apr 2026 10:30:00 +0900"
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        return dt.strftime("%Y.%m.%d")
    except Exception:
        pass
    # 정규식 fallback: "29 Apr 2026" 패턴
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", date_str)
    if m:
        day, mon, year = m.group(1), m.group(2)[:3].capitalize(), m.group(3)
        return f"{year}.{_MONTHS.get(mon, '00')}.{day.zfill(2)}"
    return ""


def search_naver_news(keyword: str, display: int = MAX_ARTICLES) -> list[dict]:
    """네이버 뉴스 검색 API"""
    headers = _get_naver_headers()
    if not headers:
        add_log("네이버 API 키 없음 - 뉴스 검색 스킵", "WARN")
        return []
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=headers,
            params={"query": keyword, "display": display, "sort": "date"},
            timeout=8,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [
            {
                "title": _strip_html(item.get("title", "")),
                "description": _strip_html(item.get("description", "")),
                "link": item.get("originallink") or item.get("link", ""),
                "pubDate": _parse_date(item.get("pubDate", "")),
            }
            for item in items
        ]
    except Exception as e:
        add_log(f"네이버 뉴스 검색 실패 ({keyword}): {e}", "WARN")
        return []


def search_naver_blog(keyword: str, display: int = MAX_ARTICLES) -> list[dict]:
    """네이버 블로그 검색 API"""
    headers = _get_naver_headers()
    if not headers:
        return []
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/blog.json",
            headers=headers,
            params={"query": keyword, "display": display, "sort": "date"},
            timeout=8,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [
            {
                "title": _strip_html(item.get("title", "")),
                "description": _strip_html(item.get("description", "")),
                "link": item.get("link", ""),
                "pubDate": _parse_date(item.get("postdate", "")),
            }
            for item in items
        ]
    except Exception as e:
        add_log(f"네이버 블로그 검색 실패 ({keyword}): {e}", "WARN")
        return []


def search_celebrity_category(category: str, max_total: int = 150) -> list[dict]:
    """
    유명인 + 카테고리 뉴스/블로그 검색 (최대 max_total개, 최신순)
    반환: [{type, title, link, pubDate, query}]
    """
    queries = CATEGORY_QUERIES.get(category, [f"연예인 {category}"])
    display_per_query = min(100, max(20, max_total // len(queries) + 10))
    seen_titles = set()
    results = []

    for query in queries:
        for item in search_naver_news(query, display=display_per_query):
            t = item["title"]
            if t and t not in seen_titles:
                seen_titles.add(t)
                results.append({**item, "type": "뉴스", "query": query})
        for item in search_naver_blog(query, display=display_per_query // 2):
            t = item["title"]
            if t and t not in seen_titles:
                seen_titles.add(t)
                results.append({**item, "type": "블로그", "query": query})

    results.sort(key=lambda x: _date_sortkey(x.get("pubDate", "")), reverse=True)
    results = results[:max_total]
    add_log(f"카테고리 [{category}] 검색: {len(results)}건")
    return results


def get_search_volumes(keywords: list[str]) -> dict[str, int]:
    """
    네이버 검색광고 API로 키워드 월간 검색량 조회
    반환: {keyword: total_search_volume}
    """
    if not keywords:
        return {}
    try:
        from modules.keyword_analyzer import get_naver_search_volume
        volume_data = get_naver_search_volume(keywords)
        return {kw: v.get("total", 0) for kw, v in volume_data.items()}
    except Exception as e:
        add_log(f"검색량 조회 실패: {e}", "WARN")
        return {}


def scrape_article(url: str) -> str:
    if not url or "naver.com/blog" in url:
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()
        body = (
            soup.find("article")
            or soup.find("main")
            or soup.find(id=re.compile(r"content|article|body", re.I))
            or soup.find(class_=re.compile(r"content|article|body|text", re.I))
            or soup.body
        )
        if not body:
            return ""
        text = body.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 20]
        return "\n".join(lines)[:MAX_SCRAPE_CHARS]
    except Exception:
        return ""


def get_research_context(keyword: str) -> str:
    add_log(f"콘텐츠 리서치 시작: {keyword}")
    news_items = search_naver_news(keyword, display=5)
    blog_items = search_naver_blog(keyword, display=3)

    if not news_items and not blog_items:
        add_log(f"리서치 결과 없음: {keyword}", "WARN")
        return ""

    sections = []
    if news_items:
        news_lines = ["[최신 뉴스 요약]"]
        for item in news_items:
            title = item["title"]
            desc = item["description"]
            if title:
                news_lines.append(f"- {title}" + (f": {desc}" if desc else ""))
        sections.append("\n".join(news_lines))

    if blog_items:
        blog_lines = ["[블로그 참고 내용]"]
        for item in blog_items:
            title = item["title"]
            desc = item["description"]
            if title:
                blog_lines.append(f"- {title}" + (f": {desc}" if desc else ""))
        sections.append("\n".join(blog_lines))

    for item in news_items[:2]:
        content = scrape_article(item.get("link", ""))
        if content:
            sections.append(f"[기사 본문 발췌 - {item['title'][:30]}]\n{content}")

    context = "\n\n".join(sections)
    add_log(f"리서치 완료: {len(context)}자 수집")
    return context


HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MAX_SCRAPE_CHARS = 1500  # 한 기사당 최대 글자 수
MAX_ARTICLES = 5         # 검색 결과 최대 수집 수


def _get_naver_headers() -> dict:
    client_id = get_api_key("naver_client_id")
    client_secret = get_api_key("naver_client_secret")
    if not client_id or not client_secret:
        return {}
    return {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }


def _strip_html(text: str) -> str:
    """HTML 태그 및 특수문자 제거"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def search_naver_news(keyword: str, display: int = MAX_ARTICLES) -> list[dict]:
    """네이버 뉴스 검색 API"""
    headers = _get_naver_headers()
    if not headers:
        add_log("네이버 API 키 없음 - 뉴스 검색 스킵", "WARN")
        return []
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=headers,
            params={"query": keyword, "display": display, "sort": "date"},
            timeout=8,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [
            {
                "title": _strip_html(item.get("title", "")),
                "description": _strip_html(item.get("description", "")),
                "link": item.get("originallink") or item.get("link", ""),
                "pubDate": item.get("pubDate", ""),
            }
            for item in items
        ]
    except Exception as e:
        add_log(f"네이버 뉴스 검색 실패 ({keyword}): {e}", "WARN")
        return []


def search_naver_blog(keyword: str, display: int = MAX_ARTICLES) -> list[dict]:
    """네이버 블로그 검색 API"""
    headers = _get_naver_headers()
    if not headers:
        return []
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/blog.json",
            headers=headers,
            params={"query": keyword, "display": display, "sort": "sim"},
            timeout=8,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [
            {
                "title": _strip_html(item.get("title", "")),
                "description": _strip_html(item.get("description", "")),
                "link": item.get("link", ""),
            }
            for item in items
        ]
    except Exception as e:
        add_log(f"네이버 블로그 검색 실패 ({keyword}): {e}", "WARN")
        return []


def scrape_article(url: str) -> str:
    """URL에서 본문 텍스트 추출 (실패 시 빈 문자열)"""
    if not url or "naver.com/blog" in url:
        # 네이버 블로그는 크롤링 차단이 많아 스킵
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "lxml")

        # 불필요한 태그 제거
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()

        # 본문 영역 추출 (article, main, #content 등 우선)
        body = (
            soup.find("article")
            or soup.find("main")
            or soup.find(id=re.compile(r"content|article|body", re.I))
            or soup.find(class_=re.compile(r"content|article|body|text", re.I))
            or soup.body
        )
        if not body:
            return ""

        text = body.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 20]
        return "\n".join(lines)[:MAX_SCRAPE_CHARS]
    except Exception:
        return ""


def get_research_context(keyword: str) -> str:
    """
    키워드에 대한 리서치 컨텍스트 생성
    네이버 뉴스 + 블로그 검색 + 일부 본문 크롤링
    반환: AI 프롬프트에 삽입할 텍스트
    """
    add_log(f"콘텐츠 리서치 시작: {keyword}")

    news_items = search_naver_news(keyword, display=5)
    blog_items = search_naver_blog(keyword, display=3)

    if not news_items and not blog_items:
        add_log(f"리서치 결과 없음: {keyword}", "WARN")
        return ""

    sections = []

    # 뉴스 요약
    if news_items:
        news_lines = ["[최신 뉴스 요약]"]
        for item in news_items:
            title = item["title"]
            desc = item["description"]
            if title:
                news_lines.append(f"- {title}" + (f": {desc}" if desc else ""))
        sections.append("\n".join(news_lines))

    # 블로그 요약
    if blog_items:
        blog_lines = ["[블로그 참고 내용]"]
        for item in blog_items:
            title = item["title"]
            desc = item["description"]
            if title:
                blog_lines.append(f"- {title}" + (f": {desc}" if desc else ""))
        sections.append("\n".join(blog_lines))

    # 뉴스 기사 본문 크롤링 (최대 2개)
    scraped = []
    for item in news_items[:2]:
        url = item.get("link", "")
        content = scrape_article(url)
        if content:
            scraped.append(f"[기사 본문 발췌 - {item['title'][:30]}]\n{content}")

    if scraped:
        sections.extend(scraped)

    context = "\n\n".join(sections)
    add_log(f"리서치 완료: {len(context)}자 수집")
    return context
