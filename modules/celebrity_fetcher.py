"""
유명인 키워드 수집 모듈
- 네이버 검색 API로 연예/스포츠/경제 뉴스에서 인명 추출 (주력)
- Google Trends 실시간 트렌딩 보조
- 부정 이슈 필터링 + 정치인 민감 카테고리 차단
- 유명인 + 카테고리 조합 키워드 생성
"""
import re
import requests
from config import get_api_key
from database.db import add_log

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 부정 이슈 키워드 - 제목에 포함 시 해당 인물 제외
_NEGATIVE_KEYWORDS = [
    "논란", "사망", "구속", "사기", "징역", "피의자", "고소", "음주운전",
    "마약", "폭행", "성범죄", "비리", "자살", "극단적", "불법", "체포",
    "기소", "수사", "혐의", "고발", "폭로", "스캔들", "이혼소송",
]

# 인명 앞/뒤에 오는 역할 키워드
_ROLE_BEFORE = re.compile(
    r"(?:배우|가수|아이돌|그룹|개그맨|개그우먼|방송인|MC|모델|뮤지션|래퍼|"
    r"작가|감독|PD|아나운서|유튜버|인플루언서|크리에이터|셰프|요리사)\s+([가-힣]{2,4})"
)
_ROLE_AFTER = re.compile(
    r"([가-힣]{2,4})\s+(?:배우|가수|씨|선수|감독|코치|대표|회장|의원|기자)"
)
_SPORTS_BEFORE = re.compile(
    r"(?:선수|감독|코치|투수|포수|타자|공격수|수비수|골키퍼)\s+([가-힣]{2,4})"
)
_SPORTS_AFTER = re.compile(
    r"([가-힣]{2,4})\s+선수"
)
_POLITICIAN_BEFORE = re.compile(
    r"(?:대통령|국회의원|장관|시장|도지사|의원|후보)\s+([가-힣]{2,4})"
)
_BIZ_BEFORE = re.compile(
    r"(?:회장|대표|CEO|창업자|설립자)\s+([가-힣]{2,4})"
)
# "김연아, ~" / "손흥민이 ~" / "BTS 뷔가 ~" 같은 제목 첫머리 패턴
_NAME_LEAD = re.compile(r"^([가-힣]{2,4})[,\s이가은는을를의도]")

# 한국 성씨
_KOREAN_SURNAMES = set(
    "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구나민진지엄채원천방공현함변염추도석선설마길연표명기반왕탁국어은편용"
)

# 인명이 아닌 단어 블랙리스트 (직업명, 일반명사 등)
_NON_PERSON_WORDS = {
    "고등학생", "중학생", "초등학생", "대학생", "직장인", "주부", "어르신",
    "시민들", "국민들", "전문가", "관계자", "담당자", "소비자", "투자자",
    "근로자", "아르바이트", "자영업자", "프리랜서", "취준생", "수험생",
    "서울시", "경기도", "부산시", "인천시", "대구시", "광주시", "대전시",
    "한국인", "외국인", "미국인", "일본인", "중국인",
    "남성분", "여성분", "남자분", "여자분", "어린이", "청소년",
    "오마이걸", "뉴진스", "에스파", "아이브", "르세라핌",  # 그룹명
}

# 뉴스 검색 쿼리 → 섹션 분류
_SEARCH_QUERIES = [
    ("배우 근황", "연예인"),
    ("가수 컴백", "연예인"),
    ("아이돌 활동", "연예인"),
    ("개그맨 방송", "연예인"),
    ("유튜버 근황", "유튜버"),
    ("축구 선수", "스포츠선수"),
    ("야구 선수", "스포츠선수"),
    ("골프 선수", "스포츠선수"),
    ("회장 사업", "기업인"),
    ("대표 창업", "기업인"),
]

