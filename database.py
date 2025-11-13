import os
import psycopg2
import aiosqlite
from contextlib import contextmanager
from datetime import date

IS_RENDER = os.getenv("RENDER") is not None
DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = IS_RENDER and DATABASE_URL

@contextmanager
def get_db_connection():
    conn = None
    try:
        if USE_POSTGRES:
            conn = psycopg2.connect(DATABASE_URL)
            yield conn
        else:
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
                        goal_end_date DATE,
                        saved_so_far DOUBLE PRECISION DEFAULT 0,
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
                    goal_end_date TEXT,
                    saved_so_far REAL DEFAULT 0,
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

# --- Основные функции ---
async def get_user(user_id: int):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                if row:
                    return {
                        "user_id": row[0], "daily_limit": row[1], "goal_amount": row[2],
                        "goal_end_date": row[3], "saved_so_far": row[4]
                    }
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            cursor = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0], "daily_limit": row[1], "goal_amount": row[2],
                    "goal_end_date": row[3], "saved_so_far": row[4]
                }
    return None

async def create_user(user_id: int):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (user_id,)
                )
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            await conn.commit()

async def update_goal(user_id: int, goal_amount: float, end_date: date):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET goal_amount = %s, goal_end_date = %s WHERE user_id = %s",
                    (goal_amount, end_date, user_id)
                )
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute(
                "UPDATE users SET goal_amount = ?, goal_end_date = ? WHERE user_id = ?",
                (goal_amount, end_date.isoformat(), user_id)
            )
            await conn.commit()

async def update_saved_so_far(user_id: int, saved: float):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET saved_so_far = %s WHERE user_id = %s",
                    (saved, user_id)
                )
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute(
                "UPDATE users SET saved_so_far = ? WHERE user_id = ?",
                (saved, user_id)
            )
            await conn.commit()

async def add_transaction(user_id: int, t_type: str, amount: float, category: str = "прочее"):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO transactions (user_id, type, amount, category)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (user_id, t_type, amount, category)
                )
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute(
                "INSERT INTO transactions (user_id, type, amount, category) VALUES (?, ?, ?, ?)",
                (user_id, t_type, amount, category)
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

async def update_daily_limit(user_id: int):
    user = await get_user(user_id)
    if not user or not user["goal_amount"] or not user["goal_end_date"]:
        return 0.0

    # Получаем общий доход
    balance = await get_balance(user_id)
    saved = user["saved_so_far"]
    # Доходы = баланс + расходы (но проще: баланс = доходы - расходы)
    # Для упрощения: считаем, что saved_so_far = баланс (можно уточнить)
    income = balance + await get_today_expenses(user_id)  # заглушка — в продакшене лучше хранить отдельно

    try:
        if isinstance(user["goal_end_date"], str):
            end_date = date.fromisoformat(user["goal_end_date"])
        else:
            end_date = user["goal_end_date"]
    except:
        return 0.0

    today = date.today()
    days_left = (end_date - today).days
    if days_left <= 0:
        return 0.0

    to_save = max(0, user["goal_amount"] - saved)
    daily_limit = max(0, (income - to_save) / days_left)

    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET daily_limit = %s WHERE user_id = %s", (daily_limit, user_id))
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute("UPDATE users SET daily_limit = ? WHERE user_id = ?", (daily_limit, user_id))
            await conn.commit()

    return daily_limit

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