import asyncio
import os
from datetime import datetime, date, timedelta
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
    reminder = State()

# 🎨 Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Доход"), KeyboardButton(text="🛒 Расход")],
        [KeyboardButton(text="🎯 Цель"), KeyboardButton(text="📊 Лимит")],
        [KeyboardButton(text="📈 Статистика"), KeyboardButton(text="📋 Задачи")],
        [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="🧹 Очистить всё")],
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

# 🎯 Цель — ПОКАЗ ТЕКУЩЕЙ ЦЕЛИ ИЛИ УСТАНОВКА
@dp.message(lambda m: m.text == "🎯 Цель")
async def goal_menu(message: Message):
    goal_amount, goal_end_date = await get_user_goal(message.from_user.id)
    if goal_amount and goal_end_date:
        try:
            end_date = date.fromisoformat(goal_end_date) if isinstance(goal_end_date, str) else goal_end_date
            text = f"🎯 Текущая цель: {goal_amount:.0f} ₽ к {end_date.strftime('%d.%m.%Y')}"
        except:
            text = f"🎯 Текущая цель: {goal_amount:.0f} ₽"
    else:
        text = "🎯 Цель не установлена."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить цель", callback_data="goal:set")],
        [InlineKeyboardButton(text="Отменить цель", callback_data="goal:clear")],
        [InlineKeyboardButton(text="✅ Цель выполнена", callback_data="goal:done")],
        [InlineKeyboardButton(text="← Назад", callback_data="back:main")]
    ])
    await message.answer(text, reply_markup=kb)

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

@dp.callback_query(lambda c: c.data == "goal:done")
async def goal_done(callback):
    await clear_goal(callback.from_user.id)
    await callback.message.edit_text("✅ Цель выполнена и удалена.")
    await callback.answer()

# 🧹 Очистить всё
@dp.message(lambda m: m.text == "🧹 Очистить всё")
async def clear_all_cmd(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, очистить ВСЁ", callback_data="clear:confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back:main")]
    ])
    await message.answer("⚠️ Внимание! Это удалит:\n• Все доходы и расходы\n• Цель\n• Все задачи\n\nПродолжить?", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "clear:confirm")
async def clear_confirm(callback):
    await clear_all(callback.from_user.id)
    await callback.message.edit_text("✅ Вся история очищена.")
    await callback.answer()

# 💰 Баланс
@dp.message(lambda m: m.text == "💰 Баланс")
async def balance_cmd(message: Message):
    balance = await get_balance(message.from_user.id)
    await message.answer(f"💰 Текущий баланс: {balance:.2f} ₽", reply_markup=main_menu)

# 📊 Лимит на день
@dp.message(lambda m: m.text == "📊 Лимит")
async def daily_limit(message: Message):
    goal_amount, goal_end_date = await get_user_goal(message.from_user.id)
    if not goal_amount or not goal_end_date:
        await message.answer("❗ Сначала установите цель через «🎯 Цель».", reply_markup=main_menu)
        return

    try:
        end_date = date.fromisoformat(goal_end_date) if isinstance(goal_end_date, str) else goal_end_date
        days_left = (end_date - date.today()).days
        if days_left <= 0:
            await message.answer("🎯 Срок цели истёк.", reply_markup=main_menu)
            return

        balance = await get_balance(message.from_user.id)
        to_save = max(0, goal_amount - balance)
        daily_limit = max(0, to_save / days_left)

        await message.answer(
            f"📊 Лимит на день:\n"
            f"🎯 Цель: {goal_amount:.0f} ₽ к {end_date.strftime('%d.%m.%Y')}\n"
            f"💰 Баланс: {balance:.0f} ₽\n"
            f"📆 Дней осталось: {days_left}\n"
            f"📌 Нужно откладывать: {daily_limit:.2f} ₽/день",
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

# 📋 Задачи — С УДАЛЕНИЕМ ПРИ ВЫПОЛНЕНИИ
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

    kb = []
    for i, (tid, text, done, due_date) in enumerate(todos, 1):
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

@dp.callback_query(lambda c: c.data.startswith("todo:select:"))
async def todo_select(callback):
    todo_id = int(callback.data.split(":")[2])
    todos = await get_todos(callback.from_user.id)
    selected = next((t for t in todos if t[0] == todo_id), None)
    if not selected:
        await callback.answer("Задача не найдена.")
        return

    _, text, done, due_date = selected
    status = "✅ Выполнено" if done else "🔲 Не выполнено"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Отметить как выполнено" if not done else "🗑 Удалить",
            callback_data=f"todo:toggle:{todo_id}"
        )],
        [InlineKeyboardButton(text="⏰ Установить напоминание", callback_data=f"reminder:set:{todo_id}")],
        [InlineKeyboardButton(text="← Назад к списку", callback_data="back:todos")]
    ])
    
    await callback.message.edit_text(
        f"📌 Задача: {text}\nСтатус: {status}\nСрок: {due_date or '—'}",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("todo:toggle:"))
