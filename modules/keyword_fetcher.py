"""
키워드 수집 모듈
- 전체 RSS 피드에서 24시간 이내 최신 키워드 추출
- 네이버 자동완성어 + 연관검색어 확장
- 구글 자동완성어 확장
"""
import re
import email.utils
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from database.db import add_log, is_keyword_used

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

ALL_RSS_FEEDS = [
    "https://www.korea.kr/rss/policy.xml",
    "https://www.korea.kr/rss/reporter.xml",
    "https://www.korea.kr/rss/column.xml",
    "https://www.korea.kr/rss/insight.xml",
    "https://www.korea.kr/rss/media.xml",
    "https://www.korea.kr/rss/shorts.xml",
    "https://www.korea.kr/rss/visual.xml",
    "https://www.korea.kr/rss/photo.xml",
    "https://www.korea.kr/rss/cartoon.xml",
    "https://www.korea.kr/rss/pressrelease.xml",
    "https://www.korea.kr/rss/fact.xml",
    "https://www.korea.kr/rss/ebriefing.xml",
    "https://www.korea.kr/rss/president.xml",
    "https://www.korea.kr/rss/cabinet.xml",
    "https://www.korea.kr/rss/speech.xml",
    "https://www.korea.kr/rss/expdoc.xml",
    "https://www.korea.kr/rss/archive.xml",
    "https://health.chosun.com/rss/healthcaren.xml",
    "https://health.chosun.com/rss/column.xml",
    "https://health.chosun.com/site/data/rss/rss.xml",
    "https://www.foodnews.co.kr/rss/S1N1.xml",
    "https://www.psychiatricnews.net/rss/allArticle.xml",
    "https://kormedi.com/category/healthnews/feed/",
    "https://kormedi.com/category/healthnews/diet/feed/",
    "https://kormedi.com/category/healthnews/food/feed/",
    "https://kormedi.com/category/healthnews/exercise/feed/",
    "https://kormedi.com/category/life/feed/",
    "https://kormedi.com/category/bionews/feed/",
    "https://kormedi.com/category/medical/feed/",
    "https://kormedi.com/category/opinion/feed/",
    "https://kormedi.com/category/cardnews/feed/",
    "https://kormedi.com/category/movie/feed/",
    "https://www.mkhealth.co.kr/rss/allArticle.xml",
    # 종합/시사
    "https://news.sbs.co.kr/news/TopicRssFeed.do?plink=RSSREADER",
    "https://www.yna.co.kr/rss/news.xml",
    "https://www.yna.co.kr/rss/health.xml",
    "https://www.yna.co.kr/rss/economy.xml",
    "https://rss.donga.com/total.xml",
    "https://www.hani.co.kr/rss",
    "https://www.khan.co.kr/rss/rssdata/total_news.xml",
    # 경제/비즈
    "https://www.mk.co.kr/rss/30000001",
    "https://www.hankyung.com/feed/all-news",
    "http://rss.edaily.co.kr/edaily_news.xml",
    "https://biz.heraldcorp.com/rss/google/newsAll",
    "https://biz.heraldcorp.com/rss/google/economy",
    "https://biz.heraldcorp.com/rss/google/realestate",
    "https://biz.heraldcorp.com/rss/google/it",
    "https://biz.heraldcorp.com/rss/google/culture",
    # IT
    "https://feeds.feedburner.com/zdkorea",
    "https://it.chosun.com/rss/allArticle.xml",
    # 식품/유통
    "https://www.thinkfood.co.kr/rss/allArticle.xml",
    # 보도자료
    "https://api.newswire.co.kr/rss/all",
    "https://api.newswire.co.kr/rss/industry/1000",
    "https://api.newswire.co.kr/rss/industry/900",
    "https://api.newswire.co.kr/rss/industry/100",
    "https://api.newswire.co.kr/rss/industry/200",
    "https://api.newswire.co.kr/rss/industry/1100",
    # 구글 뉴스
    "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
]

FALLBACK_KEYWORDS = [
    "다이어트 방법", "건강 식단", "운동 루틴", "피부 관리", "탈모 예방",
    "재테크 방법", "주식 투자 초보", "부업 방법", "블로그 수익화",
    "영어 공부법", "자격증 추천", "이직 준비", "여행 추천", "홈카페 레시피",
    "육아 꿀팁", "아기 이유식", "수면 개선", "면역력 높이는 법",
]


