"""
자동 글쓰기 & 예약 업로드 스케줄러
"""
import re
import time
from datetime import datetime, timedelta
from database.db import add_log, add_post, update_post_status, get_published_titles
from modules.keyword_fetcher import get_fresh_keywords
from modules.ai_writer import generate_post
from modules.content_researcher import get_research_context
from modules.image_fetcher import get_images, embed_images_in_content
from modules.sitemap_crawler import insert_external_links
from modules.blogger_uploader import publish_post


def _title_similarity(t1: str, t2: str) -> float:
    """제목 키워드 겹침 유사도 (0~1)"""
    w1 = set(re.findall(r"[가-힣a-zA-Z]{2,}", t1.lower()))
    w2 = set(re.findall(r"[가-힣a-zA-Z]{2,}", t2.lower()))
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / max(len(w1), len(w2))


def _is_title_duplicate(new_title: str, threshold: float = 0.7) -> tuple:
    """기존 발행 제목과 유사도 체크 - (중복여부, 유사제목)"""
    existing = get_published_titles(days=90)
    for title in existing:
        if _title_similarity(new_title, title) >= threshold:
            return True, title
    return False, ""


def run_single_post(
    keyword: str = None,
    fixed_title: str = None,
    scheduled_at: str = None,
    settings: dict = None,
) -> dict:
    """
    단일 글 작성 및 업로드 파이프라인
    fixed_title: AI 제목 대기열에서 선택한 확정 제목 (있으면 제목 고정, 본문만 생성)
    settings: {image_count, min_content_length, writing_style}
    """
    settings = settings or {}
    try:
        # 1. 키워드 선택 (fixed_title이 있으면 제목 자체를 키워드로 활용)
        if not keyword:
            if fixed_title:
                keyword = fixed_title
            else:
                keywords = get_fresh_keywords(count=1)
                if not keywords:
                    return {"success": False, "error": "사용 가능한 키워드 없음"}
                keyword = keywords[0]

        add_log(f"=== 글쓰기 파이프라인 시작: {keyword} ===" + (f" [확정 제목: {fixed_title}]" if fixed_title else ""))

        # 2. 콘텐츠 리서치 (네이버 검색 API)
        research_context = get_research_context(keyword)

        # 3. AI 글쓰기 (리서치 컨텍스트 + Gemini Grounding)
        style = settings.get("writing_style", "")
        post_data = generate_post(keyword, style=style, research_context=research_context, fixed_title=fixed_title or "")

        # 제목 유사도 중복 체크
        is_dup, similar_title = _is_title_duplicate(post_data["title"])
        if is_dup:
            add_log(f"유사 제목 중복 스킵: '{post_data['title']}' ≈ '{similar_title}'", "WARN")
            return {"success": False, "error": f"유사 제목 존재: {similar_title}"}
        post_id = add_post(keyword, post_data["title"], scheduled_at)

        # 4. 이미지 삽입
        image_count = settings.get("image_count", 5)
        images = get_images(keyword, image_count)
        content_with_images = embed_images_in_content(post_data["content"], images)

        # 5. 외부 링크 삽입 (무조건 하단 '함께 보면 좋은 글' 포함)
        final_content = insert_external_links(content_with_images, keyword=keyword)

        # 6. 메타 설명 + 본문 합치기
        full_content = (
            f'<meta name="description" content="{post_data["meta"]}">\n'
            f'<!-- keyword: {keyword} -->\n'
            f'{final_content}'
        )

        # 7. Blogger 업로드
        result = publish_post(
            title=post_data["title"],
            content=full_content,
            tags=post_data["tags"],
            scheduled_at=scheduled_at,
        )

        # 8. DB 업데이트
        update_post_status(post_id, "published", blogger_post_id=result["id"])

        add_log(f"=== 파이프라인 완료: {post_data['title']} ===")
        return {
            "success": True,
            "post_id": post_id,
            "title": post_data["title"],
            "url": result["url"],
            "keyword": keyword,
        }

    except Exception as e:
        add_log(f"파이프라인 실패: {e}", "ERROR")
        if "post_id" in locals():
            update_post_status(post_id, "failed", error=str(e))
        return {"success": False, "error": str(e)}


def run_batch(
    keywords: list = None,
    titles: list = None,
    count: int = 1,
    interval_minutes: int = 60,
    scheduled: bool = False,
    settings: dict = None,
):
    """
    여러 키워드/확정 제목 배치 작성
    keywords: 키워드 목록 (없으면 자동) - AI가 제목+본문 생성
    titles: AI 확정 제목 목록 - 제목 고정, 본문만 생성
    scheduled: True면 interval_minutes 간격으로 예약 발행
    """
    settings = settings or {}

    # 작업 목록 구성: {keyword, fixed_title}
    jobs = []
    for t in (titles or []):
        jobs.append({"keyword": None, "fixed_title": t})
    if keywords:
        for kw in keywords:
            jobs.append({"keyword": kw, "fixed_title": None})
    if not jobs:
        kws = get_fresh_keywords(count=count)
        if not kws:
            kws = [None] * count
        for kw in kws:
            jobs.append({"keyword": kw, "fixed_title": None})

    add_log(f"배치 시작: 총 {len(jobs)}개 (확정제목 {len(titles or [])}개 + 키워드 {len(keywords or [])}개), "
            f"{'예약 ' + str(interval_minutes) + '분 간격' if scheduled else '즉시 발행'}")
    results = []

    for i, job in enumerate(jobs):
        sched_at = None
        if scheduled:
            base = datetime.now() + timedelta(minutes=interval_minutes * (i + 1))
            sched_at = base.strftime("%Y-%m-%dT%H:%M:%S+09:00")

        result = run_single_post(
            keyword=job["keyword"],
            fixed_title=job["fixed_title"],
            scheduled_at=sched_at,
            settings=settings,
        )
        results.append(result)

        if not scheduled and i < len(jobs) - 1:
            add_log("다음 글 준비 중... 30초 대기")
            time.sleep(30)

    success = sum(1 for r in results if r["success"])
    add_log(f"배치 완료: 성공 {success}/{len(jobs)}")
    return results
