"""
수익형 키워드 분석 모듈
RSS 수집 → 네이버 자동완성 → 검색광고 API(검색량) → 블로그 검색(문서량)
→ 경쟁도 계산 → SEO 제목 생성
"""
import hashlib
import hmac
import base64
import time
import re
import requests
import xml.etree.ElementTree as ET
from config import get_api_key
from database.db import add_log

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

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

def fetch_rss_keywords(feeds: list[str], max_per_feed: int = 5) -> list[str]:
    """RSS 피드에서 최신 키워드 추출"""
    keywords = []
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
                title_tag = item.find("title")
                if title_tag is not None and title_tag.text:
                    title = title_tag.text.strip()
                    # 제목에서 핵심 키워드 추출 (괄호/특수문자 제거, 앞 20자)
                    kw = re.sub(r"[^\w\s가-힣]", " ", title).strip()[:30]
                    kw = re.sub(r"\s+", " ", kw).strip()
                    if kw and len(kw) >= 4 and kw not in keywords:
                        keywords.append(kw)
                        count += 1
                if count >= max_per_feed:
                    break
        except Exception as e:
            add_log(f"RSS 수집 실패 ({url}): {e}", "WARN")
            continue
    return keywords


# ─── 네이버 자동완성 ──────────────────────────────────

def get_naver_autocomplete(keyword: str) -> list[str]:
    """네이버 자동완성 키워드 수집"""
    try:
        resp = requests.get(
            "https://ac.search.naver.com/nx/ac",
            params={"q": keyword, "st": "100", "r_format": "json",
                    "r_enc": "UTF-8", "q_enc": "UTF-8", "from": "nx"},
            timeout=5,
            headers=HEADERS,
        )
        data = resp.json()
        items = data.get("items", [[]])[0]
        return [item[0] for item in items if item]
    except Exception as e:
        add_log(f"네이버 자동완성 실패 ({keyword}): {e}", "WARN")
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
    # 이득
    "{kw} 혜택 받는 3가지 핵심 방법",
    "{kw}로 비용 아끼는 실전 팁",
    # 손실 예방
    "실패 없는 {kw} 핵심 정리 5가지",
    "주의해야 할 {kw} 체크리스트",
    "미리 체크하는 {kw} 가이드",
    # 시간 효율
    "5분 만에 배우는 {kw} 단계별 정리",
    "간단하게 끝내는 {kw} 완벽 가이드",
    # 희소성
    "{kw} 비교 분석 총정리",
    "잘 모르는 {kw}의 차이점 3가지",
    "{kw} 핵심만 정리한 노하우",
]


def generate_seo_title(keyword: str) -> str:
    """
    SEO 제목 생성 (규칙 기반)
    - 키워드를 맨 앞에 배치
    - 24~30자
    - 숫자 포함
    - 특수문자 금지
    """
    for template in TITLE_TEMPLATES:
        title = template.replace("{kw}", keyword)
        # 특수문자 제거
        title = re.sub(r"[^\w\s가-힣]", "", title).strip()
        title_len = len(title)
        if 20 <= title_len <= 35 and keyword in title:
            return title

    # 폴백: 간단한 제목
    title = f"{keyword} 핵심 정리 가이드"
    return title[:35]


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

    # 2. 자동완성으로 확장
    all_candidates = []
    for rss_kw in rss_keywords[:8]:
        autocomplete = get_naver_autocomplete(rss_kw)
        for ac_kw in autocomplete[:5]:
            all_candidates.append({"keyword": ac_kw, "source": "자동완성어", "original": rss_kw})
        # 원본도 포함
        all_candidates.append({"keyword": rss_kw, "source": "RSS 원본", "original": rss_kw})

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
