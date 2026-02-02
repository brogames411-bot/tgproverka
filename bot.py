import asyncio
import os
from typing import Optional

import aiosqlite
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ================== ENV ==================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL")
CHANNEL_LINK = os.getenv("CHANNEL_LINK")

BONUS_FILE = os.getenv("BONUS_FILE", "images.jpg")
BONUS_CAPTION = os.getenv("BONUS_CAPTION", "🎁 Спасибо за подписку! Вот твой файл.(Файл выдается один раз, при повторной подписке на канал файл не будет выдан)")

ADMINS = set(
    int(x.strip()) for x in os.getenv("ADMINS", "").split(",")
    if x.strip().isdigit()
)

DB_PATH = "users.db"

# ================== DISPATCHER ==================
dp = Dispatcher(storage=MemoryStorage())

# ================== FSM ==================
class Broadcast(StatesGroup):
    waiting_text = State()
    waiting_confirm = State()

# ================== KEYBOARDS ==================
def gate_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Подписаться", url=CHANNEL_LINK)
    kb.button(text="✅ Проверить подписку", callback_data="check_sub")
    kb.adjust(1)
    return kb.as_markup()

def open_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Открыть меню", callback_data="open_menu")
    kb.adjust(1)
    return kb.as_markup()

def menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🧩 Закрытая кнопка", callback_data="secret_btn")
    kb.adjust(1)
    return kb.as_markup()

# ================== HELPERS ==================
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                bonus_sent INTEGER DEFAULT 0
            )
        """)
        await db.commit()

async def save_user(user_id: int, username: Optional[str], first_name: Optional[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id, username, first_name) VALUES(?,?,?)",
            (user_id, username, first_name),
        )
        await db.commit()

async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]

async def is_bonus_sent(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT bonus_sent FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
    return bool(row and row[0] == 1)

async def mark_bonus_sent(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET bonus_sent=1 WHERE user_id=?", (user_id,))
        await db.commit()

async def send_bonus_file(bot: Bot, user_id: int):
    doc = FSInputFile(BONUS_FILE)
    await bot.send_document(user_id, doc, caption=BONUS_CAPTION)

async def is_subscribed(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in ("creator", "administrator", "member")
    except TelegramBadRequest:
        return False

async def ensure_access_callback(call: CallbackQuery) -> bool:
    ok = await is_subscribed(call.bot, call.from_user.id)
    if not ok:
        await call.answer("🔒 Сначала подпишись!", show_alert=True)
        await call.message.edit_text(
            "Подпишись на канал и нажми «Проверить подписку».",
            reply_markup=gate_kb()
        )
    return ok

# ================== USER COMMANDS ==================
@dp.message(Command("id"))
async def my_id(message: Message):
    await message.answer(f"Ваш user_id: {message.from_user.id}")

@dp.message(Command("start"))
async def start(message: Message):
    await save_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

    ok = await is_subscribed(message.bot, message.from_user.id)

    if ok:
        await message.answer(
            "✅ Ты уже подписан! Нажми кнопку ниже:",
            reply_markup=open_menu_kb()
        )
    else:
        await message.answer(
            "Привет! 👋\n\n"
            "Чтобы получить доступ — подпишись на канал и нажми «Проверить подписку».",
            reply_markup=gate_kb()
        )

@dp.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery):
    ok = await is_subscribed(call.bot, call.from_user.id)

    if ok:
        await call.message.edit_text(
            "✅ Подписка подтверждена!\nЖми «Открыть меню».",
            reply_markup=open_menu_kb()
        )

        # 🎁 выдаём файл только один раз
        if not await is_bonus_sent(call.from_user.id):
            await send_bonus_file(call.bot, call.from_user.id)
            await mark_bonus_sent(call.from_user.id)

    else:
        await call.answer("❌ Подписка не найдена!", show_alert=True)

@dp.callback_query(F.data == "open_menu")
async def open_menu(call: CallbackQuery):
    if not await ensure_access_callback(call):
        return
    await call.message.edit_text("🎉 Меню открыто!", reply_markup=menu_kb())
    await call.answer()

@dp.callback_query(F.data == "secret_btn")
async def secret_btn(call: CallbackQuery):
    if not await ensure_access_callback(call):
        return
    await call.message.edit_text("🔥 Ты нажал закрытую кнопку!")
    await call.answer()

# ================== ADMIN PANEL ==================
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "🛠 Админ-панель:\n"
        "• /stats — статистика\n"
        "• /broadcast — рассылка\n"
        "• /cancel — отменить"
    )

@dp.message(Command("stats"))
async def stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    users = await get_all_user_ids()
    await message.answer(f"👥 Пользователей в базе: {len(users)}")

@dp.message(Command("broadcast"))
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(Broadcast.waiting_text)
    await message.answer("✉️ Пришли текст рассылки.")

@dp.message(Broadcast.waiting_text)
async def broadcast_get_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await state.set_state(Broadcast.waiting_confirm)
    await message.answer("Подтверди отправку: напиши YES или /cancel")

@dp.message(Broadcast.waiting_confirm)
async def broadcast_confirm(message: Message, state: FSMContext):
    if message.text.upper() != "YES":
        await message.answer("Не подтверждено.")
        return

    data = await state.get_data()
    text = data["text"]
    await state.clear()

    user_ids = await get_all_user_ids()

    await message.answer("🚀 Рассылка началась...")

    for uid in user_ids:
        try:
            await message.bot.send_message(uid, text)
            await asyncio.sleep(0.05)
        except:
            pass

    await message.answer("✅ Рассылка завершена!")

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.")

# ================== MAIN ==================
async def main():
    bot = Bot(BOT_TOKEN)
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
