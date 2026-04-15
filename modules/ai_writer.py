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

[제목 작성 규칙 v2.0 - 반드시 준수]
1. 길이: 공백 포함 24자 ~ 30자 이내 (모바일 검색 결과 최적화)
2. 포커스 키워드를 제목 맨 앞 15자 이내에 배치
3. 문맥적 병합 (Contextual Merging): 포커스 키워드와 심리 자극 요소를 단순 나열하지 말고, 하나의 완성된 문장형으로 구성하라.
   - 나쁜 예 (나열형): "공황장애 증상, 3분 만에 끝내는 핵심 정리"
   - 좋은 예 (자연스러운 연결): "공황장애 증상 3분 만에 자가진단하고 대처하는 법"
   - 포커스 키워드가 문장의 주어나 목적어 역할을 하도록 구조를 설계할 것
4. 동사 위주의 능동형 표현: 명사형 나열(~법, ~팁)보다 동사(~하세요, ~줄입니다)로 독자의 행동을 유도하라.
   - 예: "혜택 받는 법" → "혜택 놓치지 마세요" 또는 "혜택 바로 확인하기"
5. 아래 심리 자극 요소 중 하나를 반드시 포함 (문맥적으로 자연스럽게 확장할 것):
   - 이득 (Value): "[포커스 키워드]로 내 자산 10% 불리는 실전 노하우"
   - 손실 (Loss): "모르면 매달 손해 보는 [포커스 키워드] 환급 가이드"
   - 비교 (Analysis): "결정 장애 끝내는 [포커스 키워드] 3종 완벽 비교"
   - 효율 (Time): "바쁜 직장인을 위한 [포커스 키워드] 5분 요약본"
   - 안전 (Caution): "초보자가 흔히 하는 [포커스 키워드] 실수 3가지 방지법"
6. 타겟 페르소나 설정 (선택): 해당 정보가 필요한 대상을 구체화하여 심리적 연결고리를 강화하라.
   - 예: "사회초년생이 꼭 알아야 할 [키워드]", "부모님 선물용 [키워드] 고르는 기준"
7. 숫자와 단위의 구체화: 단순 숫자보다 신뢰도를 높이는 구체적 수치를 활용하라.
   - 예: "비용 아끼기" → "연간 24만원 절약하는", "7일 만에" → "일주일 뒤 변화 확인하는"
8. 금지: 특수문자, 홍보성 단어(이벤트·강추·무료·공짜·할인·1위 등)

[본문 작성 규칙]

★ 말투: {style_guide}

★ 2. 도입부
- 포커스 키워드가 반드시 첫 문장에 포함
- 전체 분량: 150자 이상 170자 이내 (공백 포함)
- 독자의 공감을 끌어내는 시작

★ 3. 경험사례 삽입 규칙
- 별도 <h2>경험 사례</h2> 섹션으로 분리하지 말 것 (금지)
- 각 H2 본문 내용 중간에 자연스럽게 녹여 작성
- 삽입 위치: 전체 H2 중 2~3개에만 배치 (모든 H2마다 넣지 말 것)
- 분량: 한 곳당 50자~100자 이내 (짧고 자연스럽게)
- 시점: 3인칭 권장 (지인, 친구, 직장 동료 등)
- 톤: 일상적 표현 + 감정 표현 적극 사용
- 올바른 예: <p>이 방법은 효과가 빠릅니다. 실제로 지인도 처음엔 반신반의했는데, 2주 후 "이렇게 달라질 줄 몰랐다"며 놀랐다고 하더라고요.</p>

★ 4. 본문 구성
[제목에 숫자(N가지, N개, N단계 등)가 있는 경우]
- 해당 숫자만큼 H2로 구분 (예: "5가지" → H2를 5개)
- H2 형식 예: <h2>1. 첫 번째 방법</h2>
- 각 H2마다 본문 250자 이상
- 필요 시 H3, H4 소제목 활용
- 각 H2에 내용 정리용 <table> 삽입 권장

[제목에 숫자가 없는 경우]
- H2 섹션 4~5개로 구성
- 각 H2마다 본문 250자 이상
- H3 소제목 1~2개 포함 가능

2~3개 H2에 경험사례(★3번 규칙)를 본문 흐름 속에 자연스럽게 삽입할 것.

★ 5. 자주 묻는 질문 (FAQ)
아래 형식을 정확히 지켜 작성:
<h2>자주 묻는 질문</h2>
<h3>질문 1 내용</h3><p>답변 (80자 이상)</p>
<h3>질문 2 내용</h3><p>답변 (80자 이상)</p>
<h3>질문 3 내용</h3><p>답변 (80자 이상)</p>
<h3>질문 4 내용</h3><p>답변 (80자 이상)</p>
<h3>질문 5 내용</h3><p>답변 (80자 이상)</p>
<h3>질문 6 내용</h3><p>답변 (80자 이상)</p>

★ 6. 글을 마치며
<h2>글을 마치며</h2>
본문 250자 이상 작성. 핵심 내용 요약 + 독자 행동 유도.

★ 전체 글 최소 길이: 2000자 이상 (HTML 태그 제외 순수 텍스트 기준)
★ 포커스 키워드를 제목, 도입부, 각 H2에 자연스럽게 포함

[출력 형식 - 반드시 아래 형식 준수]
===TITLE===
(제목)
===META===
(메타 설명 150자 이내)
===CONTENT===
(HTML 형식 본문 - h2, h3, h4, p, table 태그 사용)
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
    min_length = get_setting("min_content_length") or 2000

    content_text = re.sub(r"<[^>]+>", "", result["content"])
    if len(content_text) < min_length:
        raise ValueError(f"글 길이 부족: {len(content_text)}자 (최소 {min_length}자)")

    if keyword.lower() not in result["content"].lower() and keyword.lower() not in result["title"].lower():
        add_log(f"경고: 키워드 '{keyword}'가 글에 포함되지 않음", "WARN")
