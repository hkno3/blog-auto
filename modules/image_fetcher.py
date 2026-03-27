"""
이미지 검색 모듈
- Unsplash API (무료)
- Pexels API (무료) - Unsplash 한도 초과 시 자동 전환
- Pixabay API (무료) - Unsplash/Pexels 한도 초과 시 자동 전환
"""
import requests
from config import get_api_key
from database.db import add_log


UNSPLASH_API = "https://api.unsplash.com/search/photos"
PEXELS_API = "https://api.pexels.com/v1/search"
PIXABAY_API = "https://pixabay.com/api/"


def _fetch_unsplash(query: str, count: int = 5) -> list[dict]:
    api_key = get_api_key("unsplash")
    if not api_key:
        return []
    try:
        resp = requests.get(
            UNSPLASH_API,
            params={"query": query, "per_page": count, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        images = []
        for item in data.get("results", []):
            images.append({
                "url": item["urls"]["regular"],
                "thumb": item["urls"]["small"],
                "alt": item.get("alt_description") or query,
                "source": "Unsplash",
                "photographer": item["user"]["name"],
                "photographer_url": item["user"]["links"]["html"],
            })
        return images
    except Exception as e:
        add_log(f"Unsplash 이미지 검색 실패: {e}", "WARN")
        return []


def _fetch_pexels(query: str, count: int = 5) -> list[dict]:
    api_key = get_api_key("pexels")
    if not api_key:
        return []
    try:
        resp = requests.get(
            PEXELS_API,
            params={"query": query, "per_page": count, "orientation": "landscape"},
            headers={"Authorization": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        images = []
        for item in data.get("photos", []):
            images.append({
                "url": item["src"]["large"],
                "thumb": item["src"]["medium"],
                "alt": item.get("alt") or query,
                "source": "Pexels",
                "photographer": item["photographer"],
                "photographer_url": item["photographer_url"],
            })
        return images
    except Exception as e:
        add_log(f"Pexels 이미지 검색 실패: {e}", "WARN")
        return []


def _fetch_pixabay(query: str, count: int = 5) -> list[dict]:
    api_key = get_api_key("pixabay")
    if not api_key:
        return []
    try:
        resp = requests.get(
            PIXABAY_API,
            params={
                "key": api_key,
                "q": query,
                "per_page": count,
                "image_type": "photo",
                "orientation": "horizontal",
                "safesearch": "true",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        images = []
        for item in data.get("hits", []):
            images.append({
                "url": item["largeImageURL"],
                "thumb": item["webformatURL"],
                "alt": item.get("tags", query).split(",")[0].strip() or query,
                "source": "Pixabay",
                "photographer": item.get("user", "Unknown"),
                "photographer_url": f"https://pixabay.com/users/{item.get('user', '')}-{item.get('user_id', '')}",
            })
        return images
    except Exception as e:
        add_log(f"Pixabay 이미지 검색 실패: {e}", "WARN")
        return []


def get_images(keyword: str, count: int = 5) -> list[dict]:
    """
    키워드로 이미지 검색 (Pexels 우선, 부족하면 Pixabay, Unsplash 보완)
    """
    images = _fetch_pexels(keyword, count)
    add_log(f"Pexels에서 {len(images)}개 이미지 수집")

    if len(images) < count:
        needed = count - len(images)
        pixabay_images = _fetch_pixabay(keyword, needed)
        images += pixabay_images
        add_log(f"Pixabay에서 {len(pixabay_images)}개 이미지 추가")

    if len(images) < count:
        needed = count - len(images)
        unsplash_images = _fetch_unsplash(keyword, needed)
        images += unsplash_images
        add_log(f"Unsplash에서 {len(unsplash_images)}개 이미지 추가")

    if not images:
        add_log(f"이미지 없음 - API 키 확인 필요 ({keyword})", "WARN")

    return images[:count]


def embed_images_in_content(content: str, images: list[dict]) -> str:
    """
    HTML 본문에 이미지를 균등하게 삽입
    H2 태그 뒤에 이미지 삽입
    """
    if not images:
        return content

    import re
    h2_pattern = re.compile(r"(<h2[^>]*>.*?</h2>)", re.IGNORECASE | re.DOTALL)
    parts = h2_pattern.split(content)

    img_index = 0
    result_parts = []
    for part in parts:
        result_parts.append(part)
        if h2_pattern.match(part) and img_index < len(images):
            img = images[img_index]
            img_html = (
                f'<figure style="text-align:center;margin:20px 0;">'
                f'<img src="{img["url"]}" alt="{img["alt"]}" '
                f'style="max-width:100%;height:auto;border-radius:8px;" loading="lazy"/>'
                f'<figcaption style="font-size:0.85em;color:#666;">'
                f'Photo by <a href="{img["photographer_url"]}" target="_blank">'
                f'{img["photographer"]}</a> on {img["source"]}'
                f'</figcaption></figure>\n'
            )
            result_parts.append(img_html)
            img_index += 1

    return "".join(result_parts)
