"""
수익형 키워드 분석 모듈
RSS 수집(24h) → 네이버 자동완성어/연관검색어 + 구글 자동완성어
→ 검색광고 API(검색량) → 블로그 검색(문서량) → 경쟁도 계산 → SEO 제목 생성
"""
import hashlib
import hmac
import base64
import time
import re
import email.utils
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from config import get_api_key
from database.db import add_log

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 노이즈 패턴: keyword_fetcher와 동일하게 유지
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

_TITLE_PREFIX_STRIP = re.compile(
    r"^(?:\[.+?\]|【.+?】|〔.+?〕|「.+?」|\(.+?\)|\d+\.\s*|\d+위\s*|\d+일\s*|\d+월\s*)+"
)
_TITLE_SUFFIX_STRIP = re.compile(
    r"[\s]*(한다|됩니다|밝혀|나서|발표|진행|실시|추진|강화|개최|열려|마련|"
    r"시행|도입|확대|논의|검토|공개|촉구|요청|통해|위해|따라|관련|예정|"
    r"완료|성공|실패|기준|현황|전망|분석|비교|정리|총정리).*$"
)


def _extract_keyword_from_title(title: str) -> str:
    kw = re.sub(r"[^\w\s가-힣]", " ", title)
    kw = re.sub(r"\s+", " ", kw).strip()
    kw = _TITLE_PREFIX_STRIP.sub("", kw).strip()
    kw = _TITLE_SUFFIX_STRIP.sub("", kw).strip()
    words = kw.split()
    if len(words) > 4:
        kw = " ".join(words[:4])
    elif len(words) < 2:
        return ""
    return kw.strip()


def _is_good_keyword(kw: str) -> bool:
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

# ─── RSS 피드 목록 ────────────────────────────────────

HEALTH_RSS = [
    "https://health.chosun.com/rss/healthcaren.xml",
    "https://health.chosun.com/site/data/rss/rss.xml",
    "https://kormedi.com/category/healthnews/feed/",
    "https://kormedi.com/category/healthnews/diet/feed/",
    "https://kormedi.com/category/healthnews/food/feed/",
    "https://kormedi.com/category/healthnews/exercise/feed/",
    "https://kormedi.com/category/life/feed/",
    "https://kormedi.com/category/medical/feed/",
    "https://www.mkhealth.co.kr/rss/allArticle.xml",
    "https://www.foodnews.co.kr/rss/S1N1.xml",
    "https://www.psychiatricnews.net/rss/allArticle.xml",
]

POLICY_RSS = [
    "https://www.korea.kr/rss/policy.xml",
    "https://www.korea.kr/rss/insight.xml",
    "https://www.korea.kr/rss/column.xml",
]


# ─── RSS 수집 ─────────────────────────────────────────

def fetch_rss_keywords(feeds: list[str], max_per_feed: int = 5, hours: int = 24) -> list[str]:
    """RSS 피드에서 24시간 이내 최신 키워드 추출"""
    keywords = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for url in feeds:
        try:
            resp = requests.get(url, timeout=8, headers=HEADERS)
            resp.raise_for_status()
            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError:
                content = resp.content.decode("utf-8", errors="ignore").encode("utf-8")
                root = ET.fromstring(content)

            count = 0
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
                        pass

                title_tag = item.find("title")
                if title_tag is not None and title_tag.text:
                    kw = _extract_keyword_from_title(title_tag.text)
                    if kw and _is_good_keyword(kw) and kw not in keywords:
                        keywords.append(kw)
                        count += 1
                if count >= max_per_feed:
                    break
        except Exception as e:
            add_log(f"RSS 수집 실패 ({url}): {e}", "WARN")
            continue
    return keywords


# ─── 네이버 자동완성 ──────────────────────────────────