def _parse_rss(url: str, max_items: int = 3, hours: int = 24) -> list[str]:
    """RSS에서 제목 추출 (24시간 이내 기사만)"""
    try:
        resp = requests.get(url, timeout=8, headers=HEADERS)
        resp.raise_for_status()
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            content = resp.content.decode("utf-8", errors="ignore").encode("utf-8")
            root = ET.fromstring(content)

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        titles = []
        for item in root.findall(".//item"):
            # pubDate 체크 — 24시간 이전 기사 스킵
            pub_tag = item.find("pubDate")
            if pub_tag is not None and pub_tag.text:
                try:
                    pub_dt = email.utils.parsedate_to_datetime(pub_tag.text)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                except Exception:
                    pass  # 날짜 파싱 실패 시 포함

            tag = item.find("title")
            if tag is not None and tag.text:
                kw = re.sub(r"[^\w\s가-힣]", " ", tag.text).strip()
                kw = re.sub(r"\s+", " ", kw).strip()
                if len(kw) > 20:
                    kw = kw[:20].rsplit(" ", 1)[0]
                if kw and len(kw) >= 4:
                    titles.append(kw)
            if len(titles) >= max_items:
                break
        return titles
    except Exception:
        return []


def _get_naver_autocomplete(keyword: str, max_count: int = 3) -> list[str]:
    """네이버 자동완성어 (검색창 입력 시 드롭다운 추천어)"""
    try:
        resp = requests.get(
            "https://ac.search.naver.com/nx/ac",
            params={"q": keyword, "st": "100", "r_format": "json",
                    "r_enc": "UTF-8", "q_enc": "UTF-8"},
            timeout=5, headers=HEADERS,
        )
        data = resp.json()
        items = data.get("items", [[]])[0]
        return [item[0] for item in items[:max_count] if item]
    except Exception:
        return []


def _get_naver_related(keyword: str, max_count: int = 3) -> list[str]:
    """네이버 연관검색어 (검색 결과 페이지 확장 키워드)"""
    try:
        resp = requests.get(
            "https://ac.search.naver.com/nx/ac",
            params={"q": keyword, "st": "111", "r_format": "json",
                    "r_enc": "UTF-8", "q_enc": "UTF-8"},
            timeout=5, headers=HEADERS,
        )
        data = resp.json()
        items = data.get("items", [])
        # items[0]: 자동완성, items[1]: 연관검색어
        related = items[1] if len(items) > 1 else []
        return [item[0] for item in related[:max_count] if item]
    except Exception:
        return []


def _get_google_autocomplete(keyword: str, max_count: int = 3) -> list[str]:
    """구글 자동완성어 (How-to/질문형 키워드 포함)"""
    try:
        resp = requests.get(
            "https://suggestqueries.google.com/complete/search",
            params={"output": "firefox", "hl": "ko", "q": keyword},
            timeout=5, headers=HEADERS,
        )
        data = resp.json()
        suggestions = data[1] if len(data) > 1 else []
        return [s for s in suggestions[:max_count] if s and s != keyword]
    except Exception:
        return []


def fetch_all_rss_keywords(max_total: int = 30) -> list[str]:
    """전체 RSS에서 키워드 수집"""
    keywords = []
    for url in ALL_RSS_FEEDS:
        if len(keywords) >= max_total:
            break
        titles = _parse_rss(url, max_items=3)
        for kw in titles:
            if kw not in keywords:
                keywords.append(kw)
    add_log(f"RSS 키워드 {len(keywords)}개 수집")
    return keywords


def get_fresh_keywords(count: int = 20, source: str = "both") -> list[str]:
    """
    RSS(24h) + 네이버 자동완성어 + 네이버 연관검색어 + 구글 자동완성어 조합
    반환: [키워드, ...]
    """
    rss_keywords = fetch_all_rss_keywords(max_total=50)

    if not rss_keywords:
        add_log("RSS 24h 이내 키워드 없음 - 기본 키워드 사용", "WARN")
        rss_keywords = FALLBACK_KEYWORDS[:10]

    combined = []

    def _add(kw):
        if kw and kw not in combined and not is_keyword_used(kw, days=30):
            combined.append(kw)

    for kw in rss_keywords:
        _add(kw)

        # 1-2-1. 네이버 자동완성어
        for sub in _get_naver_autocomplete(kw, max_count=2):
            _add(sub)

        # 1-2-2. 네이버 연관검색어
        for sub in _get_naver_related(kw, max_count=2):
            _add(sub)

        # 1-3-1. 구글 자동완성어 (질문형/How-to 포함)
        for sub in _get_google_autocomplete(kw, max_count=1):
            _add(sub)

        if len(combined) >= count:
            break

    if not combined:
        combined = FALLBACK_KEYWORDS[:count]

    add_log(f"최종 키워드 {len(combined)}개 (RSS 24h + 네이버 자동완성/연관 + 구글 자동완성)")
    return combined[:count]
