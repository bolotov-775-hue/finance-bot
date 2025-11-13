import asyncio
import os
from datetime import datetime, date
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

from database import *

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
IS_RENDER = os.getenv("RENDER") is not None

class States(StatesGroup):
    income = State()
    expense = State()
    goal = State()
    todo = State()

# 🎨 Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Доход"), KeyboardButton(text="🛒 Расход")],
        [KeyboardButton(text="🎯 Цель"), KeyboardButton(text="📊 Лимит")],
        [KeyboardButton(text="📈 Статистика"), KeyboardButton(text="📋 Задачи")],
    ],
    resize_keyboard=True
)

# 📱 /start
@dp.message(Command("start"))
async def start(message: Message):
    await init_db()
    await message.answer("👋 Привет! Я ваш финансовый помощник.", reply_markup=main_menu)

# 💰 Доход
@dp.message(lambda m: m.text == "💰 Доход")
async def income(message: Message, state: FSMContext):
    await message.answer("Введите сумму дохода:")
    await state.set_state(States.income)

@dp.message(States.income)
async def process_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        await add_transaction(message.from_user.id, "income", amount, "доход")
        await message.answer(f"✅ Доход +{amount} ₽", reply_markup=main_menu)
    except:
        await message.answer("❌ Введите число.")
    await state.clear()

# 🛒 Расход
@dp.message(lambda m: m.text == "🛒 Расход")
async def expense(message: Message, state: FSMContext):
    await message.answer("Введите сумму расхода:")
    await state.set_state(States.expense)

@dp.message(States.expense)
async def process_expense(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        await add_transaction(message.from_user.id, "expense", amount, "прочее")
        await message.answer(f"✅ Расход {amount} ₽", reply_markup=main_menu)
    except:
        await message.answer("❌ Введите число.")
    await state.clear()

# 🎯 Цель
@dp.message(lambda m: m.text == "🎯 Цель")
async def goal_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Установить цель", callback_data="goal:set")],
        [InlineKeyboardButton(text="Отменить цель", callback_data="goal:clear")],
        [InlineKeyboardButton(text="← Назад", callback_data="back:main")]
    ])
    await message.answer("🎯 Управление целью:", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "goal:set")
async def goal_set(callback, state: FSMContext):
    await callback.message.edit_text("🎯 Формат: `сумма ДД.ММ.ГГГГ` (пример: `10000 15.12.2025`)")
    await state.set_state(States.goal)
    await callback.answer()

@dp.message(States.goal)
async def process_goal(message: Message, state: FSMContext):
    try:
        parts = message.text.strip().split(maxsplit=1)
        amount = float(parts[0])
        end_date = datetime.strptime(parts[1], "%d.%m.%Y").date()
        await set_goal(message.from_user.id, amount, end_date)
        await message.answer(f"🎯 Цель установлена: {amount:.0f} ₽ к {end_date.strftime('%d.%m.%Y')}", reply_markup=main_menu)
    except:
        await message.answer("❌ Ошибка. Пример: `10000 15.12.2025`")
    await state.clear()

@dp.callback_query(lambda c: c.data == "goal:clear")
async def goal_clear(callback):
    await clear_goal(callback.from_user.id)
    await callback.message.edit_text("✅ Цель отменена.")
    await callback.answer()

# 📊 Лимит на день — ПРАВИЛЬНАЯ ФОРМУЛА
@dp.message(lambda m: m.text == "📊 Лимит")
async def daily_limit(message: Message):
    goal_amount, goal_end_date = await get_user_goal(message.from_user.id)
    if not goal_amount or not goal_end_date:
        await message.answer("❗ Сначала установите цель через «🎯 Цель» → «Установить цель».", reply_markup=main_menu)
        return

    try:
        end_date = date.fromisoformat(goal_end_date) if isinstance(goal_end_date, str) else goal_end_date
        days_left = (end_date - date.today()).days
        if days_left <= 0:
            await message.answer("🎯 Срок цели истёк.", reply_markup=main_menu)
            return

        income = await get_income(message.from_user.id)
        balance = await get_balance(message.from_user.id)
        saved = balance  # упрощённо: накоплено = текущий баланс
        to_save = max(0, goal_amount - saved)
        daily_limit = max(0, to_save / days_left)  # ПРАВИЛЬНАЯ ФОРМУЛА

        await message.answer(
            f"📊 Лимит на день:\n"
            f"🎯 Цель: {goal_amount:.0f} ₽ к {end_date.strftime('%d.%m.%Y')}\n"
            f"💰 Накоплено: {saved:.0f} ₽\n"
            f"📆 Дней осталось: {days_left}\n"
            f"📌 Нужно откладывать: {daily_limit:.2f} ₽/день\n"
            f"❗ Тратьте меньше этого лимита!",
            reply_markup=main_menu
        )
    except Exception as e:
        await message.answer("❌ Ошибка расчёта.", reply_markup=main_menu)

