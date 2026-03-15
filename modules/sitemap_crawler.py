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

def _parse_xml(content: bytes):
    """BeautifulSoup XML 파싱 - 여러 파서 순차 시도"""
    for parser in ["lxml-xml", "xml", "lxml", "html.parser"]:
        try:
            return BeautifulSoup(content, parser)
        except Exception:
            continue
    return BeautifulSoup(content, "html.parser")


def _parse_sitemap_index(sitemap_url: str) -> list[str]:
    """sitemap_index.xml에서 하위 sitemap URL 추출"""
    try:
        resp = requests.get(sitemap_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = _parse_xml(resp.content)
        locs = [loc.get_text().strip() for loc in soup.find_all("loc") if loc.get_text().strip()]
        add_log(f"sitemap_index 파싱: {len(locs)}개 하위 sitemap ({sitemap_url})")
        return locs
    except Exception as e:
        add_log(f"sitemap_index 파싱 실패 ({sitemap_url}): {e}", "ERROR")
        return []


def _parse_sitemap(sitemap_url: str) -> list[dict]:
    """개별 sitemap.xml에서 URL + title 추출"""
    try:
        resp = requests.get(sitemap_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = _parse_xml(resp.content)
        entries = []
        for url_tag in soup.find_all("url"):
            loc = url_tag.find("loc")
            if not loc:
                continue
            url = loc.get_text().strip()
            if not url:
                continue
            # title 여러 태그명 시도
            title_tag = (url_tag.find("news:title") or url_tag.find("title")
                         or url_tag.find("image:title"))
            title = title_tag.get_text().strip() if title_tag else ""

            # title 없으면 URL에서 slug 추출
            if not title:
                slug = url.rstrip("/").split("/")[-1]
                title = slug.replace("-", " ").replace("_", " ").strip()

            entries.append({"url": url, "title": title, "description": ""})
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


def insert_external_links(content: str, keyword: str = "") -> str:
    """
    1) 본문 각 문단에 유사 외부 링크 삽입 (있을 때)
    2) 글 끝에 '함께 보면 좋은 글' 섹션 무조건 추가 (3개)
    """
    refresh_sitemap_cache()

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
    # 캐시 없어도 폴백 링크로 무조건 삽입
    footer_html = _build_related_section(related)
    footer_soup = BeautifulSoup(footer_html, "html.parser")
    soup.append(footer_soup)

    add_log(f"외부 링크 삽입: 인라인 {inline_count}개 + 하단 {len(related)}개")
    return str(soup)


def _get_related_links_for_footer(keyword: str, exclude_urls: set, count: int = 3) -> list[dict]:
    """하단 섹션용 링크 - 캐시에서 유사도 기준으로 선택, 캐시 없으면 강제 크롤링"""
    all_entries = []
    for site_info in TARGET_SITES:
        entries = _load_cache(site_info["name"])
        for e in entries:
            e["site"] = site_info["name"]
        all_entries += entries

    # 캐시 없으면 지금 바로 크롤링
    if not all_entries:
        add_log("sitemap 캐시 없음 - 즉시 크롤링 시작")
        refresh_sitemap_cache(force=True)
        for site_info in TARGET_SITES:
            entries = _load_cache(site_info["name"])
            for e in entries:
                e["site"] = site_info["name"]
            all_entries += entries

    # 그래도 없으면 빈 리스트 (섹션 빌더에서 처리)
    if not all_entries:
        add_log("sitemap 크롤링 실패 - 링크 없음", "WARN")
        return []

    # 유사도 점수 계산
    scored = []
    for e in all_entries:
        if e["url"] in exclude_urls or not e.get("title") or not e.get("url"):
            continue
        score = _similarity_score(keyword, e["title"])
        scored.append({**e, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)

    # 사이트별 균형있게 선택 (bodyandwell 1~2개 + bizachieve 1~2개)
    result = []
    sites_seen = {}
    for item in scored:
        site = item["site"]
        sites_seen[site] = sites_seen.get(site, 0)
        if sites_seen[site] < 2:
            result.append(item)
            sites_seen[site] += 1
        if len(result) >= count:
            break

    # 부족하면 점수 무관하게 채움
    if len(result) < count:
        for item in scored:
            if item not in result:
                result.append(item)
            if len(result) >= count:
                break

    return result[:count]


def _build_related_section(links: list[dict]) -> str:
    """함께 보면 좋은 글 HTML 섹션 생성 - 링크 없으면 각 사이트 최신 글 직접 크롤"""
    # 링크가 없으면 각 사이트에서 첫 번째 글 직접 가져오기
    if not links:
        links = _crawl_latest_from_each_site(count=3)

    if not links:
        add_log("외부 링크를 가져올 수 없음", "WARN")
        return ""

    items_html = ""
    for link in links:
        title = link.get("title") or "관련 글 보기"
        url = link.get("url", "")
        if not url:
            continue
        site = link.get("site", "")
        site_label = "BodyAndWell" if "bodyandwell" in site else "BizAchieve"
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


def _crawl_latest_from_each_site(count: int = 3) -> list[dict]:
    """각 사이트 sitemap에서 최신 글 직접 크롤링"""
    results = []
    per_site = max(1, count)

    for site_info in TARGET_SITES:
        try:
            sub_sitemaps = _parse_sitemap_index(site_info["sitemap"])
            if not sub_sitemaps:
                add_log(f"하위 sitemap 없음: {site_info['name']}", "WARN")
                continue

            # 여러 하위 sitemap 시도
            for sub_url in sub_sitemaps[:3]:
                entries = _parse_sitemap(sub_url)
                found = 0
                for e in entries:
                    if e.get("url") and e.get("title"):
                        results.append({**e, "site": site_info["name"]})
                        found += 1
                    if found >= per_site:
                        break
                if found > 0:
                    break  # 글 찾았으면 다음 사이트로

        except Exception as ex:
            add_log(f"직접 크롤링 실패 ({site_info['name']}): {ex}", "WARN")

    add_log(f"직접 크롤링 결과: {len(results)}개")
    return results[:count]
