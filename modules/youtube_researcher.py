"""
유튜브 리서치 모듈
- 키워드로 쇼츠/롱폼 영상 검색 (조회수순 정렬)
- 영상 제목 추출
- 자막(대본) 추출
"""
from datetime import datetime, timedelta, timezone

import requests
from config import get_api_key
from database.db import add_log

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
SHORTS_MAX_SECONDS = 60

# 업로드 기간 필터 - 키: 검색 시점 기준 거슬러 올라갈 기간
PERIOD_DELTAS = {
    "24h": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}

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

# YouTube videoCategoryId 기준 음악/엔터테인먼트 계열 (블로그 키워드 발굴 시 노이즈가 되는 경우가 많음)
MUSIC_ENTERTAINMENT_CATEGORY_IDS = {"10", "24"}  # 10=Music, 24=Entertainment


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
        "category_id": snippet.get("categoryId", ""),
        "published_at": snippet.get("publishedAt", ""),
        "view_count": int(stats.get("viewCount", 0)),
        "duration_seconds": duration_seconds,
        "duration_label": _format_duration(duration_seconds),
        "video_type": v_type,
        "link": f"https://www.youtube.com/watch?v={video_id}",
        "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
        # YouTube가 보고하는 자막 보유 여부 (참고용 - 100% 정확하지 않을 수 있음)
        "has_captions": item.get("contentDetails", {}).get("caption") == "true",
    }


def _period_cutoff(period: str):
    """period 키 -> UTC 기준 cutoff datetime (없거나 'all'이면 None)"""
    delta = PERIOD_DELTAS.get(period)
    if not delta:
        return None
    return datetime.now(timezone.utc) - delta


def _filter_and_sort(videos: list[dict], period: str = "all", min_views: int = 0,
                     captions_only: bool = False, exclude_music: bool = False,
                     sort: str = "views") -> list[dict]:
    cutoff = _period_cutoff(period)
    filtered = []
    for v in videos:
        if min_views and v["view_count"] < min_views:
            continue
        if captions_only and not v.get("has_captions"):
            continue
        if exclude_music and v.get("category_id") in MUSIC_ENTERTAINMENT_CATEGORY_IDS:
            continue
        if cutoff is not None:
            try:
                published = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
            except Exception:
                published = None
            if published is None or published < cutoff:
                continue
        filtered.append(v)

    if sort == "recent":
        filtered.sort(key=lambda v: v.get("published_at", ""), reverse=True)
    else:
        filtered.sort(key=lambda v: v["view_count"], reverse=True)
    return filtered


def search_videos(keyword: str, video_type: str = "all", period: str = "all", min_views: int = 0,
                  captions_only: bool = False, exclude_music: bool = False, sort: str = "views",
                  page_token: str = None) -> dict:
    """
    키워드로 유튜브 영상 검색 (페이지당 최대 ~50개, 무한 스크롤용 page_token 지원)
    video_type: "all" | "shorts" | "long"
    반환: {"videos": [...], "next_page_token": str|None}
    """
    api_key = get_api_key("youtube")
    if not api_key:
        raise ValueError("유튜브 API 키가 설정되지 않았습니다.")
    if not keyword:
        return {"videos": [], "next_page_token": None}

    try:
        # order=viewCount는 YouTube API 특성상 후보군이 매우 좁아 결과가 몇 개 안 나오는 경우가 많음.
        # relevance(기본값)로 넓게 가져온 뒤 실제 조회수로 재정렬한다.
        search_params = {
            "key": api_key,
            "q": keyword,
            "part": "snippet",
            "type": "video",
            "maxResults": 50,
        }
        cutoff = _period_cutoff(period)
        if cutoff is not None:
            search_params["publishedAfter"] = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        if page_token:
            search_params["pageToken"] = page_token

        search_resp = requests.get(SEARCH_URL, params=search_params, timeout=10)
        search_resp.raise_for_status()
        search_data = search_resp.json()
        next_page_token = search_data.get("nextPageToken")
        items = search_data.get("items", [])
        video_ids = [item["id"]["videoId"] for item in items if item.get("id", {}).get("videoId")]
        if not video_ids:
            return {"videos": [], "next_page_token": next_page_token}

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

        # publishedAfter는 search.list에서 이미 적용했으므로 period는 다시 거르지 않음
        results = _filter_and_sort(results, period="all", min_views=min_views,
                                   captions_only=captions_only, exclude_music=exclude_music, sort=sort)
        return {"videos": results, "next_page_token": next_page_token}

    except Exception as e:
        add_log(f"유튜브 검색 오류: {e}", "ERROR")
        raise


def get_trending_videos(region: str, video_type: str = "all", period: str = "all", min_views: int = 0,
                        captions_only: bool = False, exclude_music: bool = False, sort: str = "views",
                        page_token: str = None) -> dict:
    """
    국가별 인기 급상승 영상 조회 (현재 조회수 많은 = 사람들이 많이 찾는 주제 발굴용)
    region: TRENDING_REGIONS의 키 (예: "한국", "동남아")
    chart=mostPopular는 publishedAfter를 지원하지 않아 period는 결과를 받은 뒤 직접 거른다.
    여러 지역코드를 합치는 region(예: 동남아)은 페이지네이션을 지원하지 않음(첫 페이지만 반환).
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
        next_page_token = None
        multi_region = len(region_codes) > 1

        for code in region_codes:
            params = {
                "key": api_key,
                "chart": "mostPopular",
                "regionCode": code,
                "part": "snippet,statistics,contentDetails",
                "maxResults": 50,
            }
            # 합산 지역(예: 동남아)은 페이지네이션을 지원하지 않고 첫 페이지만 사용
            if not multi_region and page_token:
                params["pageToken"] = page_token

            resp = requests.get(VIDEOS_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if not multi_region:
                next_page_token = data.get("nextPageToken")
            for item in data.get("items", []):
                video = _video_item(item)
                if video["video_id"] in seen_ids:
                    continue
                if video_type in ("shorts", "long") and video["video_type"] != video_type:
                    continue
                seen_ids.add(video["video_id"])
                results.append(video)

        results = _filter_and_sort(results, period=period, min_views=min_views,
                                   captions_only=captions_only, exclude_music=exclude_music, sort=sort)
        return {"videos": results, "next_page_token": next_page_token}

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