# 📈 Статистика
@dp.message(lambda m: m.text == "📈 Статистика")
async def stats_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📆 За день", callback_data="stats:day")],
        [InlineKeyboardButton(text="📆 За неделю", callback_data="stats:week")],
        [InlineKeyboardButton(text="📆 За месяц", callback_data="stats:month")],
        [InlineKeyboardButton(text="📆 За год", callback_data="stats:year")],
        [InlineKeyboardButton(text="← Назад", callback_data="back:main")]
    ])
    await message.answer("📈 Выберите период:", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("stats:"))
async def show_stats(callback):
    period = callback.data.split(":")[1]
    names = {"day": "день", "week": "неделю", "month": "месяц", "year": "год"}
    expense = await get_expenses_by_period(callback.from_user.id, period)
    income = await get_income(callback.from_user.id)
    balance = await get_balance(callback.from_user.id)
    
    await callback.message.edit_text(
        f"📈 За {names[period]}:\n"
        f"📥 Доходы: {income:.0f} ₽\n"
        f"📤 Расходы: {expense:.0f} ₽\n"
        f"💰 Баланс: {balance:.0f} ₽",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Назад", callback_data="back:stats")]
        ])
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back:stats")
async def back_stats(callback):
    await stats_menu(callback.message)

# 📋 Задачи — С ИНТЕРАКТИВНЫМ ВЫБОРОМ И ОТМЕТКОЙ
@dp.message(lambda m: m.text == "📋 Задачи")
async def todos_menu(message: Message):
    todos = await get_todos(message.from_user.id)
    if not todos:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="+ Добавить", callback_data="todo:add")],
            [InlineKeyboardButton(text="← Назад", callback_data="back:main")]
        ])
        await message.answer("📭 Нет задач.", reply_markup=kb)
        return

    # Кнопки: [номер] Задача → при нажатии — выбор действия
    kb = []
    for i, (tid, text, done) in enumerate(todos, 1):
        mark = "✅ " if done else ""
        kb.append([
            InlineKeyboardButton(
                text=f"{i}. {mark}{text}",
                callback_data=f"todo:select:{tid}"
            )
        ])
    kb.append([InlineKeyboardButton(text="+ Добавить", callback_data="todo:add")])
    kb.append([InlineKeyboardButton(text="← Назад", callback_data="back:main")])
    
    await message.answer("📋 Ваши задачи:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# При выборе задачи — показываем действия
@dp.callback_query(lambda c: c.data.startswith("todo:select:"))
async def todo_select(callback):
    todo_id = int(callback.data.split(":")[2])
    todos = await get_todos(callback.from_user.id)
    selected = next((t for t in todos if t[0] == todo_id), None)
    if not selected:
        await callback.answer("Задача не найдена.")
        return

    _, text, done = selected
    status = "✅ Выполнено" if done else "🔲 Не выполнено"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Отметить как выполнено" if not done else "🔲 Снять выполнение",
            callback_data=f"todo:toggle:{todo_id}"
        )],
        [InlineKeyboardButton(text="← Назад к списку", callback_data="back:todos")]
    ])
    
    await callback.message.edit_text(
        f"📌 Задача: {text}\nСтатус: {status}",
        reply_markup=kb
    )
    await callback.answer()

# Отметить/снять выполнение
@dp.callback_query(lambda c: c.data.startswith("todo:toggle:"))
async def toggle_todo_handler(callback):
    todo_id = int(callback.data.split(":")[2])
    await toggle_todo(todo_id)
    await todos_menu(callback.message)
    await callback.answer()

# Добавить задачу
@dp.callback_query(lambda c: c.data == "todo:add")
async def todo_add(callback, state: FSMContext):
    await callback.message.edit_text("📝 Введите задачу:")
    await state.set_state(States.todo)
    await callback.answer()

@dp.message(States.todo)
async def process_todo(message: Message, state: FSMContext):
    await add_todo(message.from_user.id, message.text)
    await message.answer("✅ Задача добавлена!", reply_markup=main_menu)
    await state.clear()

# ← Назад
@dp.callback_query(lambda c: c.data == "back:main")
async def back_main(callback):
    await callback.message.delete()
    await start(callback.message)

@dp.callback_query(lambda c: c.data == "back:todos")
async def back_todos(callback):
    await todos_menu(callback.message)

# 🚀 Запуск
async def main():
    await init_db()
    
    if IS_RENDER:
        app = web.Application()
        app.router.add_get("/", lambda _: web.Response(text="Bot is alive"))
        port = int(os.environ.get("PORT", 10000))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())