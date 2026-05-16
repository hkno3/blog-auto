"""
유명인 키워드 수집 모듈
- Google Trends 실시간 트렌딩에서 인명 추출
- 연예/스포츠 RSS 뉴스에서 인명 추출
- 부정 이슈 필터링 + 정치인 민감 카테고리 차단
- 유명인 + 카테고리 조합 키워드 생성
"""
import re
import email.utils
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from database.db import add_log

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 부정 이슈 키워드 - 포함 시 해당 인물 제외
_NEGATIVE_KEYWORDS = [
    "논란", "사망", "구속", "사기", "징역", "피의자", "고소", "음주운전",
    "마약", "폭행", "성범죄", "비리", "자살", "극단적", "불법", "체포",
    "기소", "수사", "혐의", "고발", "폭로", "스캔들", "이혼소송",
]

# 인명 앞에 오는 직함/역할 키워드 → 섹션 분류에 활용
_ROLE_PATTERN = re.compile(
    r"(?:배우|가수|아이돌|개그맨|개그우먼|방송인|MC|모델|뮤지션|래퍼|"
    r"작곡가|작가|감독|PD|아나운서|기상캐스터|유튜버|인플루언서|크리에이터)\s*([가-힣]{2,4})"
)
_SPORTS_ROLE_PATTERN = re.compile(
    r"(?:선수|감독|코치|축구|야구|농구|배구|골프|수영|육상|테니스|씨름|격투기|복싱|태권도)\s*([가-힣]{2,4})"
)
_POLITICIAN_PATTERN = re.compile(
    r"(?:대통령|국회의원|장관|시장|도지사|구청장|의원|후보|전\s*대통령|전\s*장관)\s*([가-힣]{2,4})"
)
_BIZ_PATTERN = re.compile(
    r"(?:회장|대표|CEO|CTO|창업자|설립자|기업인|대기업|그룹\s*총수)\s*([가-힣]{2,4})"
)
# 제목 앞부분 이름 패턴 (예: "김연아, 건강관리 비법 공개")
_NAME_FIRST_PATTERN = re.compile(r"^([가-힣]{2,4})[,·\s]")

# 한국 성씨 목록 (이름 필터링용)
_KOREAN_SURNAMES = set(
    "김이박최정강조윤장임한오서신권황안송류전홍고문양손배조백허유남심노정하곽성차주우구신임나전민유류진지엄채원천방공강현함변염양변여추노도소신석선설마길주연방위표명기반왕모장탁국여진어은편구용"
)

# 카테고리별 허용 조합
_CELEB_CATEGORIES = {
    "연예인": ["건강 비결", "다이어트 방법", "피부 관리", "운동 루틴", "식단 관리", "체중 감량"],
    "스포츠선수": ["건강 관리", "운동 방법", "다이어트", "부상 회복", "체력 관리", "식단"],
    "유튜버": ["건강", "다이어트", "부업 수익", "투자 방법", "재테크"],
    "기업인": ["사업 성공", "투자 철학", "부동산 투자", "재테크", "창업"],
    "정치인": ["부동산", "재테크", "세금"],  # 사업 관련 제외 (민감)
    "기타": ["건강", "다이어트", "재테크", "투자"],
}

# 연예/스포츠 RSS 피드
_CELEB_RSS = {
    "연예인": [
        "https://rss.donga.com/entertainment.xml",
        "https://www.chosun.com/arc/outboundfeeds/rss/section/entertainments/?outputType=xml",
        "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=08&plink=RSSREADER",
        "https://rss.mt.co.kr/mt_enter.xml",
    ],
    "스포츠선수": [
        "https://rss.donga.com/sports.xml",
        "https://sports.chosun.com/rss/sports.xml",
        "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=07&plink=RSSREADER",
    ],
}

# 일반 뉴스 RSS (정치인/기업인 추출용)
_GENERAL_RSS = [
    "https://rss.donga.com/total.xml",
    "https://www.hankyung.com/feed/all-news",
]


def _is_valid_korean_name(name: str) -> bool:
    """한국 인명 유효성 검사"""
    if not name or len(name) < 2 or len(name) > 4:
        return False
    if not re.match(r"^[가-힣]+$", name):
        return False
    # 첫 글자가 성씨인지 확인
    if name[0] not in _KOREAN_SURNAMES:
        return False
    # 흔한 비인명 단어 제외
    non_names = {"대통령", "국회의", "위원회", "정부가", "경찰이", "검찰이"}
    if name in non_names:
        return False
    return True


def _has_negative_news(title: str) -> bool:
    """제목에 부정 키워드가 있으면 True"""
    return any(kw in title for kw in _NEGATIVE_KEYWORDS)


