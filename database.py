import os
import asyncpg
import aiosqlite
from contextlib import asynccontextmanager

# Автоматическое определение среды
IS_RENDER = os.getenv("RENDER") is not None
DATABASE_URL = os.getenv("DATABASE_URL")  # для Render
USE_POSTGRES = IS_RENDER and DATABASE_URL

@asynccontextmanager
async def get_db_connection():
    """Универсальный контекстный менеджер для БД"""
    conn = None
    try:
        if USE_POSTGRES:
            conn = await asyncpg.connect(DATABASE_URL)
            yield conn
        else:
            # Локально — SQLite
            conn = await aiosqlite.connect("finance_bot.db")
            await conn.execute("PRAGMA foreign_keys = ON")
            yield conn
    finally:
        if conn:
            await conn.close()

async def init_db():
    async with get_db_connection() as conn:
        if USE_POSTGRES:
            # PostgreSQL
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    daily_limit DOUBLE PRECISION DEFAULT 0,
                    goal_amount DOUBLE PRECISION DEFAULT 0,
                    goal_days INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS todos (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    text TEXT NOT NULL,
                    is_done BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        else:
            # SQLite
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
        if isinstance(conn, aiosqlite.Connection):
            await conn.commit()

# --- Основные функции (работают и с SQLite, и с PostgreSQL) ---
async def get_user(user_id: int):
    async with get_db_connection() as conn:
        if USE_POSTGRES:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        else:
            cursor = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
        return row

async def create_user(user_id: int):
    async with get_db_connection() as conn:
        if USE_POSTGRES:
            await conn.execute(
                """
                INSERT INTO users (user_id) VALUES ($1)
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id
            )
        else:
            await conn.execute(
                "INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)
            )
        if isinstance(conn, aiosqlite.Connection):
            await conn.commit()

async def update_goal(user_id: int, goal_amount: float, days: int):
    daily_limit = max(0, goal_amount / days) if days > 0 else 0
    async with get_db_connection() as conn:
        if USE_POSTGRES:
            await conn.execute(
                """
                UPDATE users SET goal_amount = $1, goal_days = $2, daily_limit = $3
                WHERE user_id = $4
                """,
                goal_amount, days, daily_limit, user_id
            )
        else:
            await conn.execute(
                """
                UPDATE users SET goal_amount = ?, goal_days = ?, daily_limit = ?
                WHERE user_id = ?
                """,
                (goal_amount, days, daily_limit, user_id)
            )
        if isinstance(conn, aiosqlite.Connection):
            await conn.commit()

async def add_transaction(user_id: int, t_type: str, amount: float, category: str = "прочее", desc: str = ""):
    async with get_db_connection() as conn:
        if USE_POSTGRES:
            await conn.execute(
                """
                INSERT INTO transactions (user_id, type, amount, category, description)
                VALUES ($1, $2, $3, $4, $5)
                """,
                user_id, t_type, amount, category, desc
            )
        else:
            await conn.execute(
                "INSERT INTO transactions (user_id, type, amount, category, description) VALUES (?, ?, ?, ?, ?)",
                (user_id, t_type, amount, category, desc)
            )
        if isinstance(conn, aiosqlite.Connection):
            await conn.commit()

async def get_balance(user_id: int):
    async with get_db_connection() as conn:
        if USE_POSTGRES:
            row = await conn.fetchrow("""
                SELECT 
                    COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0)
                FROM transactions WHERE user_id = $1
            """, user_id)
        else:
            cursor = await conn.execute("""
                SELECT 
                    COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0)
                FROM transactions WHERE user_id = ?
            """, (user_id,))
            row = await cursor.fetchone()
        return row[0] if row and row[0] is not None else 0.0

async def get_today_expenses(user_id: int):
    async with get_db_connection() as conn:
        if USE_POSTGRES:
            row = await conn.fetchrow("""
                SELECT COALESCE(SUM(amount), 0)
                FROM transactions
                WHERE user_id = $1 AND type = 'expense' 
                  AND created_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'Europe/Moscow')
            """, user_id)
        else:
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
    async with get_db_connection() as conn:
        if USE_POSTGRES:
            await conn.execute("INSERT INTO todos (user_id, text) VALUES ($1, $2)", user_id, text)
        else:
            await conn.execute("INSERT INTO todos (user_id, text) VALUES (?, ?)", (user_id, text))
        if isinstance(conn, aiosqlite.Connection):
            await conn.commit()

async def get_todos(user_id: int):
    async with get_db_connection() as conn:
        if USE_POSTGRES:
            rows = await conn.fetch("SELECT id, text, is_done FROM todos WHERE user_id = $1", user_id)
        else:
            cursor = await conn.execute("SELECT id, text, is_done FROM todos WHERE user_id = ?", (user_id,))
            rows = await cursor.fetchall()
        return rows

async def toggle_todo_done(todo_id: int):
    async with get_db_connection() as conn:
        if USE_POSTGRES:
            await conn.execute("UPDATE todos SET is_done = NOT is_done WHERE id = $1", todo_id)
        else:
            await conn.execute("UPDATE todos SET is_done = NOT is_done WHERE id = ?", (todo_id,))
        if isinstance(conn, aiosqlite.Connection):
            await conn.commit()