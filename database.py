import os
import psycopg2
import aiosqlite
from contextlib import contextmanager

IS_RENDER = os.getenv("RENDER") is not None
DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def get_db():
    conn = None
    try:
        if IS_RENDER and DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)
            yield conn
        else:
            conn = aiosqlite.connect("finance.db")
            yield conn
    finally:
        if conn:
            conn.close()

async def init_db():
    with get_db() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    goal_amount DOUBLE PRECISION DEFAULT 0,
                    goal_end_date DATE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    type VARCHAR(10),
                    amount DOUBLE PRECISION,
                    category TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS todos (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    text TEXT,
                    is_done BOOLEAN DEFAULT FALSE
                )
            """)
            conn.commit()
        else:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    goal_amount REAL DEFAULT 0,
                    goal_end_date TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    type TEXT,
                    amount REAL,
                    category TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    text TEXT,
                    is_done BOOLEAN DEFAULT 0
                )
            """)
            await conn.commit()

async def add_transaction(user_id, t_type, amount, category):
    with get_db() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO transactions (user_id, type, amount, category) VALUES (%s, %s, %s, %s)",
                (user_id, t_type, amount, category)
            )
            conn.commit()
        else:
            await conn.execute(
                "INSERT INTO transactions (user_id, type, amount, category) VALUES (?, ?, ?, ?)",
                (user_id, t_type, amount, category)
            )
            await conn.commit()

async def set_goal(user_id, amount, end_date):
    with get_db() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET goal_amount = %s, goal_end_date = %s WHERE user_id = %s",
                (amount, end_date, user_id)
            )
            conn.commit()
        else:
            await conn.execute(
                "UPDATE users SET goal_amount = ?, goal_end_date = ? WHERE user_id = ?",
                (amount, end_date, user_id)
            )
            await conn.commit()

async def clear_goal(user_id):
    with get_db() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET goal_amount = 0, goal_end_date = NULL WHERE user_id = %s",
                (user_id,)
            )
            conn.commit()
        else:
            await conn.execute(
                "UPDATE users SET goal_amount = 0, goal_end_date = NULL WHERE user_id = ?",
                (user_id,)
            )
            await conn.commit()

async def get_user_goal(user_id):
    with get_db() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute("SELECT goal_amount, goal_end_date FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return (row[0], row[1]) if row else (0, None)
        else:
            cursor = await conn.execute("SELECT goal_amount, goal_end_date FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return (row[0], row[1]) if row else (0, None)

async def get_balance(user_id):
    with get_db() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    COALESCE(SUM(CASE WHEN type='income' THEN amount ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN type='expense' THEN amount ELSE 0 END), 0)
                FROM transactions WHERE user_id = %s
            """, (user_id,))
            return (cur.fetchone()[0] or 0.0)
        else:
            cursor = await conn.execute("""
                SELECT 
                    COALESCE(SUM(CASE WHEN type='income' THEN amount ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN type='expense' THEN amount ELSE 0 END), 0)
                FROM transactions WHERE user_id = ?
            """, (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0.0

async def get_income(user_id):
    with get_db() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND type = 'income'", (user_id,))
            return (cur.fetchone()[0] or 0.0)
        else:
            cursor = await conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = ? AND type = 'income'", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0.0

async def get_expenses_by_period(user_id, period):
    with get_db() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            if period == "day":
                where = "DATE(created_at) = CURRENT_DATE"
            elif period == "week":
                where = "created_at >= DATE_TRUNC('week', NOW())"
            elif period == "month":
                where = "DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW())"
            else:  # year
                where = "EXTRACT(YEAR FROM created_at) = EXTRACT(YEAR FROM NOW())"
            cur.execute(f"SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND type = 'expense' AND {where}", (user_id,))
            return (cur.fetchone()[0] or 0.0)
        else:
            if period == "day":
                where = "DATE(created_at) = DATE('now')"
            elif period == "week":
                where = "strftime('%W', created_at) = strftime('%W', 'now') AND strftime('%Y', created_at) = strftime('%Y', 'now')"
            elif period == "month":
                where = "strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
            else:  # year
                where = "strftime('%Y', created_at) = strftime('%Y', 'now')"
            cursor = await conn.execute(f"SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = ? AND type = 'expense' AND {where}", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0.0

async def add_todo(user_id, text):
    with get_db() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute("INSERT INTO todos (user_id, text) VALUES (%s, %s)", (user_id, text))
            conn.commit()
        else:
            await conn.execute("INSERT INTO todos (user_id, text) VALUES (?, ?)", (user_id, text))
            await conn.commit()

async def get_todos(user_id):
    with get_db() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute("SELECT id, text, is_done FROM todos WHERE user_id = %s", (user_id,))
            return [(r[0], r[1], r[2]) for r in cur.fetchall()]
        else:
            cursor = await conn.execute("SELECT id, text, is_done FROM todos WHERE user_id = ?", (user_id,))
            return await cursor.fetchall()

async def toggle_todo(todo_id):
    with get_db() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute("UPDATE todos SET is_done = NOT is_done WHERE id = %s", (todo_id,))
            conn.commit()
        else:
            await conn.execute("UPDATE todos SET is_done = NOT is_done WHERE id = ?", (todo_id,))
            await conn.commit()