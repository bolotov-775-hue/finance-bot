import asyncio
import os
import logging
from datetime import datetime, date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

from database import *

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
IS_RENDER = os.getenv("RENDER") is not None

class FinanceStates(StatesGroup):
    waiting_for_income = State()
    waiting_for_expense_amount = State()
    waiting_for_expense_category = State()
    waiting_for_expense_subcategory = State()
    waiting_for_goal = State()
    waiting_for_todo = State()

class ReminderState(StatesGroup):
    waiting_for_text = State()
    waiting_for_date = State()
    waiting_for_time_choice = State()

class StatsState(StatesGroup):
    choosing_year = State()
    choosing_month = State()

# 🎨 Кнопки
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Доход"), KeyboardButton(text="🛒 Расход")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🎯 Цель")],
        [KeyboardButton(text="📋 Задачи"), KeyboardButton(text="⏰ Напоминания")],
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

CATEGORIES = {
    "🛒 Продукты": ["молочка", "мясо", "овощи", "выпечка"],
    "💻 Техника": ["ноутбук", "телефон", "аксессуары"],
    "💳 Кредит": ["ежемесячный", "досрочное"],
    "📦 Онлайн": ["Wildberries", "Ozon", "AliExpress"],
    "💊 Лекарства": ["НПВС", "БАДы", "реабилитация"],
    "🚌 Транспорт": ["проезд", "такси", "бензин"],
    "🏠 Быт": ["коммуналка", "ремонт", "мебель"],
    "⚽ Другое": []
}

# 📱 /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await create_user(message.from_user.id)
    await message.answer(
        "👋 Привет! Я — ваш финансовый помощник 💊💰\n"
        "Выберите действие:",
        reply_markup=main_menu
    )

# 💰 Доход
@dp.message(lambda msg: msg.text == "💰 Доход")
async def cmd_income(message: Message, state: FSMContext):
    await message.answer("💸 Введите сумму дохода:")
    await state.set_state(FinanceStates.waiting_for_income)

@dp.message(FinanceStates.waiting_for_income)
async def process_income(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        await add_transaction(message.from_user.id, "income", amount)
        await message.answer(f"✅ Доход +{amount} ₽", reply_markup=main_menu)
    except:
        await message.answer("❌ Введите число.")
    await state.clear()

# 🛒 Расход
@dp.message(lambda msg: msg.text == "🛒 Расход")
async def cmd_expense_menu(message: Message):
    buttons = [
        [InlineKeyboardButton(text=cat, callback_data=f"exp_cat:{cat}")]
        for cat in CATEGORIES.keys()
    ]
    buttons.append([InlineKeyboardButton(text="← Назад", callback_data="back_to_menu")])
    await message.answer(
        "Выберите категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(lambda cb: cb.data.startswith("exp_cat:"))
async def process_category(callback: types.CallbackQuery, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    await state.update_data(category=category)
    
    subs = CATEGORIES[category]
    if not subs:
        await callback.message.edit_text(f"Категория: {category}\nВведите сумму:")
        await state.set_state(FinanceStates.waiting_for_expense_amount)
    else:
        kb = [
            [InlineKeyboardButton(text=sub, callback_data=f"exp_sub:{sub}")]
            for sub in subs
        ] + [[InlineKeyboardButton(text="← Назад", callback_data="back_expense")]]
        await callback.message.edit_text(
            f"Категория: {category}\nВыберите подкатегорию:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
        await state.set_state(FinanceStates.waiting_for_expense_subcategory)
    await callback.answer()

@dp.callback_query(lambda cb: cb.data.startswith("exp_sub:"))
async def process_subcategory(callback: types.CallbackQuery, state: FSMContext):
    subcategory = callback.data.split(":", 1)[1]
    data = await state.get_data()
    category = data["category"]
    await state.update_data(subcategory=subcategory)
    await callback.message.edit_text(f"{category} → {subcategory}\nВведите сумму:")
    await state.set_state(FinanceStates.waiting_for_expense_amount)
    await callback.answer()

@dp.message(FinanceStates.waiting_for_expense_amount)
async def process_expense_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        data = await state.get_data()
        category = data["category"]
        subcategory = data.get("subcategory", "")
        await add_transaction(message.from_user.id, "expense", amount, category, subcategory)
        await message.answer(
            f"✅ Расход {amount} ₽\nКатегория: {category}\nПодкатегория: {subcategory or '—'}",
            reply_markup=main_menu
        )
    except:
        await message.answer("❌ Введите число.")
    await state.clear()

# 📊 Статистика
@dp.message(lambda msg: msg.text == "📊 Статистика")
async def cmd_stats_menu(message: Message):
    await message.answer(
        "📈 Выберите период:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📆 За день", callback_data="stats:day")],
            [InlineKeyboardButton(text="📆 За неделю", callback_data="stats:week")],
            [InlineKeyboardButton(text="📆 За месяц", callback_data="stats:month")],
            [InlineKeyboardButton(text="📆 За год", callback_data="stats:year")],
            [InlineKeyboardButton(text="📅 Выбрать месяц", callback_data="stats:choose_month")],
            [InlineKeyboardButton(text="← Назад", callback_data="back_to_menu")]
        ])
    )

