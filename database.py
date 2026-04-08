import sqlite3

DB = "users.db"


def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id     INTEGER PRIMARY KEY,
        phone       TEXT,
        referrer_id INTEGER,
        step        INTEGER DEFAULT 0,
        ref_count   INTEGER DEFAULT 0,
        completed   INTEGER DEFAULT 0,
        bonus_link  TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        id        INTEGER PRIMARY KEY,
        ref_limit INTEGER DEFAULT 5
    )''')

    c.execute('INSERT OR IGNORE INTO settings (id, ref_limit) VALUES (1, 5)')

    # Migration: eski bazaga yangi ustunlar qo'shish
    cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    for col, typedef in [
        ("bonus_link", "TEXT"),
        ("completed",  "INTEGER DEFAULT 0"),
    ]:
        if col not in cols:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")
            print(f"[DB migration] '{col}' ustuni qo'shildi")

    conn.commit()
    conn.close()


# ── USERS ──────────────────────────────────

def add_user(user_id, referrer_id=None):
    conn = sqlite3.connect(DB)
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, referrer_id) VALUES (?, ?)",
        (user_id, referrer_id)
    )
    conn.commit()
    conn.close()


def get_user(user_id):
    """(user_id, phone, referrer_id, step, ref_count, completed, bonus_link)"""
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def set_phone(user_id, phone):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE users SET phone=? WHERE user_id=?", (phone, user_id))
    conn.commit()
    conn.close()


def set_step(user_id, step):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE users SET step=? WHERE user_id=?", (step, user_id))
    conn.commit()
    conn.close()


def set_completed(user_id):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE users SET completed=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def set_bonus_link(user_id, link):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE users SET bonus_link=? WHERE user_id=?", (link, user_id))
    conn.commit()
    conn.close()


def get_bonus_link(user_id):
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT bonus_link FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def add_referral(referrer_id):
    conn = sqlite3.connect(DB)
    conn.execute(
        "UPDATE users SET ref_count = ref_count + 1 WHERE user_id=?",
        (referrer_id,)
    )
    conn.commit()
    conn.close()


def get_ref_count(user_id):
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT ref_count FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else 0


def get_all_user_ids():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_users_list():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT user_id, phone, step, completed FROM users").fetchall()
    conn.close()
    return rows


def get_stats():
    conn = sqlite3.connect(DB)
    total     = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    completed = conn.execute("SELECT COUNT(*) FROM users WHERE completed=1").fetchone()[0]
    w_phone   = conn.execute("SELECT COUNT(*) FROM users WHERE phone IS NOT NULL").fetchone()[0]
    conn.close()
    return total, completed, w_phone


# ── SETTINGS ───────────────────────────────

def get_ref_limit():
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT ref_limit FROM settings WHERE id=1").fetchone()
    conn.close()
    return row[0] if row else 5


def set_ref_limit(limit: int):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE settings SET ref_limit=? WHERE id=1", (limit,))
    conn.commit()
    conn.close()
