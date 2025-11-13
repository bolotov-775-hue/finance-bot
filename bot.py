import asyncio
import os
import logging
from datetime import datetime, date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

from database import *

# 🔐 Токен
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
IS_RENDER = os.getenv("RENDER") is not None

# 🧠 Состояния
class FinanceStates(StatesGroup):
    waiting_for_income = State()
    waiting_for_expense_amount = State()
    waiting_for_expense_category = State()
    waiting_for_goal = State()
    waiting_for_todo = State()

class ReminderState(StatesGroup):
    waiting_for_text = State()
    waiting_for_date = State()
    waiting_for_time_choice = State()

# 🎨 Кнопки
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Доход"), KeyboardButton(text="🛒 Расход")],
        [KeyboardButton(text="📊 Баланс"), KeyboardButton(text="🎯 Цель")],
        [KeyboardButton(text="📋 Задачи"), KeyboardButton(text="⏰ Напоминания")],
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

expense_categories = ["еда", "транспорт", "лекарства", "быт", "развлечения", "другое"]

# 📱 /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await create_user(message.from_user.id)
    await message.answer(
        "👋 Привет! Я — ваш финансовый помощник 💊💰\n"
        "Выберите действие в меню ниже:",
        reply_markup=main_menu
    )

# 💰 Доход
@dp.message(F.text == "💰 Доход")
async def cmd_income(message: Message, state: FSMContext):
    await message.answer("💸 Введите сумму дохода (например: `50000`):")
    await state.set_state(FinanceStates.waiting_for_income)

@dp.message(FinanceStates.waiting_for_income)
async def process_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        await add_transaction(message.from_user.id, "income", amount)
        await update_daily_limit(message.from_user.id)
        await message.answer(f"✅ Доход +{amount} ₽", reply_markup=main_menu)
    except:
        await message.answer("❌ Введите число.")
    await state.clear()

# 🛒 Расход
@dp.message(F.text == "🛒 Расход")
async def cmd_expense_menu(message: Message):
    buttons = []
    for cat in expense_categories:
        buttons.append([InlineKeyboardButton(text=f"{cat.capitalize()}", callback_data=f"exp_cat:{cat}")])
    buttons.append([InlineKeyboardButton(text="← Назад", callback_data="back_to_menu")])
    await message.answer(
        "Выберите категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data.startswith("exp_cat:"))
async def process_expense_category(callback: types.CallbackQuery, state: FSMContext):
    category = callback.data.split(":")[1]
    await state.update_data(category=category)
    await callback.message.edit_text(f"Категория: {category}\nВведите сумму:")
    await state.set_state(FinanceStates.waiting_for_expense_amount)
    await callback.answer()

@dp.message(FinanceStates.waiting_for_expense_amount)
async def process_expense_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        data = await state.get_data()
        category = data["category"]
        await add_transaction(message.from_user.id, "expense", amount, category)
        
        # Обновляем лимит и показываем остаток
        daily_limit = await update_daily_limit(message.from_user.id)
        spent = await get_today_expenses(message.from_user.id)
        left = max(0, daily_limit - spent)
        
        await message.answer(
            f"✅ Расход {amount} ₽ ({category})\n"
            f"📆 Осталось на сегодня: {left:.2f} ₽",
            reply_markup=main_menu
        )
    except:
        await message.answer("❌ Введите число.")
    await state.clear()

# 📊 Баланс
@dp.message(F.text == "📊 Баланс")
async def cmd_balance(message: Message):
    balance = await get_balance(message.from_user.id)
    await message.answer(f"💰 Баланс: {balance:.2f} ₽", reply_markup=main_menu)

# 🎯 Цель
@dp.message(F.text == "🎯 Цель")
async def cmd_goal(message: Message, state: FSMContext):
    await message.answer(
        "🎯 Установите финансовую цель.\n"
        "Формат: `сумма ДД.ММ.ГГГГ`\n"
        "Пример: `10000 15.12.2025`"
    )
    await state.set_state(FinanceStates.waiting_for_goal)

@dp.message(FinanceStates.waiting_for_goal)
async def process_goal(message: Message, state: FSMContext):
    try:
        parts = message.text.strip().split(maxsplit=1)
        goal_amount = float(parts[0])
        end_date = datetime.strptime(parts[1], "%d.%m.%Y").date()
        await update_goal(message.from_user.id, goal_amount, end_date)
        await update_daily_limit(message.from_user.id)
        await message.answer(
            f"🎯 Цель: накопить {goal_amount:.0f} ₽ к {end_date.strftime('%d.%m.%Y')}\n"
            f"📅 Дневной лимит рассчитан автоматически.",
            reply_markup=main_menu
        )
    except Exception as e:
        await message.answer("❌ Ошибка. Пример: `10000 15.12.2025`")
    await state.clear()

# 📋 Задачи
@dp.message(F.text == "📋 Задачи")
async def cmd_todos(message: Message):
    todos = await get_todos(message.from_user.id)
    if not todos:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="+ Добавить", callback_data="todo:add")],
            [InlineKeyboardButton(text="← Назад", callback_data="back_to_menu")]
        ])
        await message.answer("📭 Нет задач.", reply_markup=kb)
        return
    
    kb = []
    for t in todos:
        mark = "✅ " if t["is_done"] else ""
        kb.append([InlineKeyboardButton(
            text=f"{mark}{t['text']}", 
            callback_data=f"todo:toggle:{t['id']}"
        )])
    kb.append([InlineKeyboardButton(text="+ Добавить", callback_data="todo:add")])
    kb.append([InlineKeyboardButton(text="← Назад", callback_data="back_to_menu")])
    
    await message.answer("📋 Ваши задачи:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "todo:add")
async def todo_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📝 Введите задачу:")
    await state.set_state(FinanceStates.waiting_for_todo)
    await callback.answer()

@dp.message(FinanceStates.waiting_for_todo)
async def process_todo(message: Message, state: FSMContext):
    await add_todo(message.from_user.id, message.text)
    await message.answer("✅ Задача добавлена!", reply_markup=main_menu)
    await state.clear()

@dp.callback_query(F.data.startswith("todo:toggle:"))
async def toggle_todo(callback: types.CallbackQuery):
    todo_id = int(callback.data.split(":")[2])
    await toggle_todo_done(todo_id)
    await cmd_todos(callback.message)

# ⏰ Напоминания
@dp.message(F.text == "⏰ Напоминания")
async def cmd_remind_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 На дату", callback_data="remind:date")],
        [InlineKeyboardButton(text="← Назад", callback_data="back_to_menu")]
    ])
    await message.answer("🔔 Выберите тип:", reply_markup=kb)

