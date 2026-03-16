import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "blog_auto.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # 발행된 글 기록
    c.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            title TEXT,
            blogger_post_id TEXT,
            status TEXT DEFAULT 'pending',
            scheduled_at TEXT,
            published_at TEXT,
            error_message TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 사용된 키워드 중복 방지
    c.execute("""
        CREATE TABLE IF NOT EXISTS used_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT UNIQUE NOT NULL,
            used_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # sitemap 캐시
    c.execute("""
        CREATE TABLE IF NOT EXISTS sitemap_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            description TEXT,
            cached_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 실행 로그
    c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT DEFAULT 'INFO',
            message TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # Gemini API 사용량 추적
    c.execute("""
        CREATE TABLE IF NOT EXISTS gemini_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            request_count INTEGER DEFAULT 0,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            UNIQUE(date)
        )
    """)

    conn.commit()
    conn.close()


def add_log(message: str, level: str = "INFO"):
    conn = get_conn()
    conn.execute(
        "INSERT INTO logs (level, message) VALUES (?, ?)",
        (level, message)
    )
    conn.commit()
    conn.close()


def is_keyword_used(keyword: str, days: int = 30) -> bool:
    conn = get_conn()
    row = conn.execute(
        """SELECT id FROM used_keywords
           WHERE keyword = ?
           AND used_at > datetime('now', ?, 'localtime')""",
        (keyword, f"-{days} days")
    ).fetchone()
    conn.close()
    return row is not None


def mark_keyword_used(keyword: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO used_keywords (keyword, used_at) VALUES (?, datetime('now', 'localtime'))",
        (keyword,)
    )
    conn.commit()
    conn.close()


def add_post(keyword: str, title: str, scheduled_at: str = None) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO posts (keyword, title, scheduled_at, status) VALUES (?, ?, ?, ?)",
        (keyword, title, scheduled_at, "pending")
    )
    post_id = c.lastrowid
    conn.commit()
    conn.close()
    return post_id


def update_post_status(post_id: int, status: str, blogger_post_id: str = None, error: str = None):
    conn = get_conn()
    if status == "published":
        conn.execute(
            """UPDATE posts SET status=?, blogger_post_id=?, published_at=datetime('now','localtime')
               WHERE id=?""",
            (status, blogger_post_id, post_id)
        )
    elif status == "failed":
        conn.execute(
            "UPDATE posts SET status=?, error_message=? WHERE id=?",
            (status, error, post_id)
        )
    else:
        conn.execute("UPDATE posts SET status=? WHERE id=?", (status, post_id))
    conn.commit()
    conn.close()


def get_published_titles(days: int = 90) -> list[str]:
    """최근 N일 발행된 글 제목 목록"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT title FROM posts
           WHERE status='published' AND title IS NOT NULL
           AND created_at > datetime('now', ?, 'localtime')
           ORDER BY created_at DESC""",
        (f"-{days} days",)
    ).fetchall()
    conn.close()
    return [r["title"] for r in rows]


def get_posts(limit: int = 50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM posts ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_gemini_usage(prompt_tokens: int, completion_tokens: int, total_tokens: int):
    """Gemini API 사용량 기록 (날짜별 누적)"""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    conn.execute("""
        INSERT INTO gemini_usage (date, request_count, prompt_tokens, completion_tokens, total_tokens)
        VALUES (?, 1, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            request_count = request_count + 1,
            prompt_tokens = prompt_tokens + excluded.prompt_tokens,
            completion_tokens = completion_tokens + excluded.completion_tokens,
            total_tokens = total_tokens + excluded.total_tokens
    """, (today, prompt_tokens, completion_tokens, total_tokens))
    conn.commit()
    conn.close()


def get_gemini_usage(days: int = 7) -> list[dict]:
    """최근 N일 Gemini 사용량 조회"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT date, request_count, prompt_tokens, completion_tokens, total_tokens
        FROM gemini_usage
        WHERE date >= date('now', ?, 'localtime')
        ORDER BY date DESC
    """, (f"-{days} days",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_logs(limit: int = 100):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
