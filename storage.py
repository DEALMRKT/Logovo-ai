import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "bot.db")

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

async def init_db(owner_id: int):
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, role TEXT DEFAULT 'user',
            first_seen TEXT, last_seen TEXT
        )""")
        if owner_id:
            con.execute("""INSERT INTO users(user_id, role, first_seen, last_seen)
                VALUES(?, 'owner', ?, ?) ON CONFLICT(user_id) DO UPDATE SET role='owner'""",
                (owner_id, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))

def log_user(user_id, username, name):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        con.execute("""INSERT INTO users(user_id, username, name, role, first_seen, last_seen)
            VALUES(?, ?, ?, 'user', ?, ?) ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username, name=excluded.name, last_seen=excluded.last_seen""",
            (user_id, username, name, now, now))

def get_role(user_id):
    with connect() as con:
        row = con.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row["role"] if row else "user"

def set_role(user_id, role):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        con.execute("""INSERT INTO users(user_id, role, first_seen, last_seen)
            VALUES(?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET role=excluded.role""",
            (user_id, role, now, now))

def list_users(limit=15):
    with connect() as con:
        rows = con.execute("SELECT user_id, name, role FROM users ORDER BY last_seen DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

def stats():
    today = datetime.now(timezone.utc).date().isoformat()
    with connect() as con:
        users = con.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        active = con.execute("SELECT COUNT(*) n FROM users WHERE substr(last_seen,1,10)=?", (today,)).fetchone()["n"]
    return {"users": users, "today": active}