def get_naver_autocomplete(keyword: str, max_count: int = 5) -> list[str]:
    """네이버 자동완성어 (검색창 입력 시 드롭다운 추천어)"""
    try:
        resp = requests.get(
            "https://ac.search.naver.com/nx/ac",
            params={"q": keyword, "st": "100", "r_format": "json",
                    "r_enc": "UTF-8", "q_enc": "UTF-8", "from": "nx"},
            timeout=5, headers=HEADERS,
        )
        data = resp.json()
        items = data.get("items", [[]])[0]
        return [item[0] for item in items[:max_count] if item]
    except Exception as e:
        add_log(f"네이버 자동완성 실패 ({keyword}): {e}", "WARN")
        return []


def get_naver_related(keyword: str, max_count: int = 5) -> list[str]:
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
        related = items[1] if len(items) > 1 else []
        return [item[0] for item in related[:max_count] if item]
    except Exception as e:
        add_log(f"네이버 연관검색어 실패 ({keyword}): {e}", "WARN")
        return []


def get_google_autocomplete(keyword: str, max_count: int = 5) -> list[str]:
    """구글 자동완성어 (질문형/How-to 키워드 포함)"""
    try:
        resp = requests.get(
            "https://suggestqueries.google.com/complete/search",
            params={"output": "firefox", "hl": "ko", "q": keyword},
            timeout=5, headers=HEADERS,
        )
        data = resp.json()
        suggestions = data[1] if len(data) > 1 else []
        return [s for s in suggestions[:max_count] if s and s != keyword]
    except Exception as e:
        add_log(f"구글 자동완성 실패 ({keyword}): {e}", "WARN")
        return []


# ─── 네이버 검색광고 API ──────────────────────────────

def _make_ad_signature(timestamp: str, method: str, uri: str, secret: str) -> str:
    message = f"{timestamp}.{method}.{uri}"
    secret_bytes = base64.b64decode(secret)
    hashed = hmac.new(secret_bytes, message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(hashed).decode("utf-8")


def get_naver_search_volume(keywords: list[str]) -> dict[str, dict]:
    """
    네이버 검색광고 API로 월간 검색량 조회
    반환: {keyword: {pc: int, mobile: int, total: int}}
    """
    customer_id = get_api_key("naver_ad_customer_id")
    api_key = get_api_key("naver_ad_license")
    secret = get_api_key("naver_ad_secret")

    if not all([customer_id, api_key, secret]):
        add_log("네이버 검색광고 API 키 없음", "WARN")
        return {}

    result = {}
    # API는 한 번에 최대 5개
    for i in range(0, len(keywords), 5):
        batch = keywords[i:i+5]
        try:
            timestamp = str(int(time.time() * 1000))
            uri = "/keywordstool"
            sig = _make_ad_signature(timestamp, "GET", uri, secret)

            resp = requests.get(
                f"https://api.naver.com{uri}",
                params={"hintKeywords": ",".join(batch), "showDetail": "1"},
                headers={
                    "X-Timestamp": timestamp,
                    "X-API-KEY": api_key,
                    "X-Customer": str(customer_id),
                    "X-Signature": sig,
                },
                timeout=10,
            )
            data = resp.json()
            for item in data.get("keywordList", []):
                kw = item.get("relKeyword", "")
                pc = int(item.get("monthlyPcQcCnt", 0) or 0)
                mobile = int(item.get("monthlyMobileQcCnt", 0) or 0)
                result[kw] = {"pc": pc, "mobile": mobile, "total": pc + mobile}
        except Exception as e:
            add_log(f"검색광고 API 실패: {e}", "WARN")

    return result


# ─── 네이버 블로그 검색 (문서량) ──────────────────────

def get_blog_doc_count(keyword: str) -> int:
    """네이버 블로그 검색 문서 수"""
    client_id = get_api_key("naver_client_id")
    client_secret = get_api_key("naver_client_secret")

    if not client_id or not client_secret:
        return 0

    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/blog",
            params={"query": keyword, "display": 1},
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            timeout=8,
        )
        return int(resp.json().get("total", 0))
    except Exception as e:
        add_log(f"블로그 문서량 조회 실패 ({keyword}): {e}", "WARN")
        return 0


# ─── 경쟁도 / 추천도 계산 ────────────────────────────