@dp.callback_query(F.data == "remind:date")
async def remind_date_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📝 Введите текст напоминания:")
    await state.set_state(ReminderState.waiting_for_text)
    await callback.answer()

@dp.message(ReminderState.waiting_for_text)
async def remind_get_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("📅 Введите дату и время (пример: `15.12.2025 18:30`):")
    await state.set_state(ReminderState.waiting_for_date)

@dp.message(ReminderState.waiting_for_date)
async def remind_get_date(message: Message, state: FSMContext):
    data = await state.get_data()
    text = data["text"]
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
        await state.update_data(dt=dt)
        await message.answer(
            f"✅ Напоминание: «{text}»\n📅 {dt.strftime('%d.%m.%Y %H:%M')}\nКогда прислать?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="За 1 день", callback_data="remind:1d")],
                [InlineKeyboardButton(text="За 1 час", callback_data="remind:1h")],
                [InlineKeyboardButton(text="Оба", callback_data="remind:both")],
                [InlineKeyboardButton(text="← Назад", callback_data="back_to_menu")]
            ])
        )
        await state.set_state(ReminderState.waiting_for_time_choice)
    except:
        await message.answer("❌ Неверный формат. Пример: `15.12.2025 18:30`")

@dp.callback_query(F.data.startswith("remind:"))
async def remind_schedule(callback: types.CallbackQuery, state: FSMContext):
    choice = callback.data.split(":")[1]
    data = await state.get_data()
    text = data["text"]
    dt = data["dt"]
    user_id = callback.from_user.id
    base_id = f"remind_{user_id}_{int(dt.timestamp())}"
    
    if choice in ["1d", "both"]:
        job_id = f"{base_id}_1d"
        trigger = CronTrigger(
            year=dt.year, month=dt.month, day=dt.day-1,
            hour=dt.hour, minute=dt.minute,
            timezone="Europe/Moscow"
        )
        scheduler.add_job(send_reminder, trigger, [user_id, f"💊 Завтра: {text}"], id=job_id)
    
    if choice in ["1h", "both"]:
        job_id = f"{base_id}_1h"
        trigger = CronTrigger(
            year=dt.year, month=dt.month, day=dt.day,
            hour=dt.hour-1, minute=dt.minute,
            timezone="Europe/Moscow"
        )
        scheduler.add_job(send_reminder, trigger, [user_id, f"⏰ Через час: {text}"], id=job_id)
    
    await callback.message.edit_text("✅ Напоминание установлено!")
    await state.clear()
    await callback.answer()

# 📩 Отправка напоминания
async def send_reminder(user_id: int, text: str):
    try:
        await bot.send_message(user_id, text)
    except Exception as e:
        print(f"[Напоминание] Ошибка {user_id}: {e}")

# ❓ Помощь
@dp.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    await message.answer(
        "📚 Справка:\n"
        "• 💰 Доход — добавить поступление\n"
        "• 🛒 Расход — трата с категорией\n"
        "• 🎯 Цель — `сумма ДД.ММ.ГГГГ`\n"
        "• 📋 Задачи — интерактивный список\n"
        "• ⏰ Напоминания — дата и выбор времени",
        reply_markup=main_menu
    )

# ← Назад
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await cmd_start(callback.message)
    await callback.answer()

# 🚀 Запуск
async def main():
    await init_db()
    scheduler.start()

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