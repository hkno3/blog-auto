"""
자동 글쓰기 & 예약 업로드 스케줄러
"""
import time
from datetime import datetime, timedelta
from database.db import add_log, mark_keyword_used, add_post, update_post_status
from modules.keyword_fetcher import get_fresh_keywords
from modules.ai_writer import generate_post
from modules.image_fetcher import get_images, embed_images_in_content
from modules.sitemap_crawler import insert_external_links
from modules.blogger_uploader import publish_post


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

        add_log(f"=== 글쓰기 파이프라인 시작: {keyword} ===")

        # 2. AI 글쓰기
        style = settings.get("writing_style", "")
        post_data = generate_post(keyword, style=style)
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
