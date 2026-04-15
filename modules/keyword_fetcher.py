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
from database.db import add_log

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

ALL_RSS_FEEDS = [
    # 건강/의학
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
    "https://www.mkhealth.co.kr/rss/allArticle.xml",
    # 종합/시사
    "https://news.sbs.co.kr/news/TopicRssFeed.do?plink=RSSREADER",
    "https://www.yna.co.kr/rss/health.xml",
    "https://rss.donga.com/total.xml",
    # 경제/비즈
    "https://www.mk.co.kr/rss/30000001",
    "https://www.hankyung.com/feed/all-news",
    "http://rss.edaily.co.kr/edaily_news.xml",
    "https://biz.heraldcorp.com/rss/google/economy",
    "https://biz.heraldcorp.com/rss/google/it",
    # IT
    "https://feeds.feedburner.com/zdkorea",
    "https://it.chosun.com/rss/allArticle.xml",
    # 식품/유통
    "https://www.thinkfood.co.kr/rss/allArticle.xml",
    # 구글 뉴스 (한국)
    "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
]

FALLBACK_KEYWORDS = [
    "다이어트 방법", "건강 식단", "운동 루틴", "피부 관리", "탈모 예방",
    "재테크 방법", "주식 투자 초보", "부업 방법", "블로그 수익화",
    "영어 공부법", "자격증 추천", "이직 준비", "여행 추천", "홈카페 레시피",
    "육아 꿀팁", "아기 이유식", "수면 개선", "면역력 높이는 법",
]

# 노이즈 패턴: 포함 시 키워드에서 제외
_NOISE_PATTERNS = re.compile(
    r"위원회|위원장|부위원장|장관|차관|청장|국장|과장|대변인|대표단|"
    r"국방부|외교부|법무부|행안부|기재부|복지부|환경부|교육부|문체부|농림부|"
    r"산업부|중기부|과기부|통일부|여가부|국토부|해수부|고용부|보건부|"
    r"금융위|공정위|방통위|선관위|감사원|헌법재판소|"
    r"고용노동부|국토교통부|농림축산식품부|해양수산부|보건복지부|"
    r"과학기술정보통신부|중소벤처기업부|개인정보보호위원회|"
    r"전체회의|보도참고|보도자료|보도설명|브리핑|접견|위촉|간담회|협약식|업무협약|"
    r"현안점검|점검회의|당정|정무위|국감|국정감사|예결위|"
    r"박람회|엑스포|시상식|공청회|포럼|세미나|학술대회|"
    r"발대식|출범식|개막식|폐막식|착공식|준공식|"
    r"추경|예산안|법안|개정안|시행령|고시|"
    r"quot|nbsp"
)

# 제목 앞부분 제거 패턴: 기관명·날짜·번호 등
_TITLE_PREFIX_STRIP = re.compile(
    r"^(?:\[.+?\]|【.+?】|〔.+?〕|「.+?」|\(.+?\)|\d+\.\s*|\d+위\s*|\d+일\s*|\d+월\s*)+"
)

# 제목 뒷부분 제거 패턴: 동사형 어미·접속어 등
_TITLE_SUFFIX_STRIP = re.compile(
    r"[\s]*(한다|됩니다|밝혀|나서|발표|진행|실시|추진|강화|개최|열려|마련|"
    r"시행|도입|확대|논의|검토|공개|촉구|요청|통해|위해|따라|관련|예정|"
    r"완료|성공|실패|기준|현황|전망|분석|비교|정리|총정리).*$"
)


def _extract_keyword_from_title(title: str) -> str:
    """뉴스 제목에서 핵심 주제어 추출"""
    # 특수문자 정리
    kw = re.sub(r"[^\w\s가-힣]", " ", title)
    kw = re.sub(r"\s+", " ", kw).strip()

    # 앞부분 노이즈 제거 (기관명·날짜 등)
    kw = _TITLE_PREFIX_STRIP.sub("", kw).strip()

    # 뒷부분 동사형 어미 제거
    kw = _TITLE_SUFFIX_STRIP.sub("", kw).strip()

    # 2~4단어만 사용 (앞에서부터)
    words = kw.split()
    if len(words) > 4:
        kw = " ".join(words[:4])
    elif len(words) < 2:
        return ""

    return kw.strip()


def _is_good_keyword(kw: str) -> bool:
    """검색용 키워드로 적합한지 판단"""
    if not kw:
        return False
    if _NOISE_PATTERNS.search(kw):
        return False
    words = kw.split()
    if not (2 <= len(words) <= 4):
        return False
    if not re.search(r"[가-힣]{2,}", kw):
        return False
    return True


def _parse_rss(url: str, max_items: int = 3, hours: int = 24) -> list[str]:
    """RSS에서 핵심 키워드 추출 (24시간 이내 기사만)"""
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
            pub_tag = item.find("pubDate")
            if pub_tag is not None and pub_tag.text:
                try:
                    pub_dt = email.utils.parsedate_to_datetime(pub_tag.text)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                except Exception:
                    pass

            tag = item.find("title")
            if tag is not None and tag.text:
                kw = _extract_keyword_from_title(tag.text)
                if _is_good_keyword(kw):
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
        if not kw:
            return
        word_count = len(kw.split())
        if word_count < 2 or word_count > 5:
            return
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
