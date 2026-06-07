"""
유튜브 리서치 모듈
- 키워드로 쇼츠/롱폼 영상 검색 (조회수순 정렬)
- 영상 제목 추출
- 자막(대본) 추출
"""
import requests
from config import get_api_key
from database.db import add_log

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
SHORTS_MAX_SECONDS = 60

# 국가별 인기 영상 탭 - 키: (region 표시명, YouTube regionCode 목록)
TRENDING_REGIONS = {
    "한국": ["KR"],
    "일본": ["JP"],
    "중국": ["CN"],
    "미국": ["US"],
    "영국": ["GB"],
    "인도": ["IN"],
    "베트남": ["VN"],
    "동남아": ["TH", "ID"],
}


def _parse_duration_seconds(duration: str) -> int:
    """ISO 8601 duration (예: PT1M30S) -> 초 단위 정수"""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not m:
        return 0
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def _format_duration(seconds: int) -> str:
    if seconds >= 3600:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def _video_item(item: dict) -> dict:
    duration_seconds = _parse_duration_seconds(item.get("contentDetails", {}).get("duration", ""))
    v_type = "shorts" if duration_seconds <= SHORTS_MAX_SECONDS else "long"
    video_id = item["id"]
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    return {
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "channel": snippet.get("channelTitle", ""),
        "view_count": int(stats.get("viewCount", 0)),
        "duration_seconds": duration_seconds,
        "duration_label": _format_duration(duration_seconds),
        "video_type": v_type,
        "link": f"https://www.youtube.com/watch?v={video_id}",
        "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
    }


def search_videos(keyword: str, video_type: str = "all", max_results: int = 25) -> list[dict]:
    """
    키워드로 유튜브 영상 검색 후 조회수 내림차순 정렬
    video_type: "all" | "shorts" | "long"
    반환: [{video_id, title, channel, view_count, duration_seconds, duration_label,
            video_type, link, thumbnail}]
    """
    api_key = get_api_key("youtube")
    if not api_key:
        raise ValueError("유튜브 API 키가 설정되지 않았습니다.")
    if not keyword:
        return []

    try:
        search_resp = requests.get(
            SEARCH_URL,
            params={
                "key": api_key,
                "q": keyword,
                "part": "snippet",
                "type": "video",
                "maxResults": min(max_results, 50),
                "order": "viewCount",
            },
            timeout=10,
        )
        search_resp.raise_for_status()
        items = search_resp.json().get("items", [])
        video_ids = [item["id"]["videoId"] for item in items if item.get("id", {}).get("videoId")]
        if not video_ids:
            return []

        videos_resp = requests.get(
            VIDEOS_URL,
            params={
                "key": api_key,
                "id": ",".join(video_ids),
                "part": "snippet,statistics,contentDetails",
            },
            timeout=10,
        )
        videos_resp.raise_for_status()
        results = []
        for item in videos_resp.json().get("items", []):
            video = _video_item(item)
            if video_type in ("shorts", "long") and video["video_type"] != video_type:
                continue
            results.append(video)

        results.sort(key=lambda v: v["view_count"], reverse=True)
        return results

    except Exception as e:
        add_log(f"유튜브 검색 오류: {e}", "ERROR")
        raise


def get_trending_videos(region: str, video_type: str = "all", max_results: int = 25) -> list[dict]:
    """
    국가별 인기 급상승 영상 조회 (현재 조회수 많은 = 사람들이 많이 찾는 주제 발굴용)
    region: TRENDING_REGIONS의 키 (예: "한국", "동남아")
    """
    api_key = get_api_key("youtube")
    if not api_key:
        raise ValueError("유튜브 API 키가 설정되지 않았습니다.")

    region_codes = TRENDING_REGIONS.get(region)
    if not region_codes:
        raise ValueError(f"지원하지 않는 지역입니다: {region}")

    try:
        seen_ids = set()
        results = []
        for code in region_codes:
            resp = requests.get(
                VIDEOS_URL,
                params={
                    "key": api_key,
                    "chart": "mostPopular",
                    "regionCode": code,
                    "part": "snippet,statistics,contentDetails",
                    "maxResults": min(max_results, 50),
                },
                timeout=10,
            )
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                video = _video_item(item)
                if video["video_id"] in seen_ids:
                    continue
                if video_type in ("shorts", "long") and video["video_type"] != video_type:
                    continue
                seen_ids.add(video["video_id"])
                results.append(video)

        results.sort(key=lambda v: v["view_count"], reverse=True)
        return results[:max_results]

    except Exception as e:
        add_log(f"유튜브 인기 영상 조회 오류 ({region}): {e}", "ERROR")
        raise


def get_transcript(video_id: str) -> str:
    """영상 자막(대본) 텍스트 추출 (한국어 우선, 없으면 자동생성/영어 순으로 fallback)"""
    from youtube_transcript_api import YouTubeTranscriptApi

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None
        for lang in ("ko", "en"):
            try:
                transcript = transcript_list.find_transcript([lang])
                break
            except Exception:
                continue
        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(["ko", "en"])
            except Exception:
                transcript = next(iter(transcript_list))

        entries = transcript.fetch()
        return " ".join(entry["text"].strip() for entry in entries if entry.get("text", "").strip())

    except Exception as e:
        add_log(f"유튜브 대본 추출 오류 ({video_id}): {e}", "ERROR")
        raise
