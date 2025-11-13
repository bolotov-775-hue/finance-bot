import os
import psycopg2
import aiosqlite
from contextlib import contextmanager

IS_RENDER = os.getenv("RENDER") is not None
DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def get_db_connection():
    conn = None
    try:
        if IS_RENDER and DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)
            yield conn
        else:
            conn = aiosqlite.connect("finance_bot.db")
            yield conn
    finally:
        if conn:
            conn.close()

async def init_db():
    with get_db_connection() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    goal_amount DOUBLE PRECISION DEFAULT 0,
                    goal_end_date DATE,
                    saved_so_far DOUBLE PRECISION DEFAULT 0
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
            
            # Безопасное добавление столбцов
            try:
                cur.execute("SELECT goal_end_date FROM users LIMIT 1")
            except:
                try:
                    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS goal_end_date DATE")
                except:
                    pass

            try:
                cur.execute("SELECT saved_so_far FROM users LIMIT 1")
            except:
                try:
                    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS saved_so_far DOUBLE PRECISION DEFAULT 0")
                except:
                    pass

            conn.commit()
        else:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    goal_amount REAL DEFAULT 0,
                    goal_end_date TEXT,
                    saved_so_far REAL DEFAULT 0
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

async def add_transaction(user_id, t_type, amount, category="прочее"):
    with get_db_connection() as conn:
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
    with get_db_connection() as conn:
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

async def get_balance(user_id):
    with get_db_connection() as conn:
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

async def get_total_income(user_id):
    with get_db_connection() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND type = 'income'", (user_id,))
            return cur.fetchone()[0] or 0.0
        else:
            cursor = await conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = ? AND type = 'income'", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0.0

async def get_user_goal(user_id):
    with get_db_connection() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute("SELECT goal_amount, goal_end_date FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return (row[0], row[1]) if row else (0, None)
        else:
            cursor = await conn.execute("SELECT goal_amount, goal_end_date FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return (row[0], row[1]) if row else (0, None)

async def get_today_expenses(user_id):
    with get_db_connection() as conn:
        if IS_RENDER and DATABASE_URL:
            cur = conn.cursor()
            cur.execute("""
                SELECT COALESCE(SUM(amount), 0)
                FROM transactions
                WHERE user_id = %s AND type = 'expense' 
                  AND DATE(created_at) = CURRENT_DATE
            """, (user_id,))
            return cur.fetchone()[0] or 0.0
        else:
            cursor = await conn.execute("""
                SELECT COALESCE(SUM(amount), 0)
                FROM transactions
                WHERE user_id = ? AND type = 'expense' 
                  AND DATE(created_at) = DATE('now')
            """, (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0.0