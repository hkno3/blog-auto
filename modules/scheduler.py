"""
자동 글쓰기 & 예약 업로드 스케줄러
"""
import time
from datetime import datetime, timedelta
from config import get_setting
from database.db import add_log, mark_keyword_used, add_post, update_post_status
from modules.keyword_fetcher import get_fresh_keywords
from modules.ai_writer import generate_post
from modules.image_fetcher import get_images, embed_images_in_content
from modules.sitemap_crawler import insert_external_links
from modules.blogger_uploader import publish_post


def run_single_post(keyword: str = None, scheduled_at: str = None) -> dict:
    """
    단일 글 작성 및 업로드 파이프라인
    keyword가 None이면 자동 키워드 선택
    반환: {success, post_id, title, url, error}
    """
    try:
        # 1. 키워드 선택
        if not keyword:
            keywords = get_fresh_keywords(count=1, source=get_setting("keyword_source") or "google")
            if not keywords:
                return {"success": False, "error": "사용 가능한 키워드 없음"}
            keyword = keywords[0]

        add_log(f"=== 글쓰기 파이프라인 시작: {keyword} ===")

        # 2. AI 글쓰기
        post_data = generate_post(keyword)
        post_id = add_post(keyword, post_data["title"], scheduled_at)

        # 3. 이미지 삽입
        image_count = get_setting("image_count") or 5
        images = get_images(keyword, image_count)
        content_with_images = embed_images_in_content(post_data["content"], images)

        # 4. 외부 링크 삽입
        final_content = insert_external_links(content_with_images)

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


def run_batch(count: int = None, interval_minutes: int = None, scheduled_start: str = None):
    """
    여러 개 글 배치 작성
    count: 작성할 글 수
    interval_minutes: 글 간격 (분)
    scheduled_start: 첫 발행 시간 (ISO 형식)
    """
    count = count or get_setting("batch_count") or 3
    interval = interval_minutes or get_setting("post_interval_minutes") or 60

    add_log(f"배치 시작: {count}개, {interval}분 간격")
    results = []

    for i in range(count):
        # 예약 시간 계산
        sched_at = None
        if scheduled_start:
            from dateutil.parser import parse as parse_dt
            base = parse_dt(scheduled_start)
            sched_at = (base + timedelta(minutes=interval * i)).isoformat()

        result = run_single_post(scheduled_at=sched_at)
        results.append(result)

        if i < count - 1:
            if not scheduled_start:
                # 즉시 발행 모드: API 부하 방지 대기
                wait = min(interval * 60, 30)
                add_log(f"다음 글 대기 중... {wait}초")
                time.sleep(wait)

    success = sum(1 for r in results if r["success"])
    add_log(f"배치 완료: 성공 {success}/{count}")
    return results
