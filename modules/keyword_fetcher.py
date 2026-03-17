"""
키워드 수집 모듈
- 전체 RSS 피드에서 최신 키워드 추출
- 네이버 자동완성으로 서브 키워드 확장
"""
import re
import requests
import xml.etree.ElementTree as ET
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


def _parse_rss(url: str, max_items: int = 3) -> list[str]:
    """RSS에서 제목 추출"""
    try:
        resp = requests.get(url, timeout=8, headers=HEADERS)
        resp.raise_for_status()
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            content = resp.content.decode("utf-8", errors="ignore").encode("utf-8")
            root = ET.fromstring(content)

        titles = []
        for item in root.findall(".//item"):
            tag = item.find("title")
            if tag is not None and tag.text:
                # 특수문자 제거, 핵심 키워드만 추출
                kw = re.sub(r"[^\w\s가-힣]", " ", tag.text).strip()
                kw = re.sub(r"\s+", " ", kw).strip()
                # 너무 길면 앞 20자만
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
    """네이버 자동완성 서브 키워드"""
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


def fetch_all_rss_keywords(max_total: int = 30) -> list[str]:
    """전체 RSS에서 키워드 수집"""
    keywords = []
    for url in ALL_RSS_FEEDS:
        if len(keywords) >= max_total:
            break
        titles = _parse_rss(url, max_items=2)
        for kw in titles:
            if kw not in keywords:
                keywords.append(kw)
    add_log(f"RSS 키워드 {len(keywords)}개 수집")
    return keywords


def get_fresh_keywords(count: int = 20, source: str = "both") -> list[str]:
    """
    RSS + 네이버 자동완성 서브 키워드 조합
    반환: [키워드, 서브키워드1, 서브키워드2, ...]
    """
    # RSS에서 기본 키워드 수집
    rss_keywords = fetch_all_rss_keywords(max_total=15)

    if not rss_keywords:
        add_log("RSS 수집 실패 - 기본 키워드 사용", "WARN")
        rss_keywords = FALLBACK_KEYWORDS[:10]

    # 각 키워드 + 자동완성 서브 키워드 조합
    combined = []
    for kw in rss_keywords:
        # 원본 키워드
        if kw not in combined and not is_keyword_used(kw, days=30):
            combined.append(kw)

        # 서브 키워드 (자동완성)
        sub_keywords = _get_naver_autocomplete(kw, max_count=2)
        for sub in sub_keywords:
            if sub not in combined and not is_keyword_used(sub, days=30):
                combined.append(sub)

        if len(combined) >= count:
            break

    # 부족하면 폴백
    if not combined:
        combined = FALLBACK_KEYWORDS[:count]

    add_log(f"최종 키워드 {len(combined)}개 (RSS + 서브키워드)")
    return combined[:count]
