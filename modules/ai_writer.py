"""
AI 글쓰기 모듈 - Gemini API (무료 티어)
SEO 최적화 구조로 글 생성
"""
import re
import google.generativeai as genai
from config import get_api_key, get_setting
from database.db import add_log


def _get_model():
    api_key = get_api_key("gemini")
    if not api_key:
        raise ValueError("Gemini API 키가 설정되지 않았습니다.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.5-flash")  # 무료 티어


def _build_prompt(keyword: str, style: str = "") -> str:
    style_guide = style or get_setting("writing_style") or "친근하고 정보성 있는 블로그 말투"
    return f"""
당신은 SEO 전문 블로그 작가입니다.
아래 키워드를 주제로 블로그 글을 작성해주세요.

[키워드]
{keyword}

[작성 규칙]
1. 제목: SEO에 최적화된 매력적인 제목 (60자 이내)
2. 메타 설명: 검색 결과에 표시될 요약문 (150자 이내)
3. 본문 구조:
   - 도입부: 독자의 관심을 끄는 시작 (2~3문장)
   - H2 섹션 4~5개: 각 섹션마다 H3 소제목 1~2개 포함
   - 각 섹션 200~300자 이상
   - 결론: 핵심 요약 및 행동 유도
4. 키워드를 자연스럽게 제목, 첫 단락, 각 H2에 포함
5. 글 전체 길이: 1500자 이상
6. 말투: {style_guide}

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
        model = _get_model()
        prompt = _build_prompt(keyword, style)
        response = model.generate_content(prompt)
        text = response.text

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
