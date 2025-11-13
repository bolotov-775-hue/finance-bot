import asyncio
import os
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from aiohttp import web

from database import *

# 🔐 Токен — из переменной окружения (в Render задаётся вручную)
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен. Укажите в переменных окружения.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# Проверка: запущен ли на Render
IS_RENDER = os.getenv("RENDER") is not None

# 🧠 Состояния
class FinanceStates(StatesGroup):
    waiting_for_income = State()
    waiting_for_expense = State()
    waiting_for_goal = State()
    waiting_for_todo = State()

# 🛠 Утилиты
def parse_amount_category(text: str):
    parts = text.strip().split(maxsplit=1)
    if len(parts) == 1:
        return float(parts[0]), "прочее"
    try:
        amount = float(parts[0])
        category = parts[1].strip() or "прочее"
        return amount, category
    except ValueError:
        raise ValueError("Неверный формат")

# 📱 Команды
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await create_user(user_id)
    await message.answer(
        "👋 Привет! Я — ваш финансовый помощник.\n\n"
        "📌 Команды:\n"
        "/income — +доход\n"
        "/expense — –расход\n"
        "/balance — баланс\n"
        "/today — траты сегодня + лимит\n"
        "/goal — цель (например: `10000 30`)\n"
        "/todo — добавить задачу\n"
        "/todos — список задач\n"
        "/done 1 — отметить задачу №1 как сделанную"
    )

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    balance = await get_balance(message.from_user.id)
    await message.answer(f"💰 Баланс: {balance:.2f} ₽")

@dp.message(Command("today"))
async def cmd_today(message: Message):
    user_id = message.from_user.id
    spent = await get_today_expenses(user_id)
    user = await get_user(user_id)
    daily_limit = user["daily_limit"] if user else 0
    left = max(0, daily_limit - spent)
    status = "🟢 В пределах лимита" if spent <= daily_limit else "🔴 Превышен лимит"
    await message.answer(
        f"📆 Сегодня потрачено: {spent:.2f} ₽\n"
        f"🎯 Лимит на день: {daily_limit:.2f} ₽\n"
        f"➡️ Осталось: {left:.2f} ₽\n"
        f"{status}"
    )

@dp.message(Command("income"))
async def cmd_income(message: Message, state: FSMContext):
    await message.answer("💸 Введите: `сумма [категория]` (например: `50000 зарплата`)")
    await state.set_state(FinanceStates.waiting_for_income)

@dp.message(FinanceStates.waiting_for_income)
async def process_income(message: Message, state: FSMContext):
    try:
        amount, category = parse_amount_category(message.text)
        await add_transaction(message.from_user.id, "income", amount, category)
        await message.answer(f"✅ Доход +{amount} ₽ добавлен (категория: {category})")
    except Exception:
        await message.answer("❌ Ошибка. Пример: `50000 зарплата`")
    await state.clear()

@dp.message(Command("expense"))
async def cmd_expense(message: Message, state: FSMContext):
    await message.answer("🛒 Введите: `сумма [категория]` (например: `450 супермаркет`)")
    await state.set_state(FinanceStates.waiting_for_expense)

@dp.message(FinanceStates.waiting_for_expense)
async def process_expense(message: Message, state: FSMContext):
    try:
        amount, category = parse_amount_category(message.text)
        await add_transaction(message.from_user.id, "expense", amount, category)
        spent = await get_today_expenses(message.from_user.id)
        user = await get_user(message.from_user.id)
        daily_limit = user["daily_limit"] if user else 0
        if daily_limit > 0 and spent > daily_limit:
            await message.answer(f"⚠️ Превышен дневной лимит на {spent - daily_limit:.2f} ₽!")
        await message.answer(f"✅ Расход {amount} ₽ записан (категория: {category})")
    except Exception:
        await message.answer("❌ Ошибка. Пример: `450 супермаркет`")
    await state.clear()

