"""
실시간 이슈 키워드 수집 모듈
- Google Trends RSS (무료)
- 네이버 뉴스 RSS (무료)
"""
import requests
import xml.etree.ElementTree as ET
from database.db import add_log, is_keyword_used


GOOGLE_TRENDS_RSS = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR"
NAVER_NEWS_RSS = "https://news.naver.com/main/rss/section.naver?sid1=105"  # IT/과학 예시


def fetch_google_trends(count: int = 20) -> list[str]:
    """Google Trends 실시간 인기 검색어 (한국)"""
    try:
        resp = requests.get(GOOGLE_TRENDS_RSS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        keywords = []
        for item in root.findall(".//item"):
            title = item.find("title")
            if title is not None and title.text:
                keywords.append(title.text.strip())
            if len(keywords) >= count:
                break
        add_log(f"Google Trends 키워드 {len(keywords)}개 수집 완료")
        return keywords
    except Exception as e:
        add_log(f"Google Trends 수집 실패: {e}", "ERROR")
        return []


def fetch_naver_news_keywords(count: int = 20) -> list[str]:
    """네이버 뉴스 RSS에서 키워드 추출"""
    try:
        resp = requests.get(NAVER_NEWS_RSS, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        keywords = []
        for item in root.findall(".//item"):
            title = item.find("title")
            if title is not None and title.text:
                # 뉴스 제목에서 핵심 키워드 추출 (첫 15자)
                kw = title.text.strip()[:50]
                keywords.append(kw)
            if len(keywords) >= count:
                break
        add_log(f"네이버 뉴스 키워드 {len(keywords)}개 수집 완료")
        return keywords
    except Exception as e:
        add_log(f"네이버 뉴스 수집 실패: {e}", "ERROR")
        return []


def get_fresh_keywords(count: int = 10, source: str = "google") -> list[str]:
    """
    중복 제거된 신선한 키워드 반환
    source: 'google' | 'naver' | 'both'
    """
    raw = []
    if source in ("google", "both"):
        raw += fetch_google_trends(30)
    if source in ("naver", "both"):
        raw += fetch_naver_news_keywords(30)

    # 중복 키워드(30일 이내 사용한 것) 제거
    fresh = []
    for kw in raw:
        if not is_keyword_used(kw, days=30):
            fresh.append(kw)
        if len(fresh) >= count:
            break

    add_log(f"신선한 키워드 {len(fresh)}개 선별 완료 (소스: {source})")
    return fresh
