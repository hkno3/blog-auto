"""
콘텐츠 리서치 모듈
- 네이버 검색 API (뉴스 + 블로그)로 관련 자료 수집
- 크롤링 가능한 페이지 본문 추출
- AI에게 넘길 리서치 컨텍스트 구성
"""
import re
import requests
from bs4 import BeautifulSoup
from config import get_api_key
from database.db import add_log

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