@dp.message(Command("goal"))
async def cmd_goal(message: Message, state: FSMContext):
    await message.answer(
        "🎯 Установите цель: `сумма дней`\n"
        "Пример: `10000 30` — накопить 10 000 ₽ за 30 дней"
    )
    await state.set_state(FinanceStates.waiting_for_goal)

@dp.message(FinanceStates.waiting_for_goal)
async def process_goal(message: Message, state: FSMContext):
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError()
        goal_amount = float(parts[0])
        days = int(parts[1])
        if days <= 0:
            raise ValueError()
        await update_goal(message.from_user.id, goal_amount, days)
        await message.answer(
            f"🎯 Цель: накопить {goal_amount:.0f} ₽ за {days} дней.\n"
            f"📅 Дневной лимит будет пересчитан на основе доходов."
        )
    except Exception:
        await message.answer("❌ Ошибка. Пример: `10000 30`")
    await state.clear()

@dp.message(Command("todo"))
async def cmd_todo_add(message: Message, state: FSMContext):
    await message.answer("📝 Введите задачу:")
    await state.set_state(FinanceStates.waiting_for_todo)

@dp.message(FinanceStates.waiting_for_todo)
async def process_todo(message: Message, state: FSMContext):
    await add_todo(message.from_user.id, message.text)
    await message.answer("✅ Задача добавлена!")
    await state.clear()

@dp.message(Command("todos"))
async def cmd_todos(message: Message):
    todos = await get_todos(message.from_user.id)
    if not todos:
        await message.answer("📭 Нет задач.")
        return
    text = "📋 Задачи:\n"
    for t in todos:
        mark = "✅" if t["is_done"] else "🔲"  # PostgreSQL возвращает dict, SQLite — tuple
        tid = t["id"] if isinstance(t, dict) else t[0]
        txt = t["text"] if isinstance(t, dict) else t[1]
        done = t["is_done"] if isinstance(t, dict) else t[2]
        mark = "✅" if done else "🔲"
        text += f"{mark} [{tid}] {txt}\n"
    text += "\n✅ Чтобы завершить: `/done 1`"
    await message.answer(text)

@dp.message(Command("done"))
async def cmd_done(message: Message):
    try:
        todo_id = int(message.text.split()[1])
        await toggle_todo_done(todo_id)
        await message.answer(f"✅ Задача №{todo_id} обновлена.")
    except Exception:
        await message.answer("❌ Используйте: `/done 123`")

# --- Напоминания (ежедневно в 09:00) ---
async def send_reminder(user_id: int, text: str):
    try:
        await bot.send_message(user_id, f"⏰ Напоминание:\n\n{text}")
    except Exception as e:
        print(f"[Напоминание] Ошибка {user_id}: {e}")

# Регистрация напоминания (можно расширить позже)
@dp.message(Command("remind"))
async def cmd_remind(message: Message):
    await message.answer(
        "🔔 Напишите текст напоминания — я буду присылать его ежедневно в 09:00.\n"
        "(Пока без даты/времени — для MVP)"
    )
    # В будущем можно добавить FSM для выбора времени

@dp.message(lambda msg: not msg.text.startswith("/"))
async def handle_reminder_text(message: Message):
    user_id = message.from_user.id
    text = message.text
    job_id = f"remind_{user_id}"
    # Удалим старое и добавим новое
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(
        send_reminder,
        CronTrigger(hour=9, minute=0, timezone="Europe/Moscow"),
        args=[user_id, text],
        id=job_id,
        replace_existing=True
    )
    await message.answer(f"✅ Напоминание установлено:\n«{text}»\nБудет приходить ежедневно в 09:00.")

# 🚀 Запуск
async def main():
    await init_db()
    scheduler.start()

    # Для Render: HTTP-сервер (health check)
    if IS_RENDER:
        app = web.Application()
        app.router.add_get("/", lambda _: web.Response(text="✅ Бот жив."))
        port = int(os.environ.get("PORT", 10000))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"📡 HTTP health-check на порту {port}")

    print("🤖 Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Бот остановлен.")