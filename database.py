import os
import psycopg2
import aiosqlite
from contextlib import contextmanager

# Определяем среду
IS_RENDER = os.getenv("RENDER") is not None
DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = IS_RENDER and DATABASE_URL

# Для PostgreSQL — используем sync-версию (aiogram + psycopg2-binary работают вместе)
@contextmanager
def get_db_connection():
    conn = None
    try:
        if USE_POSTGRES:
            conn = psycopg2.connect(DATABASE_URL)
            yield conn
        else:
            # Локально — SQLite
            conn = aiosqlite.connect("finance_bot.db")
            yield conn
    finally:
        if conn:
            if USE_POSTGRES:
                conn.close()
            else:
                conn.close()

async def init_db():
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        daily_limit DOUBLE PRECISION DEFAULT 0,
                        goal_amount DOUBLE PRECISION DEFAULT 0,
                        goal_days INTEGER DEFAULT 0,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        type VARCHAR(10) CHECK (type IN ('income', 'expense')),
                        amount DOUBLE PRECISION NOT NULL,
                        category TEXT DEFAULT 'прочее',
                        description TEXT DEFAULT '',
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS todos (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        text TEXT NOT NULL,
                        is_done BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    daily_limit REAL DEFAULT 0,
                    goal_amount REAL DEFAULT 0,
                    goal_days INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    type TEXT CHECK(type IN ('income', 'expense')),
                    amount REAL,
                    category TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    text TEXT,
                    is_done BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.commit()

# --- Функции ---
async def get_user(user_id: int):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                if row:
                    return {
                        "user_id": row[0],
                        "daily_limit": row[1],
                        "goal_amount": row[2],
                        "goal_days": row[3],
                        "created_at": row[4]
                    }
                return None
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            cursor = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0],
                    "daily_limit": row[1],
                    "goal_amount": row[2],
                    "goal_days": row[3],
                    "created_at": row[4]
                }
            return None

async def create_user(user_id: int):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (user_id) VALUES (%s)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (user_id,)
                )
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)
            )
            await conn.commit()

async def update_goal(user_id: int, goal_amount: float, days: int):
    daily_limit = max(0, goal_amount / days) if days > 0 else 0
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users SET goal_amount = %s, goal_days = %s, daily_limit = %s
                    WHERE user_id = %s
                    """,
                    (goal_amount, days, daily_limit, user_id)
                )
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute(
                """
                UPDATE users SET goal_amount = ?, goal_days = ?, daily_limit = ?
                WHERE user_id = ?
                """,
                (goal_amount, days, daily_limit, user_id)
            )
            await conn.commit()

async def add_transaction(user_id: int, t_type: str, amount: float, category: str = "прочее", desc: str = ""):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO transactions (user_id, type, amount, category, description)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (user_id, t_type, amount, category, desc)
                )
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute(
                "INSERT INTO transactions (user_id, type, amount, category, description) VALUES (?, ?, ?, ?, ?)",
                (user_id, t_type, amount, category, desc)
            )
            await conn.commit()

async def get_balance(user_id: int):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) -
                        COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0)
                    FROM transactions WHERE user_id = %s
                """, (user_id,))
                row = cur.fetchone()
                return row[0] if row else 0.0
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            cursor = await conn.execute("""
                SELECT 
                    COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0)
                FROM transactions WHERE user_id = ?
            """, (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0.0

async def get_today_expenses(user_id: int):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COALESCE(SUM(amount), 0)
                    FROM transactions
                    WHERE user_id = %s AND type = 'expense' 
                      AND created_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'Europe/Moscow')
                """, (user_id,))
                row = cur.fetchone()
                return row[0] if row else 0.0
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            cursor = await conn.execute("""
                SELECT COALESCE(SUM(amount), 0)
                FROM transactions
                WHERE user_id = ? AND type = 'expense' 
                  AND DATE(created_at) = DATE('now', 'localtime')
            """, (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0.0

# --- TODO ---
async def add_todo(user_id: int, text: str):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO todos (user_id, text) VALUES (%s, %s)", (user_id, text))
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute("INSERT INTO todos (user_id, text) VALUES (?, ?)", (user_id, text))
            await conn.commit()

async def get_todos(user_id: int):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, text, is_done FROM todos WHERE user_id = %s", (user_id,))
                rows = cur.fetchall()
                return [{"id": r[0], "text": r[1], "is_done": r[2]} for r in rows]
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            cursor = await conn.execute("SELECT id, text, is_done FROM todos WHERE user_id = ?", (user_id,))
            rows = await cursor.fetchall()
            return [{"id": r[0], "text": r[1], "is_done": r[2]} for r in rows]

async def toggle_todo_done(todo_id: int):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE todos SET is_done = NOT is_done WHERE id = %s", (todo_id,))
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute("UPDATE todos SET is_done = NOT is_done WHERE id = ?", (todo_id,))
            await conn.commit()