def calc_competition(search_vol: int, doc_count: int) -> dict:
    """경쟁 강도 및 추천도 계산"""
    if search_vol == 0:
        return {"ratio": 999, "level": "매우 높음", "score": 1}

    ratio = round(doc_count / search_vol, 2)

    if ratio < 1.0:
        level = "매우 낮음"
    elif ratio < 3.0:
        level = "낮음"
    elif ratio < 8.0:
        level = "보통"
    elif ratio < 15.0:
        level = "높음"
    else:
        level = "매우 높음"

    # 추천도 (1~5)
    if ratio < 1.0 and search_vol >= 500:
        score = 5
    elif ratio < 1.5 and search_vol >= 300:
        score = 4
    elif ratio < 3.0 and search_vol >= 100:
        score = 3
    elif ratio < 8.0 and search_vol >= 50:
        score = 2
    else:
        score = 1

    return {"ratio": ratio, "level": level, "score": score}


def estimate_cpc(keyword: str, search_vol: int) -> str:
    """키워드 카테고리별 예상 CPC 추정"""
    health_words = ["건강", "다이어트", "영양", "비타민", "운동", "병원", "약", "치료",
                    "피부", "탈모", "암", "당뇨", "혈압", "관절", "수면"]
    finance_words = ["보험", "대출", "투자", "주식", "펀드", "재테크", "연금", "세금",
                     "부동산", "청약", "적금", "카드"]

    kw_lower = keyword.lower()
    if any(w in kw_lower for w in health_words):
        base = 600
    elif any(w in kw_lower for w in finance_words):
        base = 900
    else:
        base = 250

    # 검색량 높을수록 단가 상승
    if search_vol >= 5000:
        base = int(base * 1.5)
    elif search_vol >= 1000:
        base = int(base * 1.2)

    return f"{base:,}원 ~ {int(base * 2.5):,}원"


# ─── SEO 제목 생성 ────────────────────────────────────

TITLE_TEMPLATES = [
    # 이득 — "~로 혜택/비용 아끼기"
    "{kw} 혜택 받는 3가지 핵심 방법",
    "{kw}로 비용 아끼는 5가지 팁",
    "{kw} 나만 몰랐던 절약 꿀팁 7가지",
    # 손실 — "모르면 손해, 나만 몰랐던"
    "{kw} 모르면 손해보는 핵심 7가지",
    "{kw} 나만 모르던 실수 5가지 정리",
    # 손실 예방 — "실패 없이, 미리 체크"
    "{kw} 실패 없이 끝내는 5단계 가이드",
    "{kw} 미리 체크해야 할 3가지 핵심",
    # 시간 효율 — "3분, 7일, 단계별"
    "{kw} 3분 만에 끝내는 단계별 정리",
    "{kw} 단 7일 만에 바꾸는 실전 방법",
    # 희소성/정보 — "핵심 정리, 비교 분석, 차이점"
    "{kw} 핵심만 정리한 비교 분석",
    "{kw} 잘 모르는 차이점 3가지 정리",
    "{kw} 가성비 조합으로 비용 줄이는 법",
]


def generate_seo_title(keyword: str) -> str:
    """
    SEO 제목 생성 (규칙 기반)
    - 포커스 키워드를 맨 앞 15자 이내에 배치
    - 24~30자 (모바일 최적화)
    - 숫자 포함 권장
    - 특수문자·홍보성 단어 금지
    """
    BANNED = ["무료", "공짜", "할인", "이벤트", "강추", "1위"]
    for template in TITLE_TEMPLATES:
        title = template.replace("{kw}", keyword)
        title = re.sub(r"[^\w\s가-힣]", "", title).strip()
        title_len = len(title)
        if (24 <= title_len <= 32
                and keyword in title
                and not any(b in title for b in BANNED)):
            return title

    # 폴백
    title = re.sub(r"[^\w\s가-힣]", "", f"{keyword} 핵심 정리 가이드").strip()
    return title[:32]


