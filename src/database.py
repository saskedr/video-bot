import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            registered_at TEXT DEFAULT (datetime('now'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            platform TEXT,
            video_type TEXT,
            status TEXT DEFAULT 'pending',
            file_size INTEGER,
            compressed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)

    try:
        cursor.execute("ALTER TABLE downloads ADD COLUMN video_type TEXT")
        conn.commit()
    except Exception:
        pass

    conn.commit()
    conn.close()


def register_user(user_id, username=None, first_name=None, last_name=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
        VALUES (?, ?, ?, ?)
    """, (user_id, username, first_name, last_name))
    conn.commit()
    conn.close()


def log_download(user_id, url, platform, video_type=None, status="pending", file_size=None, compressed=False):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO downloads (user_id, url, platform, video_type, status, file_size, compressed)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, url, platform, video_type, status, file_size, 1 if compressed else 0))
    download_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return download_id


def update_download_status(download_id, status, file_size=None, compressed=False):
    conn = get_connection()
    cursor = conn.cursor()
    if file_size is not None:
        cursor.execute("""
            UPDATE downloads SET status = ?, file_size = ?, compressed = ? WHERE id = ?
        """, (status, file_size, 1 if compressed else 0, download_id))
    else:
        cursor.execute("""
            UPDATE downloads SET status = ?, compressed = ? WHERE id = ?
        """, (status, 1 if compressed else 0, download_id))
    conn.commit()
    conn.close()


def get_user_downloads_count(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM downloads
        WHERE user_id = ? AND status = 'success'
    """, (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result["cnt"] if result else 0


def get_user_stats(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors
        FROM downloads WHERE user_id = ?
    """, (user_id,))
    result = cursor.fetchone()
    stats = dict(result) if result else {"total": 0, "success": 0, "errors": 0}

    cursor.execute("""
        SELECT
            SUM(CASE WHEN video_type = 'youtube' AND status = 'success' THEN 1 ELSE 0 END) as youtube,
            SUM(CASE WHEN video_type = 'shorts' AND status = 'success' THEN 1 ELSE 0 END) as shorts,
            SUM(CASE WHEN video_type = 'tiktok' AND status = 'success' THEN 1 ELSE 0 END) as tiktok,
            SUM(CASE WHEN video_type = 'reels' AND status = 'success' THEN 1 ELSE 0 END) as reels,
            SUM(CASE WHEN video_type = 'instagram' AND status = 'success' THEN 1 ELSE 0 END) as instagram
        FROM downloads WHERE user_id = ?
    """, (user_id,))
    platform_result = cursor.fetchone()
    if platform_result:
        stats.update(dict(platform_result))
    else:
        stats.update({"youtube": 0, "shorts": 0, "tiktok": 0, "reels": 0, "instagram": 0})

    conn.close()
    return stats


def get_today_downloads_count(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM downloads
        WHERE user_id = ? AND status = 'success'
        AND date(created_at) = date('now')
    """, (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result["cnt"] if result else 0


def get_all_users_count():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM users")
    result = cursor.fetchone()
    conn.close()
    return result["cnt"] if result else 0