# 카테고리별 허용 조합
_CELEB_CATEGORIES = {
    "연예인": ["건강 비결", "다이어트 방법", "피부 관리", "운동 루틴", "식단 관리", "체중 감량"],
    "스포츠선수": ["건강 관리", "운동 방법", "다이어트", "부상 회복", "체력 관리", "식단"],
    "유튜버": ["건강", "다이어트", "부업 수익", "투자 방법", "재테크"],
    "기업인": ["사업 성공", "투자 철학", "부동산 투자", "재테크", "창업"],
    "정치인": ["부동산", "재테크", "세금"],
    "기타": ["건강", "다이어트", "재테크", "투자"],
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
    return re.sub(r"\s+", " ", text).strip()


def _is_valid_korean_name(name: str) -> bool:
    if not name or len(name) < 2 or len(name) > 4:
        return False
    if not re.match(r"^[가-힣]+$", name):
        return False
    if name[0] not in _KOREAN_SURNAMES:
        return False
    if name in _NON_PERSON_WORDS:
        return False
    return True


def _has_negative_news(title: str) -> bool:
    return any(kw in title for kw in _NEGATIVE_KEYWORDS)


def _extract_names_from_text(text: str, default_category: str) -> list[tuple[str, str]]:
    """텍스트에서 (이름, 분류) 튜플 추출"""
    results = []
    seen = set()

    def _add(name, cat):
        if name not in seen and _is_valid_korean_name(name):
            seen.add(name)
            results.append((name, cat))

    for pattern, cat in [
        (_ROLE_BEFORE, "연예인"),
        (_ROLE_AFTER, "연예인"),
        (_SPORTS_BEFORE, "스포츠선수"),
        (_SPORTS_AFTER, "스포츠선수"),
        (_POLITICIAN_BEFORE, "정치인"),
        (_BIZ_BEFORE, "기업인"),
    ]:
        for m in pattern.finditer(text):
            _add(m.group(1), cat)

    # 제목 첫머리 이름
    m = _NAME_LEAD.match(text)
    if m:
        _add(m.group(1), default_category)

    return results


def _search_naver_news(query: str, display: int = 20) -> list[str]:
    """네이버 뉴스 검색 → 제목 리스트 반환"""
    headers = _get_naver_headers()
    if not headers:
        return []
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=headers,
            params={"query": query, "display": display, "sort": "date"},
            timeout=8,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [_strip_html(item.get("title", "")) for item in items if item.get("title")]
    except Exception as e:
        add_log(f"네이버 뉴스 검색 실패 ({query}): {e}", "WARN")
        return []


def _get_google_trending_names() -> list[tuple[str, str]]:
    """Google Trends 실시간 트렌딩에서 한국 인명 추출 (보조)"""
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="ko", tz=540, timeout=(5, 10))
        trending_df = pytrends.trending_searches(pn="south_korea")
        trending_terms = trending_df[0].tolist()[:30]

        names = []
        for term in trending_terms:
            term = str(term).strip()
            if re.match(r"^[가-힣]{2,4}$", term) and _is_valid_korean_name(term):
                names.append((term, "기타"))
            for m in _ROLE_BEFORE.finditer(term):
                if _is_valid_korean_name(m.group(1)):
                    names.append((m.group(1), "연예인"))
            for m in _SPORTS_AFTER.finditer(term):
                if _is_valid_korean_name(m.group(1)):
                    names.append((m.group(1), "스포츠선수"))
        return names
    except Exception as e:
        add_log(f"Google Trends 실패 (무시): {e}", "WARN")
        return []


def get_celebrity_names(max_count: int = 40) -> list[tuple[str, str]]:
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

    has_naver = bool(_get_naver_headers())

    # 1. 네이버 검색 API (주력)
    if has_naver:
        add_log("네이버 뉴스 검색으로 유명인 수집 시작")
        for query, default_cat in _SEARCH_QUERIES:
            titles = _search_naver_news(query, display=50)
            for title in titles:
                if _has_negative_news(title):
                    continue
                for name, cat in _extract_names_from_text(title, default_cat):
                    _add(name, cat)
            if len(results) >= max_count:
                break
        add_log(f"네이버 검색 수집: {len(results)}명")
    else:
        add_log("네이버 API 키 없음 - Google Trends만 사용", "WARN")

    # 2. Google Trends 보조
    if len(results) < max_count:
        for name, cat in _get_google_trending_names():
            _add(name, cat)

    add_log(f"유명인 수집 완료: {len(results)}명")
    return results[:max_count]


def get_celebrity_keywords(count: int = 50) -> list[str]:
    """
    유명인 + 카테고리 조합 키워드 생성
    반환: ["김연아 건강 비결", "손흥민 운동 방법", ...]
    """
    celebs = get_celebrity_names(max_count=60)
    if not celebs:
        add_log("유명인 수집 결과 없음", "WARN")
        return []

    keywords = []
    seen_keywords = set()

    # 인물당 여러 카테고리 조합 생성
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
