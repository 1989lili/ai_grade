import sqlite3
import os
import sys
import datetime

if getattr(sys, 'frozen', False):
    EXE_DIR = os.path.dirname(sys.executable)
else:
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(EXE_DIR, 'activations.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS activations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hwid TEXT NOT NULL,
            license_key TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expiry TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            device_label TEXT DEFAULT '',
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )''')
        # 默认管理员 admin/admin123
        cursor = conn.execute("SELECT COUNT(*) FROM admin_users")
        if cursor.fetchone()[0] == 0:
            import hashlib
            pw_hash = hashlib.sha256('admin123'.encode()).hexdigest()
            conn.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
                         ('admin', pw_hash))


def add_activation(hwid, license_key, expiry=None, device_label='', note=''):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO activations (hwid, license_key, issued_at, expiry, device_label, note) VALUES (?, ?, ?, ?, ?, ?)",
            (hwid, license_key, datetime.datetime.now(datetime.UTC).isoformat(), expiry, device_label, note))


def get_activations(page=1, per_page=20, search='', status=''):
    with get_conn() as conn:
        where = []
        params = []
        if search:
            where.append("(hwid LIKE ? OR device_label LIKE ? OR note LIKE ?)")
            params.extend([f'%{search}%'] * 3)
        if status:
            where.append("status = ?")
            params.append(status)
        where_clause = ' AND '.join(where) if where else '1=1'

        total = conn.execute(f"SELECT COUNT(*) FROM activations WHERE {where_clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM activations WHERE {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page]
        ).fetchall()
        return [dict(r) for r in rows], total


def get_activation_by_hwid(hwid):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM activations WHERE hwid=? ORDER BY created_at DESC LIMIT 1", (hwid,)).fetchone()
        return dict(row) if row else None


def revoke_activation(activation_id):
    with get_conn() as conn:
        conn.execute("UPDATE activations SET status='revoked' WHERE id=?", (activation_id,))


def get_stats():
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM activations").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM activations WHERE status='active'").fetchone()[0]
        revoked = conn.execute("SELECT COUNT(*) FROM activations WHERE status='revoked'").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM activations WHERE date(created_at)=date('now')").fetchone()[0]
        return {'total': total, 'active': active, 'revoked': revoked, 'today': today}


def verify_admin(username, password):
    import hashlib
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM admin_users WHERE username=? AND password_hash=?",
            (username, pw_hash)
        ).fetchone()
        return dict(row) if row else None
