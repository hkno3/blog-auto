"""
자동 글쓰기 & 예약 업로드 스케줄러
"""
import re
import time
from datetime import datetime, timedelta
from database.db import add_log, mark_keyword_used, add_post, update_post_status, is_keyword_used, get_published_titles
from modules.keyword_fetcher import get_fresh_keywords
from modules.ai_writer import generate_post
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
    scheduled_at: str = None,
    settings: dict = None,
) -> dict:
    """
    단일 글 작성 및 업로드 파이프라인
    settings: {image_count, min_content_length, writing_style}
    """
    settings = settings or {}
    try:
        # 1. 키워드 선택
        if not keyword:
            keywords = get_fresh_keywords(count=1)
            if not keywords:
                return {"success": False, "error": "사용 가능한 키워드 없음"}
            keyword = keywords[0]

        # [방법 1+3] 키워드 중복 체크 (자동/수동 공통)
        if is_keyword_used(keyword, days=30):
            add_log(f"중복 키워드 스킵 (30일 이내 사용됨): {keyword}", "WARN")
            return {"success": False, "error": f"중복 키워드: {keyword} (30일 이내 사용됨)"}

        add_log(f"=== 글쓰기 파이프라인 시작: {keyword} ===")

        # 2. AI 글쓰기
        style = settings.get("writing_style", "")
        post_data = generate_post(keyword, style=style)

        # [방법 2] 제목 유사도 중복 체크
        is_dup, similar_title = _is_title_duplicate(post_data["title"])
        if is_dup:
            add_log(f"유사 제목 중복 스킵: '{post_data['title']}' ≈ '{similar_title}'", "WARN")
            return {"success": False, "error": f"유사 제목 존재: {similar_title}"}
        post_id = add_post(keyword, post_data["title"], scheduled_at)

        # 3. 이미지 삽입
        image_count = settings.get("image_count", 5)
        images = get_images(keyword, image_count)
        content_with_images = embed_images_in_content(post_data["content"], images)

        # 4. 외부 링크 삽입 (무조건 하단 '함께 보면 좋은 글' 포함)
        final_content = insert_external_links(content_with_images, keyword=keyword)

        # 5. 메타 설명 + 본문 합치기
        full_content = (
            f'<meta name="description" content="{post_data["meta"]}">\n'
            f'<!-- keyword: {keyword} -->\n'
            f'{final_content}'
        )

        # 6. Blogger 업로드
        result = publish_post(
            title=post_data["title"],
            content=full_content,
            tags=post_data["tags"],
            scheduled_at=scheduled_at,
        )

        # 7. DB 업데이트
        update_post_status(post_id, "published", blogger_post_id=result["id"])
        mark_keyword_used(keyword)

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
    count: int = 1,
    interval_minutes: int = 60,
    scheduled: bool = False,
    settings: dict = None,
):
    """
    여러 키워드 배치 작성
    keywords: 지정 키워드 목록 (없으면 자동)
    scheduled: True면 interval_minutes 간격으로 예약 발행
    """
    settings = settings or {}

    # 키워드 준비
    if not keywords:
        keywords = get_fresh_keywords(count=count)
    if not keywords:
        keywords = [None] * count  # 자동 선택

    add_log(f"배치 시작: {len(keywords)}개, {'예약 ' + str(interval_minutes) + '분 간격' if scheduled else '즉시 발행'}")
    results = []

    for i, kw in enumerate(keywords):
        # 예약 시간 계산 (예약 모드)
        sched_at = None
        if scheduled:
            from datetime import timezone
            base = datetime.now() + timedelta(minutes=interval_minutes * (i + 1))
            sched_at = base.strftime("%Y-%m-%dT%H:%M:%S+09:00")

        result = run_single_post(keyword=kw, scheduled_at=sched_at, settings=settings)
        results.append(result)

        # 즉시 모드: 글 사이 30초 대기 (API 부하 방지)
        if not scheduled and i < len(keywords) - 1:
            add_log("다음 글 준비 중... 30초 대기")
            time.sleep(30)

    success = sum(1 for r in results if r["success"])
    add_log(f"배치 완료: 성공 {success}/{len(keywords)}")
    return results