def _describe_source(keyword: str, original: str) -> str:
    """키워드 출처 설명"""
    if keyword == original:
        return "RSS 원본 키워드"
    return f"'{original}' 자동완성"


# ─── 메인 분석 함수 ───────────────────────────────────

def analyze_keywords(mode: str = "health", top_n: int = 5) -> list[dict]:
    """
    전체 키워드 분석 파이프라인
    mode: 'health' | 'biz'
    반환: 분석 결과 리스트
    """
    add_log(f"키워드 분석 시작 (모드: {mode})")

    # 1. RSS 수집
    feeds = HEALTH_RSS if mode == "health" else POLICY_RSS
    rss_keywords = fetch_rss_keywords(feeds[:6], max_per_feed=5)
    add_log(f"RSS 키워드 {len(rss_keywords)}개 수집")

    if not rss_keywords:
        add_log("RSS 수집 실패 - 기본 키워드 사용", "WARN")
        rss_keywords = ["건강 식단", "다이어트 방법", "운동 루틴"] if mode == "health" else ["재테크 방법", "부업 추천"]

    # 2. 네이버 자동완성어 + 연관검색어 + 구글 자동완성어로 확장
    all_candidates = []
    for rss_kw in rss_keywords[:8]:
        # RSS 원본
        all_candidates.append({"keyword": rss_kw, "source": "RSS 원본", "original": rss_kw})
        # 1-2-1. 네이버 자동완성어
        for ac_kw in get_naver_autocomplete(rss_kw, max_count=3):
            all_candidates.append({"keyword": ac_kw, "source": "네이버 자동완성어", "original": rss_kw})
        # 1-2-2. 네이버 연관검색어
        for rel_kw in get_naver_related(rss_kw, max_count=3):
            all_candidates.append({"keyword": rel_kw, "source": "네이버 연관검색어", "original": rss_kw})
        # 1-3-1. 구글 자동완성어
        for g_kw in get_google_autocomplete(rss_kw, max_count=2):
            all_candidates.append({"keyword": g_kw, "source": "구글 자동완성어", "original": rss_kw})

    # 중복 제거
    seen = set()
    unique = []
    for c in all_candidates:
        if c["keyword"] not in seen:
            seen.add(c["keyword"])
            unique.append(c)

    add_log(f"후보 키워드 {len(unique)}개 (중복 제거 후)")

    # 3. 검색량 조회 (배치)
    kw_list = [c["keyword"] for c in unique[:20]]
    search_volumes = get_naver_search_volume(kw_list)

    # 4. 각 키워드 분석
    results = []
    for cand in unique[:20]:
        kw = cand["keyword"]
        vol_data = search_volumes.get(kw, {"pc": 0, "mobile": 0, "total": 0})
        total_vol = vol_data["total"]

        if total_vol < 100:  # 검색량 너무 적으면 스킵
            continue

        doc_count = get_blog_doc_count(kw)
        comp = calc_competition(total_vol, doc_count)
        cpc = estimate_cpc(kw, total_vol)
        title = generate_seo_title(kw)

        results.append({
            "keyword": kw,
            "title": title,
            "source": cand["source"],
            "original": cand["original"],
            "search_pc": vol_data["pc"],
            "search_mobile": vol_data["mobile"],
            "search_total": total_vol,
            "doc_count": doc_count,
            "competition_ratio": comp["ratio"],
            "competition_level": comp["level"],
            "recommendation": comp["score"],
            "cpc_estimate": cpc,
        })

    # 5. 경쟁도 낮음 + 추천도 높음 순 정렬
    results.sort(key=lambda x: (x["competition_ratio"], -x["search_total"]))

    # 매우 낮음 + 추천도 5인 것만 우선, 없으면 낮음 포함
    top = [r for r in results if r["competition_level"] == "매우 낮음" and r["recommendation"] == 5]
    if len(top) < top_n:
        top += [r for r in results if r not in top and r["competition_level"] in ("매우 낮음", "낮음")]

    top = top[:top_n]
    add_log(f"키워드 분석 완료: {len(top)}개 선별")
    return top
