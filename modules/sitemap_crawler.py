"""
외부 링크 삽입 모듈
- Google Sheets API v4로 사이트맵 URL 가져오기
- 글 문단과 유사한 주제의 링크 자동 삽입
- 6시간 캐싱 + 상위 결과에서 랜덤 선택으로 다양성 확보
"""
import re
import random
import requests
from urllib.parse import unquote
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from config import get_api_key
from database.db import get_conn, add_log

# ─── 대상 사이트 및 Google Sheets 설정 ───────────────────
TARGET_SITES = [
    {
        "name": "bizachieve",
        "sheets": [
            "1F5OMpIyI1ZM8V39Zt4-ls_TzBqvWr0N5Tim_td_KwxA",  # postsitemap1
        ],
    },
    {
        "name": "bodyandwell",
        "sheets": [
            "1tULUyDltaH_uw7yNFGNkH3FXUigLWGxZnrj6tcgw5ZQ",  # postsitemap1
        ],
    },
    {
        "name": "cointrail",
        "sheets": [
            "1pUdL05UghiNeTSmgXKa8w25zLKUeKeTE0T4fFHinJNE",  # postsitemap
        ],
    },
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BlogAutoBot/1.0)"}
CACHE_HOURS = 6  # 6시간마다 갱신

SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


# ─── Google Sheets API v4 헬퍼 ─────────────────────────

def _sheet_api_url(sheet_id: str) -> str:
    """Google Sheets API v4 URL (컬럼 A 전체)"""
    api_key = get_api_key("google_sheets")
    return f"{SHEETS_API_BASE}/{sheet_id}/values/A:A?key={api_key}"


def _slug_to_title(url: str) -> str:
    """URL 슬러그에서 의사 제목 추출 (예: /weight-loss-tips → weight loss tips)"""
    try:
        path = url.rstrip("/").split("/")[-1]
        path = path.split("?")[0].split("#")[0]  # 쿼리스트링/앵커 제거
        path = unquote(path)                      # URL 인코딩 디코딩 (%eb%af... → 한글)
        path = re.sub(r"\.\w+$", "", path)        # 확장자 제거
        title = re.sub(r"[-_]+", " ", path).strip()
        return title if len(title) > 2 else ""
    except Exception:
        return ""


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


# ─── Google Sheets API v4 파싱 ─────────────────────────

def _fetch_gsheet(sheet_id: str) -> list[dict]:
    """Google Sheets API v4로 URL 목록 파싱"""
    api_key = get_api_key("google_sheets")
    if not api_key:
        add_log("Google Sheets API 키 없음 - 설정 화면에서 입력해주세요", "WARN")
        return []

    url = _sheet_api_url(sheet_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        entries = []
        for row in data.get("values", []):
            if not row:
                continue
            cell = row[0].strip()
            if not cell.startswith("http"):
                continue  # 헤더 행 또는 비URL 스킵
            title = _slug_to_title(cell)
            entries.append({"url": cell, "title": title, "description": ""})

        return entries
    except Exception as e:
        add_log(f"Google Sheets API 파싱 실패 ({sheet_id[:8]}...): {e}", "WARN")
        return []


def refresh_feed_cache(force: bool = False):
    """전체 사이트 Google Sheets 캐시 갱신"""
    for site_info in TARGET_SITES:
        name = site_info["name"]
        if not force and _is_cache_valid(name):
            add_log(f"캐시 유효 - 스킵: {name}")
            continue

        add_log(f"Google Sheets 크롤링 시작: {name}")
        all_entries = []
        for sheet_id in site_info["sheets"]:
            entries = _fetch_gsheet(sheet_id)
            all_entries.extend(entries)
            add_log(f"  시트 {sheet_id[:8]}... → {len(entries)}개")

        if all_entries:
            _save_cache(name, all_entries)
            add_log(f"캐시 저장: {name} (총 {len(all_entries)}개)")
        else:
            add_log(f"데이터 없음: {name}", "WARN")


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

    # ── 문단 뒤 별도 링크 문단 삽입 ─────────────────────
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
            title = link["title"] or "관련 글 보기"
            link_p = BeautifulSoup(
                f'<p><a href="{link["url"]}" target="_blank" rel="noopener noreferrer"'
                f' style="color:#1a73e8;text-decoration:underline;">{title}</a></p>',
                "html.parser"
            )
            p.insert_after(link_p)
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
        add_log("캐시 없음 - 즉시 크롤링")
        refresh_feed_cache(force=True)
        for site_info in TARGET_SITES:
            entries = _load_cache(site_info["name"])
            for e in entries:
                e["site"] = site_info["name"]
            all_entries += entries

    if not all_entries:
        add_log("크롤링 실패 - 링크 없음", "WARN")
        return []

    # 유사도 점수 계산
    scored = []
    for e in all_entries:
        if e["url"] in exclude_urls or not e.get("url"):
            continue
        score = _similarity_score(keyword, e.get("title", ""))
        scored.append({**e, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)

    # 상위 10개 중 랜덤 선택 (매번 다른 링크 노출)
    pool = scored[:10]
    if len(pool) <= count:
        candidates = pool
    else:
        # 사이트별 균형: 각 사이트 풀 분리 후 랜덤
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
