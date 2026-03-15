"""
실시간 이슈 키워드 수집 모듈
- Google Trends RSS (무료)
- 네이버 뉴스 RSS (무료)
- 수동 키워드 폴백
"""
import requests
import xml.etree.ElementTree as ET
from database.db import add_log, is_keyword_used

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Google Trends RSS (여러 URL 시도)
GOOGLE_TRENDS_URLS = [
    "https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR",
    "https://trends.google.co.kr/trends/trendingsearches/daily/rss?geo=KR",
]

# 네이버 뉴스 RSS 섹션별
NAVER_RSS_URLS = [
    "https://feeds.feedburner.com/navernews/ZdXb",  # 연예
    "https://news.naver.com/main/rss/section.naver?sid1=101",  # 경제
    "https://news.naver.com/main/rss/section.naver?sid1=102",  # 사회
    "https://news.naver.com/main/rss/section.naver?sid1=105",  # IT
    "https://news.naver.com/main/rss/section.naver?sid1=103",  # 생활/문화
]

# 폴백 키워드 (API 실패 시)
FALLBACK_KEYWORDS = [
    "다이어트 방법", "건강 식단", "운동 루틴", "피부 관리", "탈모 예방",
    "재테크 방법", "주식 투자 초보", "부업 방법", "유튜브 수익화", "블로그 수익",
    "영어 공부법", "자격증 추천", "이직 준비", "면접 질문", "자소서 작성법",
    "여행 추천", "국내 여행지", "캠핑 장비", "맛집 추천", "홈카페 레시피",
    "육아 꿀팁", "아기 이유식", "임신 초기 증상", "출산 준비물", "어린이집 준비",
]


def fetch_google_trends(count: int = 20) -> list[str]:
    """Google Trends 실시간 인기 검색어 (한국)"""
    for url in GOOGLE_TRENDS_URLS:
        try:
            resp = requests.get(url, timeout=10, headers=HEADERS)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            keywords = []
            for item in root.findall(".//item"):
                title = item.find("title")
                if title is not None and title.text:
                    keywords.append(title.text.strip())
                if len(keywords) >= count:
                    break
            if keywords:
                add_log(f"Google Trends 키워드 {len(keywords)}개 수집 완료")
                return keywords
        except Exception as e:
            add_log(f"Google Trends 수집 실패 ({url}): {e}", "WARN")
            continue
    return []


def fetch_naver_news_keywords(count: int = 20) -> list[str]:
    """네이버 뉴스 RSS에서 키워드 추출"""
    keywords = []
    for url in NAVER_RSS_URLS:
        if len(keywords) >= count:
            break
        try:
            resp = requests.get(url, timeout=10, headers=HEADERS)
            resp.raise_for_status()

            # XML 파싱 (인코딩 문제 대비)
            content = resp.content
            try:
                root = ET.fromstring(content)
            except ET.ParseError:
                content = resp.content.decode("utf-8", errors="ignore").encode("utf-8")
                root = ET.fromstring(content)

            for item in root.findall(".//item"):
                title = item.find("title")
                if title is not None and title.text:
                    kw = title.text.strip()[:50]
                    if kw and kw not in keywords:
                        keywords.append(kw)
                if len(keywords) >= count:
                    break
        except Exception as e:
            add_log(f"네이버 뉴스 RSS 실패 ({url}): {e}", "WARN")
            continue

    if keywords:
        add_log(f"네이버 뉴스 키워드 {len(keywords)}개 수집 완료")
    return keywords


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

    # 수집 실패 시 폴백 키워드 사용
    if not raw:
        add_log("외부 키워드 수집 실패 - 기본 키워드 사용", "WARN")
        raw = FALLBACK_KEYWORDS[:]

    # 중복 키워드(30일 이내 사용한 것) 제거
    fresh = []
    for kw in raw:
        if not is_keyword_used(kw, days=30):
            fresh.append(kw)
        if len(fresh) >= count:
            break

    # 그래도 없으면 폴백에서 강제 반환
    if not fresh:
        fresh = FALLBACK_KEYWORDS[:count]

    add_log(f"신선한 키워드 {len(fresh)}개 선별 완료 (소스: {source})")
    return fresh
