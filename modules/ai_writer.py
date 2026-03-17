"""
AI 글쓰기 모듈 - Gemini API (무료 티어)
SEO 최적화 구조로 글 생성
"""
import re
from google import genai
from config import get_api_key, get_setting
from database.db import add_log, record_gemini_usage


def _get_client():
    api_key = get_api_key("gemini")
    if not api_key:
        raise ValueError("Gemini API 키가 설정되지 않았습니다.")
    return genai.Client(api_key=api_key)


def _build_prompt(keyword: str, style: str = "") -> str:
    style_guide = style or get_setting("writing_style") or "친근하고 정보성 있는 블로그 말투"
    return f"""
당신은 SEO 전문 블로그 작가입니다.
아래 키워드(포커스 키워드)를 주제로 블로그 글을 작성해주세요.

[포커스 키워드]
{keyword}

[제목 작성 규칙 - 반드시 준수]
1. 길이: 공백 포함 24자 ~ 30자 이내 (모바일 검색 결과 최적화)
2. 포커스 키워드를 제목 맨 앞 15자 이내에 배치
3. 아래 심리 자극 요소 중 하나를 반드시 포함 (심리 자극 요소를 참고하고 유사하게 확장했으면 좋겠어):
   - 이득: "~로 혜택 받는 법", "~로 비용 아끼기"
   - 손실: "모르면 손해보는 ~", "나만 몰랐던 ~"
   - 속도: "3분 만에 끝내는 ~", "단 7일 만에 ~"
   - 희소성: "~ 핵심 정리", "~ 비교 분석", "~ 차이점"
   - 실용: "~ 가성비 조합", "~ 비용 아끼는 팁"
   - 손실 예방: "실패 없는 ~", "주의해야 할 ~", "미리 체크하는 ~"
   - 시간 효율: "단계별 ~ 가이드", "5분 만에 배우는 ~", "간단하게 끝내는 ~"
4. 숫자 포함 권장 (예: 3가지, 7일, 5단계)
5. 금지: 특수문자, 홍보성 단어(이벤트·강추·무료·공짜·할인·1위 등)

[본문 작성 규칙]
1. 메타 설명: 검색 결과에 표시될 요약문 (150자 이내)
2. 본문 구조:
   - 도입부: 독자의 관심을 끄는 시작 (2~3문장)
   - H2 섹션 4~5개: 각 섹션마다 H3 소제목 1~2개 포함
   - 각 섹션 200~300자 이상
   - 결론: 핵심 요약 및 행동 유도
3. 포커스 키워드를 자연스럽게 제목, 첫 단락, 각 H2에 포함
4. 글 전체 길이: 1500자 이상
5. 말투: {style_guide}

[출력 형식 - 반드시 아래 형식 준수]
===TITLE===
(제목)
===META===
(메타 설명)
===CONTENT===
(HTML 형식 본문 - h2, h3, p 태그 사용)
===TAGS===
(관련 태그 5~8개, 쉼표 구분)
===CATEGORY===
(카테고리 1개)
"""


def generate_post(keyword: str, style: str = "") -> dict:
    """
    키워드로 SEO 최적화 글 생성
    반환: {title, meta, content, tags, category}
    """
    add_log(f"AI 글쓰기 시작: {keyword}")
    try:
        client = _get_client()
        prompt = _build_prompt(keyword, style)
        response = client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt
        )
        text = response.text

        # 토큰 사용량 기록
        usage = getattr(response, "usage_metadata", None)
        if usage:
            pt = getattr(usage, "prompt_token_count", 0) or 0
            ct = getattr(usage, "candidates_token_count", 0) or 0
            tt = getattr(usage, "total_token_count", 0) or (pt + ct)
            record_gemini_usage(pt, ct, tt)
            add_log(f"Gemini 토큰 사용: 입력 {pt} + 출력 {ct} = {tt}개")

        result = _parse_response(text, keyword)
        _validate_content(result, keyword)

        add_log(f"AI 글쓰기 완료: {result['title']}")
        return result

    except Exception as e:
        add_log(f"AI 글쓰기 실패 ({keyword}): {e}", "ERROR")
        raise


def _parse_response(text: str, keyword: str) -> dict:
    def extract(tag: str) -> str:
        pattern = rf"==={tag}===\s*(.*?)(?====|\Z)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""

    title = extract("TITLE") or f"{keyword} 완벽 가이드"
    meta = extract("META") or f"{keyword}에 대한 모든 것을 알아보세요."
    content = extract("CONTENT") or text
    tags_raw = extract("TAGS")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else [keyword]
    category = extract("CATEGORY") or "일반"

    return {
        "title": title,
        "meta": meta,
        "content": content,
        "tags": tags,
        "category": category,
        "keyword": keyword,
    }


def _validate_content(result: dict, keyword: str):
    """글 품질 최소 기준 검증"""
    min_length = get_setting("min_content_length") or 800

    content_text = re.sub(r"<[^>]+>", "", result["content"])
    if len(content_text) < min_length:
        raise ValueError(f"글 길이 부족: {len(content_text)}자 (최소 {min_length}자)")

    if keyword.lower() not in result["content"].lower() and keyword.lower() not in result["title"].lower():
        add_log(f"경고: 키워드 '{keyword}'가 글에 포함되지 않음", "WARN")
