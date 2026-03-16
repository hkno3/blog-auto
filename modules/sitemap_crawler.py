"""
외부 링크 삽입 모듈
- RSS Feed 파싱 (sitemap 대신 - 더 단순하고 최신 글 제공)
- 글 문단과 유사한 주제의 링크 자동 삽입
- 6시간 캐싱 + 상위 결과에서 랜덤 선택으로 다양성 확보
"""
import re
import random
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from database.db import get_conn, add_log

TARGET_SITES = [
    {
        "name": "bodyandwell",
        "feed": "https://bodyandwell.com/feed",
    },
    {
        "name": "bizachieve",
        "feed": "https://bizachieve.com/feed",
    },
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BlogAutoBot/1.0)"}
CACHE_HOURS = 6  # 6시간마다 갱신 (24시간→6시간으로 단축)


# ─── 캐시 ──────────────────────────────────────────────

def _is_cache_valid(site: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        """SELECT cached_at FROM sitemap_cache
           WHERE site=? ORDER BY cached_at DESC LIMIT 1""",
        (site,)
    ).fetchone()
    conn.close()
    if not row:
        return False
    cached_at = datetime.fromisoformat(row["cached_at"])
    return datetime.now() - cached_at < timedelta(hours=CACHE_HOURS)


def _save_cache(site: str, entries: list[dict]):
    conn = get_conn()
    conn.execute("DELETE FROM sitemap_cache WHERE site=?", (site,))
    for e in entries:
        conn.execute(
            "INSERT INTO sitemap_cache (site, url, title, description) VALUES (?, ?, ?, ?)",
            (site, e["url"], e.get("title", ""), e.get("description", ""))
        )
    conn.commit()
    conn.close()