@dp.callback_query(lambda cb: cb.data.startswith("stats:"))
async def process_stats(callback: types.CallbackQuery):
    if cb.data == "stats:choose_month":
        return  # handled separately
    
    period = callback.data.split(":")[1]
    names = {"day": "день", "week": "неделю", "month": "месяц", "year": "год"}
    expenses = await get_expenses_by_period(callback.from_user.id, period)
    
    if not expenses:
        await callback.message.edit_text(f"📭 Нет расходов за {names[period]}.")
        return

    total = sum(row[2] for row in expenses)
    text = f"📉 Расходы за {names[period]}: {total:,.0f} ₽\n\n"
    for cat, sub, amt in expenses:
        sub_text = f" → {sub}" if sub else ""
        bar = "█" * min(10, int(amt / total * 10)) if total > 0 else ""
        text += f"{cat}{sub_text}: {amt:,.0f} ₽ {bar}\n"
    
    await callback.message.edit_text(text)
    await callback.answer()

# === Выбор месяца ===
@dp.callback_query(lambda cb: cb.data == "stats:choose_month")
async def choose_year_start(callback: types.CallbackQuery, state: FSMContext):
    now = datetime.now()
    years = [now.year + i for i in range(-2, 3)]
    kb = [[InlineKeyboardButton(text=str(y), callback_data=f"stats_year:{y}")] for y in years]
    kb.append([InlineKeyboardButton(text="← Назад", callback_data="back_stats_menu")])
    
    await callback.message.edit_text(
        "Выберите год:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )
    await state.set_state(StatsState.choosing_year)
    await callback.answer()

@dp.callback_query(lambda cb: cb.data.startswith("stats_year:"), StatsState.choosing_year)
async def choose_month(callback: types.CallbackQuery, state: FSMContext):
    year = int(callback.data.split(":")[1])
    await state.update_data(year=year)
    
    months = [
        "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
    ]
    kb = []
    for i, m in enumerate(months, 1):
        kb.append([InlineKeyboardButton(text=m, callback_data=f"stats_month:{i}")])
    kb.append([InlineKeyboardButton(text="← Назад", callback_data="stats:choose_month")])
    
    await callback.message.edit_text(
        f"Год: {year}\nВыберите месяц:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )
    await state.set_state(StatsState.choosing_month)
    await callback.answer()

@dp.callback_query(lambda cb: cb.data.startswith("stats_month:"), StatsState.choosing_month)
async def show_month_stats(callback: types.CallbackQuery, state: FSMContext):
    month = int(callback.data.split(":")[1])
    data = await state.get_data()
    year = data["year"]
    user_id = callback.from_user.id
    
    income, expense, top_cats = await get_stats_for_month(user_id, year, month)
    balance = income - expense
    
    month_names = ["", "январь", "февраль", "март", "апрель", "май", "июнь",
                   "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
    
    text = f"📅 **{month_names[month].capitalize()} {year}**\n\n"
    text += f"📥 Доход: **{income:,.0f} ₽**\n"
    text += f"📤 Расход: **{expense:,.0f} ₽**\n"
    text += f"💰 Баланс: **{'+' if balance >= 0 else ''}{balance:,.0f} ₽**\n\n"
    
    if top_cats:
        text += "📉 Топ-5 категорий:\n"
        for i, (cat, amt) in enumerate(top_cats, 1):
            text += f"{i}. {cat}: {amt:,.0f} ₽\n"
    else:
        text += "📭 Нет расходов."

    await callback.message.edit_text(text, parse_mode="Markdown")
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda cb: cb.data == "back_stats_menu")
async def back_to_stats_menu(callback: types.CallbackQuery):
    await cmd_stats_menu(callback.message)
    await callback.answer()

# 🎯 Цель
@dp.message(lambda msg: msg.text == "🎯 Цель")
async def cmd_goal(message: Message, state: FSMContext):
    await message.answer("🎯 Формат: `сумма ДД.ММ.ГГГГ` (пример: `10000 15.12.2025`)")
    await state.set_state(FinanceStates.waiting_for_goal)

@dp.message(FinanceStates.waiting_for_goal)
async def process_goal(message: Message, state: FSMContext):
    try:
        parts = message.text.strip().split(maxsplit=1)
        goal_amount = float(parts[0])
        end_date = datetime.strptime(parts[1], "%d.%m.%Y").date()
        
        if USE_POSTGRES:
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET goal_amount = %s, goal_end_date = %s WHERE user_id = %s",
                        (goal_amount, end_date, message.from_user.id)
                    )
                conn.commit()
        else:
            async with aiosqlite.connect("finance_bot.db") as conn:
                await conn.execute(
                    "UPDATE users SET goal_amount = ?, goal_end_date = ? WHERE user_id = ?",
                    (goal_amount, end_date.isoformat(), message.from_user.id)
                )
                await conn.commit()
        
        await message.answer(
            f"🎯 Цель: {goal_amount:,.0f} ₽ к {end_date.strftime('%d.%m.%Y')}",
            reply_markup=main_menu
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}\nПример: `10000 15.12.2025`")
    await state.clear()

# 📋 Задачи
@dp.message(lambda msg: msg.text == "📋 Задачи")
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
        kb.append([InlineKeyboardButton(text=f"{mark}{t['text']}", callback_data=f"todo:toggle:{t['id']}")])
    kb.append([InlineKeyboardButton(text="+ Добавить", callback_data="todo:add")])
    kb.append([InlineKeyboardButton(text="← Назад", callback_data="back_to_menu")])
    
    await message.answer("📋 Ваши задачи:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(lambda cb: cb.data == "todo:add")
async def todo_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📝 Введите задачу:")
    await state.set_state(FinanceStates.waiting_for_todo)
    await callback.answer()

@dp.message(FinanceStates.waiting_for_todo)
async def process_todo(message: Message, state: FSMContext):
    await add_todo(message.from_user.id, message.text)
    await message.answer("✅ Задача добавлена!", reply_markup=main_menu)
    await state.clear()

@dp.callback_query(lambda cb: cb.data.startswith("todo:toggle:"))
async def toggle_todo(callback: types.CallbackQuery):
    todo_id = int(callback.data.split(":")[2])
    await toggle_todo_done(todo_id)
    await cmd_todos(callback.message)

# ⏰ Напоминания
@dp.message(lambda msg: msg.text == "⏰ Напоминания")
async def cmd_remind_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 На дату", callback_data="remind:date")],
        [InlineKeyboardButton(text="← Назад", callback_data="back_to_menu")]
    ])
    await message.answer("🔔 Выберите тип:", reply_markup=kb)

