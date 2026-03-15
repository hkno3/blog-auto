"""
Sitemap 크롤링 및 외부 링크 삽입 모듈
- bodyandwell.com / bizachieve.com sitemap 파싱
- 글 문단과 유사한 주제의 링크 자동 삽입
- 하루 1회 캐싱
"""
import re
import sqlite3
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from database.db import get_conn, add_log

TARGET_SITES = [
    {
        "name": "bodyandwell",
        "sitemap": "https://bodyandwell.com/sitemap_index.xml",
    },
    {
        "name": "bizachieve",
        "sitemap": "https://bizachieve.com/sitemap_index.xml",
    },
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BlogAutoBot/1.0)"}


# ─── 캐시 ──────────────────────────────────────────────

def _is_cache_valid(site: str, max_age_hours: int = 24) -> bool:
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
    return datetime.now() - cached_at < timedelta(hours=max_age_hours)


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


# ─── 파싱 ──────────────────────────────────────────────

def _parse_sitemap_index(sitemap_url: str) -> list[str]:
    """sitemap_index.xml에서 하위 sitemap URL 추출"""
    try:
        resp = requests.get(sitemap_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "lxml-xml")
        locs = [loc.text.strip() for loc in soup.find_all("loc")]
        return locs
    except Exception as e:
        add_log(f"sitemap_index 파싱 실패 ({sitemap_url}): {e}", "ERROR")
        return []


def _parse_sitemap(sitemap_url: str) -> list[dict]:
    """개별 sitemap.xml에서 URL + title 추출"""
    try:
        resp = requests.get(sitemap_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "lxml-xml")
        entries = []
        for url_tag in soup.find_all("url"):
            loc = url_tag.find("loc")
            title_tag = url_tag.find("news:title") or url_tag.find("title")
            if loc:
                entries.append({
                    "url": loc.text.strip(),
                    "title": title_tag.text.strip() if title_tag else "",
                    "description": "",
                })
        return entries
    except Exception as e:
        add_log(f"sitemap 파싱 실패 ({sitemap_url}): {e}", "WARN")
        return []


def refresh_sitemap_cache(force: bool = False):
    """전체 사이트 sitemap 캐시 갱신"""
    for site_info in TARGET_SITES:
        name = site_info["name"]
        if not force and _is_cache_valid(name):
            add_log(f"sitemap 캐시 유효 - 스킵: {name}")
            continue

        add_log(f"sitemap 크롤링 시작: {name}")
        sub_sitemaps = _parse_sitemap_index(site_info["sitemap"])

        all_entries = []
        for sub_url in sub_sitemaps[:10]:  # 최대 10개 하위 sitemap
            entries = _parse_sitemap(sub_url)
            all_entries += entries

        _save_cache(name, all_entries)
        add_log(f"sitemap 캐시 저장 완료: {name} ({len(all_entries)}개)")


# ─── 유사도 & 링크 삽입 ────────────────────────────────

def _similarity_score(text1: str, text2: str) -> float:
    """간단한 키워드 겹침 유사도 (0~1)"""
    t1 = set(re.findall(r"[가-힣a-zA-Z]{2,}", text1.lower()))
    t2 = set(re.findall(r"[가-힣a-zA-Z]{2,}", text2.lower()))
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / max(len(t1), len(t2))


def find_related_links(paragraph: str, top_n: int = 2) -> list[dict]:
    """
    문단 내용과 유사한 외부 링크 찾기
    반환: [{url, title, site, score}]
    """
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


def insert_external_links(content: str, min_score: float = 0.08) -> str:
    """
    HTML 본문의 각 <p> 문단에 유사 외부 링크 삽입
    """
    refresh_sitemap_cache()

    soup = BeautifulSoup(content, "html.parser")
    paragraphs = soup.find_all("p")

    used_urls = set()
    insert_count = 0

    for p in paragraphs:
        text = p.get_text()
        if len(text) < 50:
            continue

        links = find_related_links(text, top_n=2)
        for link in links:
            if link["url"] in used_urls or link["score"] < min_score:
                continue
            # 문단 끝에 관련 링크 추가
            link_tag = soup.new_tag(
                "a", href=link["url"], target="_blank", rel="noopener noreferrer",
                style="color:#1a73e8;text-decoration:underline;"
            )
            link_tag.string = f" → {link['title'] or '관련 글 보기'}"
            p.append(link_tag)
            used_urls.add(link["url"])
            insert_count += 1
            break  # 문단당 최대 1개

    add_log(f"외부 링크 {insert_count}개 삽입 완료")
    return str(soup)
