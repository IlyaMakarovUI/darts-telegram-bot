import asyncio
import sqlite3
from datetime import datetime, timedelta
import os

import pandas as pd
import matplotlib.pyplot as plt

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery
)
from aiogram.filters import Command

# ---------- CONFIG ----------
TOKEN = os.getenv("BOT_TOKEN")
TRAINING_DURATION = 600  # 10 минут

# ---------- BOT ----------
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ---------- DATABASE ----------
conn = sqlite3.connect("darts.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS throws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    rating TEXT,
    timestamp DATETIME
)
""")
conn.commit()

# ---------- STATE ----------
active_sessions = set()

# ---------- KEYBOARDS ----------
start_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="▶️ Старт тренировки", callback_data="start")],
    [
        InlineKeyboardButton(text="📊 За неделю", callback_data="week"),
        InlineKeyboardButton(text="📈 График прогресса", callback_data="graph")
    ]
])

throw_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="❌ Плохо", callback_data="bad"),
        InlineKeyboardButton(text="⚖️ Средне", callback_data="ok"),
        InlineKeyboardButton(text="⭐ Отлично", callback_data="good")
    ]
])

# ---------- COMMANDS ----------
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "🎯 Тренировки по дартсу\n\n"
        "▶️ Старт — 10 минут\n"
        "После каждого сета из 3 дротиков выбери оценку.",
        reply_markup=start_kb
    )

@dp.callback_query(F.data == "start")
async def start_training(call: CallbackQuery):
    user_id = call.from_user.id

    if user_id in active_sessions:
        await call.answer("Тренировка уже идёт")
        return

    active_sessions.add(user_id)

    await call.message.answer(
        "⏱ Тренировка началась (10 минут)",
        reply_markup=throw_kb
    )

    asyncio.create_task(finish_training(user_id, call.message.chat.id))

async def finish_training(user_id: int, chat_id: int):
    await asyncio.sleep(TRAINING_DURATION)

    active_sessions.discard(user_id)

    since = datetime.now() - timedelta(seconds=TRAINING_DURATION)

    cursor.execute("""
        SELECT rating, COUNT(*) FROM throws
        WHERE user_id = ? AND timestamp >= ?
        GROUP BY rating
    """, (user_id, since))

    data = dict(cursor.fetchall())

    await bot.send_message(
        chat_id,
        "⏱ Тренировка завершена\n\n"
        f"❌ Плохо — {data.get('bad', 0)}\n"
        f"⚖️ Средне — {data.get('ok', 0)}\n"
        f"⭐ Отлично — {data.get('good', 0)}",
        reply_markup=start_kb
    )

@dp.callback_query(F.data.in_(["bad", "ok", "good"]))
async def register_throw(call: CallbackQuery):
    if call.from_user.id not in active_sessions:
        await call.answer("Сначала нажми «Старт»")
        return

    cursor.execute(
        "INSERT INTO throws (user_id, rating, timestamp) VALUES (?, ?, ?)",
        (call.from_user.id, call.data, datetime.now())
    )
    conn.commit()

    await call.answer("✓ Записано")

@dp.callback_query(F.data == "week")
async def week_stats(call: CallbackQuery):
    since = datetime.now() - timedelta(days=7)

    cursor.execute("""
        SELECT rating, COUNT(*) FROM throws
        WHERE user_id = ? AND timestamp >= ?
        GROUP BY rating
    """, (call.from_user.id, since))

    data = dict(cursor.fetchall())

    await call.message.answer(
        "📊 Статистика за 7 дней\n\n"
        f"❌ Плохо — {data.get('bad', 0)}\n"
        f"⚖️ Средне — {data.get('ok', 0)}\n"
        f"⭐ Отлично — {data.get('good', 0)}"
    )

@dp.callback_query(F.data == "graph")
async def progress_graph(call: CallbackQuery):
    since = datetime.now() - timedelta(days=14)

    df = pd.read_sql_query("""
        SELECT date(timestamp) AS day, rating, COUNT(*) AS count
        FROM throws
        WHERE user_id = ? AND timestamp >= ?
        GROUP BY day, rating
        ORDER BY day
    """, conn, params=(call.from_user.id, since))

    if df.empty:
        await call.message.answer("Нет данных для графика")
        return

    pivot = df.pivot(index="day", columns="rating", values="count").fillna(0)

    plt.figure(figsize=(8, 4))
    plt.plot(pivot.index, pivot.get("bad", []), label="Плохо")
    plt.plot(pivot.index, pivot.get("ok", []), label="Средне")
    plt.plot(pivot.index, pivot.get("good", []), label="Отлично")

    plt.title("Прогресс тренировок (14 дней)")
    plt.xlabel("Дата")
    plt.ylabel("Количество")
    plt.legend()
    plt.grid(True)

    file_path = "progress.png"
    plt.tight_layout()
    plt.savefig(file_path)
    plt.close()

    await bot.send_photo(
        call.message.chat.id,
        photo=open(file_path, "rb"),
        caption="📈 Прогресс тренировок за 14 дней"
    )

# ---------- RUN ----------
if __name__ == "__main__":
    dp.run_polling(bot)
