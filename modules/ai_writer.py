"""
AI 글쓰기 모듈 - Gemini API (무료 티어)
SEO 최적화 구조로 글 생성
"""
import re
import time
from google import genai
from config import get_api_key, get_setting
from database.db import add_log, record_gemini_usage


def _get_client():
    api_key = get_api_key("gemini")
    if not api_key:
        raise ValueError("Gemini API 키가 설정되지 않았습니다.")
    return genai.Client(api_key=api_key)


def _build_prompt(keyword: str, style: str = "", research_context: str = "", fixed_title: str = "") -> str:
    style_guide = style or get_setting("writing_style") or "친근하고 정보성 있는 블로그 말투"

    research_section = ""
    if research_context:
        research_section = f"""
[참고 자료 - 아래 내용을 참고하여 글을 작성하되, 절대 그대로 복사하지 말 것. 핵심 정보만 재구성하여 활용]
{research_context}

"""

    title_instruction = ""
    if fixed_title:
        title_instruction = f"""
[제목 고정 - 반드시 준수]
아래 제목을 그대로 사용하고 변경하지 말 것:
{fixed_title}

"""

    return f"""
당신은 SEO 전문 블로그 작가입니다.
{research_section}{title_instruction}아래 키워드(포커스 키워드)를 주제로 블로그 글을 작성해주세요.

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


def generate_post(keyword: str, style: str = "", research_context: str = "", fixed_title: str = "") -> dict:
    """
    키워드로 SEO 최적화 글 생성
    fixed_title: AI 제목 대기열에서 선택한 확정 제목 (옵션) - 제목 고정, 본문만 생성
    research_context: 네이버 검색으로 수집한 참고 자료 (옵션)
    반환: {title, meta, content, tags, category}
    503 과부하 시 최대 4회 재시도 (10→20→40→60초 간격)
    """
    log_msg = f"AI 글쓰기 시작: {keyword}"
    if fixed_title:
        log_msg += f" (확정 제목: {fixed_title})"
    elif research_context:
        log_msg += " (리서치 컨텍스트 포함)"
    add_log(log_msg)
    retry_delays = [10, 20, 40, 60]
    last_error = None

    for attempt in range(len(retry_delays) + 1):
        try:
            from google.genai import types
            client = _get_client()
            prompt = _build_prompt(keyword, style, research_context, fixed_title)
            # Gemini Grounding: 인터넷 검색으로 최신 정보 보완
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                ),
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
            if fixed_title:
                result["title"] = fixed_title
            _validate_content(result, keyword)

            add_log(f"AI 글쓰기 완료: {result['title']}")
            return result

        except Exception as e:
            last_error = e
            err_str = str(e)
            # 503 과부하 오류만 재시도
            if "503" in err_str and attempt < len(retry_delays):
                delay = retry_delays[attempt]
                add_log(f"Gemini 503 과부하 - {delay}초 후 재시도 ({attempt + 1}/{len(retry_delays)})", "WARN")
                time.sleep(delay)
            else:
                add_log(f"AI 글쓰기 실패 ({keyword}): {e}", "ERROR")
                raise

    add_log(f"AI 글쓰기 최종 실패 ({keyword}): {last_error}", "ERROR")
    raise last_error


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


def generate_seo_titles(articles: list[dict]) -> list[dict]:
    """
    뉴스 기사 목록(최대 5개)을 한 번의 Gemini 호출로 SEO 제목 3개씩 생성
    articles: [{"title": str, "content": str}, ...]
    반환: [{"original_title": str, "titles": [str, str, str]}, ...]
    """
    if not articles:
        return []

    articles = articles[:5]

    article_blocks = []
    for i, art in enumerate(articles, 1):
        block = f"[기사{i}]\n뉴스 제목: {art['title']}\n본문 발췌:\n{art.get('content', '(본문 없음)')}"
        article_blocks.append(block)

    articles_text = "\n\n".join(article_blocks)

    prompt = f"""당신은 SEO 전문 블로그 작가입니다.
아래 각 기사를 읽고, 각 기사마다 블로그 제목을 3개씩 생성하세요.

[제목 작성 규칙 v2.0 - 반드시 준수]
1. 길이: 공백 포함 24자 ~ 30자 이내
2. 핵심 키워드를 제목 맨 앞 15자 이내에 배치
3. 문맥적 병합: 키워드와 심리 자극 요소를 하나의 완성된 문장으로 구성
   - 나쁜 예: "공황장애 증상, 3분 만에 끝내는 핵심 정리"
   - 좋은 예: "공황장애 증상 3분 만에 자가진단하고 대처하는 법"
4. 동사 위주 능동형 표현 사용
5. 3개 제목은 각각 다른 심리 자극 요소 사용:
   - 이득(Value), 손실(Loss), 비교(Analysis), 효율(Time), 안전(Caution) 중에서
6. 숫자 구체화 권장 (예: "연간 24만원 절약", "2주 만에 변화")
7. 금지: 특수문자, 홍보성 단어(무료·강추·이벤트·1위 등)

[기사 목록]
{articles_text}

[응답 형식 - 반드시 이 형식만 사용]
기사1:
1. 제목
2. 제목
3. 제목

기사2:
1. 제목
2. 제목
3. 제목

(기사 수만큼 반복)"""

    add_log(f"SEO 제목 생성 시작: 기사 {len(articles)}개")
    retry_delays = [10, 20, 40, 60]
    last_error = None

    for attempt in range(len(retry_delays) + 1):
        try:
            client = _get_client()
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            text = response.text

            usage = getattr(response, "usage_metadata", None)
            if usage:
                pt = getattr(usage, "prompt_token_count", 0) or 0
                ct = getattr(usage, "candidates_token_count", 0) or 0
                tt = getattr(usage, "total_token_count", 0) or (pt + ct)
                record_gemini_usage(pt, ct, tt)
                add_log(f"Gemini 토큰 사용: 입력 {pt} + 출력 {ct} = {tt}개")

            results = _parse_titles_response(text, articles)
            add_log(f"SEO 제목 생성 완료: {len(results)}개 기사")
            return results

        except Exception as e:
            last_error = e
            err_str = str(e)
            if "503" in err_str and attempt < len(retry_delays):
                delay = retry_delays[attempt]
                add_log(f"Gemini 503 과부하 - {delay}초 후 재시도 ({attempt + 1}/{len(retry_delays)})", "WARN")
                time.sleep(delay)
            else:
                add_log(f"SEO 제목 생성 실패: {e}", "ERROR")
                raise

    raise last_error


def _parse_titles_response(text: str, articles: list[dict]) -> list[dict]:
    """Gemini 응답에서 기사별 제목 3개 파싱"""
    results = []
    for i, art in enumerate(articles, 1):
        pattern = rf"기사{i}[:\s]*\n((?:.*\n?){{1,6}})"
        match = re.search(pattern, text)
        titles = []
        if match:
            block = match.group(1)
            for line in block.strip().splitlines():
                line = re.sub(r"^\s*\d+\.\s*", "", line).strip()
                if line and not line.startswith("기사"):
                    titles.append(line)
                if len(titles) >= 3:
                    break

        while len(titles) < 3:
            titles.append(f"{art['title'][:20]} 완벽 정리")

        results.append({
            "original_title": art["title"],
            "titles": titles[:3],
        })
    return results