def _load_cache(site: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT url, title, description FROM sitemap_cache WHERE site=?", (site,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── RSS Feed 파싱 ──────────────────────────────────────

def _fetch_feed(feed_url: str) -> list[dict]:
    """RSS feed에서 글 목록 파싱"""
    try:
        resp = requests.get(feed_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")

        # xml 파서 실패 시 lxml로 재시도
        if not soup.find("item"):
            soup = BeautifulSoup(resp.content, "lxml")

        entries = []
        for item in soup.find_all("item"):
            title_tag = item.find("title")
            link_tag = item.find("link")
            desc_tag = item.find("description")

            title = title_tag.get_text(strip=True) if title_tag else ""
            # <link> 태그가 비어있을 경우 next_sibling으로 URL 추출
            if link_tag:
                url = link_tag.get_text(strip=True) or (link_tag.next_sibling or "").strip()
            else:
                url = ""
            description = ""
            if desc_tag:
                desc_text = BeautifulSoup(desc_tag.get_text(), "html.parser").get_text()
                description = desc_text[:200].strip()

            if url and title and len(title) > 4:
                entries.append({"url": url, "title": title, "description": description})

        return entries
    except Exception as e:
        add_log(f"Feed 파싱 실패 ({feed_url}): {e}", "WARN")
        return []


def refresh_feed_cache(force: bool = False):
    """전체 사이트 feed 캐시 갱신"""
    for site_info in TARGET_SITES:
        name = site_info["name"]
        if not force and _is_cache_valid(name):
            add_log(f"feed 캐시 유효 - 스킵: {name}")
            continue

        add_log(f"feed 크롤링 시작: {name}")
        entries = _fetch_feed(site_info["feed"])
        if entries:
            _save_cache(name, entries)
            add_log(f"feed 캐시 저장: {name} ({len(entries)}개)")
        else:
            add_log(f"feed 데이터 없음: {name}", "WARN")


# ─── 유사도 & 링크 삽입 ────────────────────────────────

def _similarity_score(text1: str, text2: str) -> float:
    """간단한 키워드 겹침 유사도 (0~1)"""
    t1 = set(re.findall(r"[가-힣a-zA-Z]{2,}", text1.lower()))
    t2 = set(re.findall(r"[가-힣a-zA-Z]{2,}", text2.lower()))
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / max(len(t1), len(t2))


def find_related_links(paragraph: str, top_n: int = 2) -> list[dict]:
    """문단 내용과 유사한 외부 링크 찾기"""
    all_entries = []
    for site_info in TARGET_SITES:
        entries = _load_cache(site_info["name"])
        for e in entries:
            e["site"] = site_info["name"]
        all_entries += entries

    scored = []
    for e in all_entries:
        search_text = f"{e['title']} {e.get('description', '')}"
        score = _similarity_score(paragraph, search_text)
        if score > 0.05:
            scored.append({**e, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def insert_external_links(content: str, keyword: str = "") -> str:
    """
    1) 본문 각 문단에 유사 외부 링크 삽입 (있을 때)
    2) 글 끝에 '함께 보면 좋은 글' 섹션 무조건 추가 (3개)
    """
    refresh_feed_cache()  # 캐시 만료 시에만 갱신

    soup = BeautifulSoup(content, "html.parser")

    # ── 문단별 인라인 링크 ────────────────────────────
    used_urls = set()
    inline_count = 0
    for p in soup.find_all("p"):
        text = p.get_text()
        if len(text) < 50:
            continue
        links = find_related_links(text, top_n=2)
        for link in links:
            if link["url"] in used_urls or link["score"] < 0.08:
                continue
            link_tag = soup.new_tag(
                "a", href=link["url"], target="_blank", rel="noopener noreferrer",
                style="color:#1a73e8;text-decoration:underline;"
            )
            link_tag.string = f" → {link['title'] or '관련 글 보기'}"
            p.append(link_tag)
            used_urls.add(link["url"])
            inline_count += 1
            break

    # ── 글 끝 '함께 보면 좋은 글' 무조건 추가 ──────────
    related = _get_related_links_for_footer(keyword, used_urls, count=3)
    footer_html = _build_related_section(related)
    footer_soup = BeautifulSoup(footer_html, "html.parser")
    soup.append(footer_soup)

    add_log(f"외부 링크 삽입: 인라인 {inline_count}개 + 하단 {len(related)}개")
    return str(soup)


def _get_related_links_for_footer(keyword: str, exclude_urls: set, count: int = 3) -> list[dict]:
    """하단 섹션용 링크 - 유사도 상위에서 랜덤 선택으로 다양성 확보"""
    all_entries = []
    for site_info in TARGET_SITES:
        entries = _load_cache(site_info["name"])
        for e in entries:
            e["site"] = site_info["name"]
        all_entries += entries

    # 캐시 없으면 즉시 크롤링
    if not all_entries:
        add_log("feed 캐시 없음 - 즉시 크롤링")
        refresh_feed_cache(force=True)
        for site_info in TARGET_SITES:
            entries = _load_cache(site_info["name"])
            for e in entries:
                e["site"] = site_info["name"]
            all_entries += entries

    if not all_entries:
        add_log("feed 크롤링 실패 - 링크 없음", "WARN")
        return []

    # 유사도 점수 계산
    scored = []
    for e in all_entries:
        if e["url"] in exclude_urls or not e.get("title") or not e.get("url"):
            continue
        score = _similarity_score(keyword, e["title"])
        scored.append({**e, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)

    # 상위 10개 중 랜덤 선택 (매번 다른 링크 노출)
    pool = scored[:10]
    if len(pool) <= count:
        candidates = pool
    else:
        # 사이트별 균형: bodyandwell/bizachieve 각각 풀 분리 후 랜덤
        pool_by_site = {}
        for item in pool:
            site = item["site"]
            pool_by_site.setdefault(site, []).append(item)

        candidates = []
        site_names = list(pool_by_site.keys())
        random.shuffle(site_names)
        for site in site_names:
            site_pool = pool_by_site[site]
            pick = random.choice(site_pool)
            candidates.append(pick)
            if len(candidates) >= count:
                break

        # 부족하면 나머지에서 보충
        if len(candidates) < count:
            remaining = [x for x in pool if x not in candidates]
            random.shuffle(remaining)
            candidates += remaining[:count - len(candidates)]

    return candidates[:count]


def _build_related_section(links: list[dict]) -> str:
    """함께 보면 좋은 글 HTML 섹션 생성"""
    if not links:
        add_log("외부 링크를 가져올 수 없음", "WARN")
        return ""

    items_html = ""
    for link in links:
        title = link.get("title") or "관련 글 보기"
        url = link.get("url", "")
        if not url:
            continue
        items_html += f"""
        <li style="margin-bottom:8px;">
          <a href="{url}" target="_blank" rel="noopener noreferrer"
             style="color:#1a73e8;text-decoration:none;font-weight:500;">
            📌 {title}
          </a>
        </li>"""

    if not items_html:
        return ""

    return f"""
<div style="margin-top:40px;padding:20px;background:#f8fafc;border-left:4px solid #4f46e5;border-radius:8px;">
  <h3 style="margin:0 0 12px;font-size:1.1em;color:#1e293b;">📚 함께 보면 좋은 글</h3>
  <ul style="list-style:none;padding:0;margin:0;">
    {items_html}
  </ul>
</div>"""


# 하위 호환성 유지
def refresh_sitemap_cache(force: bool = False):
    refresh_feed_cache(force=force)