async def toggle_todo_handler(callback):
    todo_id = int(callback.data.split(":")[2])
    todos = await get_todos(callback.from_user.id)
    selected = next((t for t in todos if t[0] == todo_id), None)
    if not selected:
        await callback.answer("Задача не найдена.")
        return

    _, _, done, _ = selected
    if done:
        # Удаляем задачу
        await delete_todo(todo_id)
        await callback.message.edit_text("🗑 Задача удалена.")
    else:
        # Отмечаем как выполненную
        await toggle_todo(todo_id)
        await callback.message.edit_text("✅ Задача отмечена как выполненная.")

    await todos_menu(callback.message)
    await callback.answer()

# 🕒 Напоминания к задачам
@dp.callback_query(lambda c: c.data.startswith("reminder:set:"))
async def reminder_set(callback, state: FSMContext):
    todo_id = int(callback.data.split(":")[2])
    await state.update_data(todo_id=todo_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="За 1 день", callback_data="rem:day")],
        [InlineKeyboardButton(text="За 1 час", callback_data="rem:hour")],
        [InlineKeyboardButton(text="Оба", callback_data="rem:both")],
        [InlineKeyboardButton(text="← Назад", callback_data="back:todo")]
    ])
    await callback.message.edit_text("⏰ Когда напомнить?", reply_markup=kb)
    await state.set_state(States.reminder)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("rem:"))
async def process_reminder(callback, state: FSMContext):
    data = await state.get_data()
    todo_id = data["todo_id"]
    trigger_type = callback.data.split(":")[1]
    
    # Устанавливаем напоминание на 1 день/час до даты задачи
    todos = await get_todos(callback.from_user.id)
    selected = next((t for t in todos if t[0] == todo_id), None)
    if not selected:
        await callback.message.edit_text("Задача не найдена.")
        await state.clear()
        await callback.answer()
        return

    _, _, _, due_date_str = selected
    if not due_date_str:
        await callback.message.edit_text("❌ У задачи нет срока.")
        await state.clear()
        await callback.answer()
        return

    try:
        due_date = date.fromisoformat(due_date_str) if isinstance(due_date_str, str) else due_date_str
        now = datetime.now()
        
        if trigger_type == "day":
            scheduled = datetime.combine(due_date - timedelta(days=1), now.time())
        elif trigger_type == "hour":
            scheduled = datetime.combine(due_date, now.time()) - timedelta(hours=1)
        else:  # both
            # Создаем два напоминания
            scheduled_day = datetime.combine(due_date - timedelta(days=1), now.time())
            scheduled_hour = datetime.combine(due_date, now.time()) - timedelta(hours=1)
            
            await add_reminder(callback.from_user.id, todo_id, "day", scheduled_day)
            await add_reminder(callback.from_user.id, todo_id, "hour", scheduled_hour)
            await callback.message.edit_text("✅ Напоминания установлены: за 1 день и за 1 час.")
            await state.clear()
            await callback.answer()
            return
        
        await add_reminder(callback.from_user.id, todo_id, trigger_type, scheduled)
        await callback.message.edit_text(f"✅ Напоминание установлено: за {trigger_type}")
    except Exception as e:
        await callback.message.edit_text("❌ Ошибка установки напоминания.")
    
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back:todo")
async def back_todo(callback):
    await todos_menu(callback.message)

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