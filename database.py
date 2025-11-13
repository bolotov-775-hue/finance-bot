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
                # 1. Создаём таблицы
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
                        subcategory TEXT DEFAULT '',
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

                # 2. МИГРАЦИЯ: безопасное добавление столбцов через information_schema
                migrations = [
                    ("users", "goal_end_date", "DATE"),
                    ("users", "saved_so_far", "DOUBLE PRECISION DEFAULT 0"),
                    ("transactions", "subcategory", "TEXT DEFAULT ''")
                ]

                for table, col, col_type in migrations:
                    try:
                        # Проверяем, существует ли столбец
                        cur.execute("""
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = %s AND column_name = %s
                        """, (table, col))
                        if not cur.fetchone():
                            # Добавляем, если отсутствует
                            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                            print(f"✅ Добавлен столбец {col} в {table}")
                    except Exception as e:
                        print(f"⚠️ Пропущена миграция {col} ({e})")
                        conn.rollback()  # Откатываем текущую транзакцию, чтобы не сломать последующие

                conn.commit()
    else:
        # SQLite (локально)
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
                    category TEXT DEFAULT 'прочее',
                    subcategory TEXT DEFAULT '',
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

            # Миграция для SQLite (через PRAGMA)
            async def ensure_column(table, col_def):
                try:
                    await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
                except aiosqlite.OperationalError as e:
                    if "duplicate column" in str(e).lower():
                        pass  # уже есть — игнорируем
                    else:
                        print(f"⚠️ SQLite миграция: {e}")

            await ensure_column("users", "goal_end_date TEXT")
            await ensure_column("users", "saved_so_far REAL DEFAULT 0")
            await ensure_column("transactions", "subcategory TEXT DEFAULT ''")

            await conn.commit()

# --- Функции работы с данными ---
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
                return None
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

async def add_transaction(user_id: int, t_type: str, amount: float, category: str = "прочее", subcategory: str = ""):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO transactions (user_id, type, amount, category, subcategory) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, t_type, amount, category, subcategory)
                )
            conn.commit()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            await conn.execute(
                "INSERT INTO transactions (user_id, type, amount, category, subcategory) VALUES (?, ?, ?, ?, ?)",
                (user_id, t_type, amount, category, subcategory)
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

async def get_expenses_by_period(user_id: int, period: str):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if period == "day":
                    where = "DATE(created_at) = CURRENT_DATE"
                elif period == "week":
                    where = "created_at >= DATE_TRUNC('week', NOW())"
                elif period == "month":
                    where = "DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW())"
                else:  # year
                    where = "EXTRACT(YEAR FROM created_at) = EXTRACT(YEAR FROM NOW())"
                
                cur.execute(f"""
                    SELECT category, subcategory, SUM(amount)
                    FROM transactions
                    WHERE user_id = %s AND type = 'expense' AND {where}
                    GROUP BY category, subcategory
                    ORDER BY SUM(amount) DESC
                """, (user_id,))
                return await cur.fetchall()
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            if period == "day":
                where = "DATE(created_at) = DATE('now')"
            elif period == "week":
                where = "strftime('%W', created_at) = strftime('%W', 'now') AND strftime('%Y', created_at) = strftime('%Y', 'now')"
            elif period == "month":
                where = "strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
            else:  # year
                where = "strftime('%Y', created_at) = strftime('%Y', 'now')"
            
            cursor = await conn.execute(f"""
                SELECT category, subcategory, SUM(amount)
                FROM transactions
                WHERE user_id = ? AND type = 'expense' AND {where}
                GROUP BY category, subcategory
                ORDER BY SUM(amount) DESC
            """, (user_id,))
            return await cursor.fetchall()

async def get_stats_for_month(user_id: int, year: int, month: int):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0)
                    FROM transactions
                    WHERE user_id = %s 
                      AND EXTRACT(YEAR FROM created_at) = %s
                      AND EXTRACT(MONTH FROM created_at) = %s
                """, (user_id, year, month))
                income, expense = await cur.fetchone()

                cur.execute("""
                    SELECT category, SUM(amount)
                    FROM transactions
                    WHERE user_id = %s AND type = 'expense'
                      AND EXTRACT(YEAR FROM created_at) = %s
                      AND EXTRACT(MONTH FROM created_at) = %s
                    GROUP BY category
                    ORDER BY SUM(amount) DESC
                    LIMIT 5
                """, (user_id, year, month))
                top_cats = await cur.fetchall()
                return income or 0.0, expense or 0.0, top_cats or []
    else:
        async with aiosqlite.connect("finance_bot.db") as conn:
            cursor = await conn.execute("""
                SELECT 
                    COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0)
                FROM transactions
                WHERE user_id = ? 
                  AND strftime('%Y', created_at) = ?
                  AND strftime('%m', created_at) = ?
            """, (user_id, str(year), f"{month:02d}"))
            row = await cursor.fetchone()
            income, expense = row[0], row[1]

            cursor = await conn.execute("""
                SELECT category, SUM(amount)
                FROM transactions
                WHERE user_id = ? AND type = 'expense'
                  AND strftime('%Y', created_at) = ?
                  AND strftime('%m', created_at) = ?
                GROUP BY category
                ORDER BY SUM(amount) DESC
                LIMIT 5
            """, (user_id, str(year), f"{month:02d}"))
            top_cats = await cursor.fetchall()
            return income or 0.0, expense or 0.0, top_cats or []

async def get_todos(user_id: int):
    if USE_POSTGRES:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, text, is_done FROM todos WHERE user_id = %s", (user_id,))
                rows = await cur.fetchall()
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