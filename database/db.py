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


def get_posts(limit: int = 50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM posts ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_logs(limit: int = 100):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