@dp.callback_query(lambda cb: cb.data == "remind:date")
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

@dp.callback_query(lambda cb: cb.data.startswith("remind:"))
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
        scheduler.add_job(
            lambda: bot.send_message(user_id, f"💊 Завтра: {text}"),
            trigger, id=job_id
        )
    
    if choice in ["1h", "both"]:
        job_id = f"{base_id}_1h"
        trigger = CronTrigger(
            year=dt.year, month=dt.month, day=dt.day,
            hour=dt.hour-1, minute=dt.minute,
            timezone="Europe/Moscow"
        )
        scheduler.add_job(
            lambda: bot.send_message(user_id, f"⏰ Через час: {text}"),
            trigger, id=job_id
        )
    
    await callback.message.edit_text("✅ Напоминание установлено!")
    await state.clear()
    await callback.answer()

# ❓ Помощь
@dp.message(lambda msg: msg.text == "❓ Помощь")
async def cmd_help(message: Message):
    await message.answer(
        "📚 Помощь:\n"
        "• 💰 Доход — поступление средств\n"
        "• 🛒 Расход — с подкатегориями\n"
        "• 📊 Статистика — за периоды и выбранные месяцы\n"
        "• 🎯 Цель — `сумма ДД.ММ.ГГГГ`\n"
        "• 💊 Лекарства — отдельная категория для вас",
        reply_markup=main_menu
    )

# ← Назад
@dp.callback_query(lambda cb: cb.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await cmd_start(callback.message)
    await callback.answer()

@dp.callback_query(lambda cb: cb.data == "back_expense")
async def back_to_expense(callback: types.CallbackQuery):
    await cmd_expense_menu(callback.message)
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