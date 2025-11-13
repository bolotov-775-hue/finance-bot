import asyncio
import os
import logging
from datetime import datetime, date
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
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

# 🎨 Главное меню с кнопкой лимита
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Доход"), KeyboardButton(text="🛒 Расход")],
        [KeyboardButton(text="🎯 Цель"), KeyboardButton(text="📊 Лимит на день")],  # ← ОТДЕЛЬНАЯ КНОПКА
        [KeyboardButton(text="📈 Статистика")]
    ],
    resize_keyboard=True
)

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
        await add_transaction(message.from_user.id, "income", amount)
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
        await add_transaction(message.from_user.id, "expense", amount)
        
        # Рассчитываем лимит и показываем остаток
        goal_amount, goal_end_date = await get_user_goal(message.from_user.id)
        if goal_amount and goal_end_date:
            try:
                end_date = date.fromisoformat(goal_end_date) if isinstance(goal_end_date, str) else goal_end_date
                days_left = (end_date - date.today()).days
                if days_left > 0:
                    income = await get_total_income(message.from_user.id)
                    to_save = max(0, goal_amount)
                    daily_limit = max(0, (income - to_save) / days_left)
                    spent_today = await get_today_expenses(message.from_user.id)
                    left = max(0, daily_limit - spent_today)
                    await message.answer(f"✅ Расход {amount} ₽\n📆 Осталось на сегодня: {left:.2f} ₽", reply_markup=main_menu)
                    return
            except:
                pass
        await message.answer(f"✅ Расход {amount} ₽", reply_markup=main_menu)
    except Exception as e:
        await message.answer("❌ Введите число.")
    await state.clear()

# 🎯 Цель
@dp.message(lambda m: m.text == "🎯 Цель")
async def goal(message: Message, state: FSMContext):
    await message.answer("🎯 Формат: `сумма ДД.ММ.ГГГГ` (пример: `10000 15.12.2025`)")
    await state.set_state(States.goal)

@dp.message(States.goal)
async def process_goal(message: Message, state: FSMContext):
    try:
        parts = message.text.strip().split(maxsplit=1)
        amount = float(parts[0])
        end_date = datetime.strptime(parts[1], "%d.%m.%Y").date()
        await set_goal(message.from_user.id, amount, end_date)
        await message.answer(f"🎯 Цель: накопить {amount:.0f} ₽ к {end_date.strftime('%d.%m.%Y')}", reply_markup=main_menu)
    except Exception as e:
        await message.answer("❌ Ошибка. Пример: `10000 15.12.2025`")
    await state.clear()

# 📊 Лимит на день — ОТДЕЛЬНАЯ КНОПКА
@dp.message(lambda m: m.text == "📊 Лимит на день")
async def daily_limit(message: Message):
    goal_amount, goal_end_date = await get_user_goal(message.from_user.id)
    if not goal_amount or not goal_end_date:
        await message.answer("❗ Сначала установите цель через кнопку «🎯 Цель».", reply_markup=main_menu)
        return

    try:
        # Преобразуем дату
        end_date = date.fromisoformat(goal_end_date) if isinstance(goal_end_date, str) else goal_end_date
        days_left = (end_date - date.today()).days
        if days_left <= 0:
            await message.answer("🎯 Срок цели истёк. Установите новую цель.", reply_markup=main_menu)
            return

        income = await get_total_income(message.from_user.id)
        to_save = goal_amount  # упрощённо: цель = сумма к накоплению
        daily_limit = max(0, (income - to_save) / days_left)
        spent_today = await get_today_expenses(message.from_user.id)
        left = max(0, daily_limit - spent_today)

        await message.answer(
            f"📊 Лимит на день:\n"
            f"🎯 Цель: {goal_amount:.0f} ₽ к {end_date.strftime('%d.%m.%Y')}\n"
            f"💰 Доходов: {income:.0f} ₽\n"
            f"📆 Осталось дней: {days_left}\n"
            f"📌 Дневной лимит: {daily_limit:.2f} ₽\n"
            f"🛒 Потрачено сегодня: {spent_today:.2f} ₽\n"
            f"➡️ Осталось: {left:.2f} ₽",
            reply_markup=main_menu
        )
    except Exception as e:
        await message.answer("❌ Ошибка расчёта лимита.", reply_markup=main_menu)

# 📈 Статистика
@dp.message(lambda m: m.text == "📈 Статистика")
async def stats(message: Message):
    balance = await get_balance(message.from_user.id)
    income = await get_total_income(message.from_user.id)
    await message.answer(
        f"📈 Статистика:\n"
        f"💰 Баланс: {balance:.2f} ₽\n"
        f"📥 Доходы: {income:.2f} ₽",
        reply_markup=main_menu
    )

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
        print(f"Running on port {port}")

    print("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())