def _extract_names_from_title(title: str, section: str) -> list[tuple[str, str]]:
    """
    제목에서 (이름, 분류) 튜플 리스트 추출
    section: 연예인 | 스포츠선수 | 정치인 | 기업인 | 기타
    """
    results = []

    # 역할 패턴으로 추출
    for pattern, cat in [
        (_ROLE_PATTERN, "연예인"),
        (_SPORTS_ROLE_PATTERN, "스포츠선수"),
        (_POLITICIAN_PATTERN, "정치인"),
        (_BIZ_PATTERN, "기업인"),
    ]:
        for m in pattern.finditer(title):
            name = m.group(1)
            if _is_valid_korean_name(name):
                results.append((name, cat))

    # 제목 앞부분 이름 패턴 (역할 없이 이름만 있는 경우)
    m = _NAME_FIRST_PATTERN.match(title)
    if m:
        name = m.group(1)
        if _is_valid_korean_name(name) and not any(name == r[0] for r in results):
            results.append((name, section))

    return results


def _fetch_celeb_from_rss(url: str, section: str, days: int = 365) -> list[tuple[str, str]]:
    """RSS에서 유명인 이름 추출 (최근 N일 이내 기사)"""
    try:
        resp = requests.get(url, timeout=8, headers=HEADERS)
        resp.raise_for_status()
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            content = resp.content.decode("utf-8", errors="ignore").encode("utf-8")
            root = ET.fromstring(content)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        names = []

        for item in root.findall(".//item"):
            # 날짜 필터
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

            title_tag = item.find("title")
            if title_tag is None or not title_tag.text:
                continue

            title = title_tag.text.strip()

            # 부정 이슈 필터링
            if _has_negative_news(title):
                continue

            extracted = _extract_names_from_title(title, section)
            names.extend(extracted)

        return names
    except Exception as e:
        add_log(f"RSS 유명인 추출 실패 ({url[:40]}): {e}", "WARN")
        return []


def _get_google_trending_names() -> list[tuple[str, str]]:
    """Google Trends 실시간 트렌딩에서 한국 인명 추출"""
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="ko", tz=540, timeout=(5, 10))
        trending_df = pytrends.trending_searches(pn="south_korea")
        trending_terms = trending_df[0].tolist()[:30]

        names = []
        for term in trending_terms:
            term = str(term).strip()
            # 2-4자 순한글이면 인명 후보
            if re.match(r"^[가-힣]{2,4}$", term) and _is_valid_korean_name(term):
                names.append((term, "기타"))
            # "OOO 선수", "배우 OOO" 형태
            for pattern, cat in [
                (_ROLE_PATTERN, "연예인"),
                (_SPORTS_ROLE_PATTERN, "스포츠선수"),
            ]:
                for m in pattern.finditer(term):
                    name = m.group(1)
                    if _is_valid_korean_name(name):
                        names.append((name, cat))

        return names
    except Exception as e:
        add_log(f"Google Trends 트렌딩 실패: {e}", "WARN")
        return []


def get_celebrity_names(max_count: int = 30) -> list[tuple[str, str]]:
    """
    유명인 이름 수집 메인 함수
    반환: [(이름, 분류), ...] - 분류: 연예인|스포츠선수|정치인|기업인|기타
    """
    seen = set()
    results = []

    def _add(name: str, category: str):
        if name not in seen and _is_valid_korean_name(name):
            seen.add(name)
            results.append((name, category))

    # 1. Google Trends 실시간 트렌딩
    add_log("Google Trends 유명인 수집 시작")
    for name, cat in _get_google_trending_names():
        _add(name, cat)

    # 2. 연예/스포츠 RSS
    for section, urls in _CELEB_RSS.items():
        for url in urls:
            for name, cat in _fetch_celeb_from_rss(url, section, days=365):
                _add(name, cat)
            if len(results) >= max_count:
                break

    # 3. 일반 뉴스 RSS (정치인/기업인)
    for url in _GENERAL_RSS:
        if len(results) >= max_count:
            break
        for name, cat in _fetch_celeb_from_rss(url, "기타", days=365):
            _add(name, cat)

    add_log(f"유명인 수집 완료: {len(results)}명")
    return results[:max_count]


def get_celebrity_keywords(count: int = 20) -> list[str]:
    """
    유명인 + 카테고리 조합 키워드 생성
    반환: ["김연아 건강 비결", "손흥민 운동 방법", ...]
    """
    celebs = get_celebrity_names(max_count=count)
    if not celebs:
        add_log("유명인 수집 결과 없음", "WARN")
        return []

    keywords = []
    seen_keywords = set()

    for name, category in celebs:
        categories = _CELEB_CATEGORIES.get(category, _CELEB_CATEGORIES["기타"])
        for cat in categories:
            kw = f"{name} {cat}"
            if kw not in seen_keywords:
                seen_keywords.add(kw)
                keywords.append(kw)
            if len(keywords) >= count:
                break
        if len(keywords) >= count:
            break

    add_log(f"유명인 키워드 {len(keywords)}개 생성")
    return keywords
