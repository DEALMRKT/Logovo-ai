import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.getenv("DATABASE_PATH", "bot.db")


def get_connection():
    return sqlite3.connect(DB_PATH)


async def init_db(owner_id):
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                name TEXT DEFAULT '',
                role TEXT DEFAULT 'user',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        if owner_id:
            conn.execute("""
                INSERT INTO users (user_id, role)
                VALUES (?, 'owner')
                ON CONFLICT(user_id)
                DO UPDATE SET role = 'owner'
            """, (owner_id,))


def get_role(user_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT role FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    return row[0] if row else "user"


def set_role(user_id, role):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO users (user_id, role)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET role = excluded.role
        """, (user_id, role))


def log_user(user_id, username, name):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                username = excluded.username,
                name = excluded.name,
                last_seen = CURRENT_TIMESTAMP
        """, (user_id, username, name))


def list_users(limit=15):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT user_id, name, role
            FROM users
            ORDER BY last_seen DESC
            LIMIT ?
        """, (int(limit),)).fetchall()

    return [
        {
            "user_id": row[0],
            "name": row[1],
            "role": row[2]
        }
        for row in rows
    ]


def stats():
    with get_connection() as conn:
        users = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        today = conn.execute("""
            SELECT COUNT(*) FROM users
            WHERE date(last_seen) = date('now')
        """).fetchone()[0]

    return {
        "users": users,
        "today": today
    }
