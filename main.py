
import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from geopy.distance import geodesic

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from app import app, db
from models import User, Project, Report, ReportPhoto

app.app_context().push()
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния
STATE_CHOOSE = "choose_project"
STATE_READY = "ready_to_start"
STATE_WAIT_LOC = "waiting_location"
STATE_WORKING = "working"
STATE_WAIT_TEXT = "waiting_text"
STATE_WAIT_PHOTO_COUNT = "waiting_photo_count"
STATE_WAIT_PHOTOS = "waiting_photos"

# Память состояний
user_states = {}

# Гео-кнопка
loc_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
    resize_keyboard=True
)

def reset_state(chat_id):
    user_states.pop(chat_id, None)

def save_photo(telegram_id, file_id):
    folder = os.path.join("static", "reports", str(telegram_id))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{file_id}.jpg")
    rel = f"reports/{telegram_id}/{file_id}.jpg"
    return path, rel

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat = message.chat.id
    reset_state(chat)

    tid = str(message.from_user.id)
    user = db.session.query(User).filter_by(telegram_id=tid, is_active=True).first()
    if not user:
        await message.answer("❌ Вы не зарегистрированы.")
        return

    projects = db.session.query(Project).all()
    builder = ReplyKeyboardBuilder()
    for p in projects:
        builder.add(KeyboardButton(text=f"{p.name}, {p.address}"))
    builder.adjust(1)

    user_states[chat] = {"state": STATE_CHOOSE, "data": {
        "projects": {f"{p.name}, {p.address}": p.id for p in projects}
    }}

    await message.answer("🏢 Выберите проект:", reply_markup=builder.as_markup(resize_keyboard=True))

@dp.message()
async def AllMessage(message: types.Message):
    chat = message.chat.id
    text = message.text or ""
    state = user_states.get(chat, {}).get("state")
    data = user_states.setdefault(chat, {}).setdefault("data", {})

    if state == STATE_CHOOSE:
        projects = data["projects"]
        if text not in projects:
            await message.answer("❌ Неизвестный адрес, выберите кнопкой.")
            return

        pid = projects[text]
        proj = db.session.get(Project, pid)
        data["project_id"] = pid
        data["ask_location"] = proj.ask_location

        if proj.ask_location:
            user_states[chat]["state"] = STATE_READY
            await message.answer("✅ Вы выбрали проект. Нажмите 🏁 Начать", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🏁 Начать")]], resize_keyboard=True))
        else:
            user_states[chat]["state"] = STATE_WORKING
            await message.answer("✅ Вы выбрали проект. Нажмите 📝 Отчет в конце.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📝 Отчет")]], resize_keyboard=True))
        return

    if state == STATE_READY and text == "🏁 Начать":
        proj = db.session.get(Project, data["project_id"])
        data["target_coords"] = (proj.latitude, proj.longitude)
        user_states[chat]["state"] = STATE_WAIT_LOC
        await message.answer("📍 Отправьте геолокацию:", reply_markup=loc_kb)
        return

    if state == STATE_WAIT_LOC and message.location:
        target = data["target_coords"]
        current = (message.location.latitude, message.location.longitude)
        dist = geodesic(target, current).meters
        if dist <= 250:
            data["start_time"] = datetime.now()
            user_states[chat]["state"] = STATE_WORKING
            await message.answer("✅ Вы на месте! Нажмите 📝 Отчет в конце.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text = "📝 Отчет")]], resize_keyboard=True))
        else:
            await message.answer(f"❌ Слишком далеко: {dist:.0f} м. Попробуйте ещё раз.", reply_markup=loc_kb)
        return

    if state == STATE_WORKING and text == "📝 Отчет":
        user_states[chat]["state"] = STATE_WAIT_TEXT
        await message.answer("📝 Введите текст отчета:", reply_markup=ReplyKeyboardRemove())
        return

    if state == STATE_WAIT_TEXT and text:
        data["text_report"] = text
        user_states[chat]["state"] = STATE_WAIT_PHOTO_COUNT
        await message.answer("📸 Сколько фото вы хотите отправить?")
        return

    if state == STATE_WAIT_PHOTO_COUNT and text.isdigit():
        count = int(text)
        if count < 1:
            await message.answer("❌ Укажите положительное число.")
            return
        data["photo_total"] = count
        data["photo_received"] = 0
        data["photo_paths"] = []
        user_states[chat]["state"] = STATE_WAIT_PHOTOS
        await message.answer(f"📤 Жду {count} фото.")
        return

    if state == STATE_WAIT_PHOTOS and message.photo:
        uid = db.session.query(User).filter_by(telegram_id=str(message.from_user.id)).first().id
        telegram_id = message.from_user.id

        # берем только самое качественное фото
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        path, rel = save_photo(telegram_id, photo.file_id)
        await bot.download_file(file.file_path, path)
        data["photo_paths"].append(rel)

        total = data["photo_total"]
        recvd = len(data["photo_paths"])

        if recvd >= total:
            report = Report(
                user_id=uid,
                project_id=data["project_id"],
                start_time=data.get("start_time") or datetime.now(),
                end_time=datetime.now(),
                text_report=data["text_report"]
            )
            db.session.add(report)
            db.session.flush()

            for rel in data["photo_paths"]:
                db.session.add(ReportPhoto(report_id=report.id, photo_path=rel))

            db.session.commit()
            await message.answer("✅ Отчет сохранен!", reply_markup=ReplyKeyboardRemove())
            reset_state(chat)
        else:
            await message.answer(f"📷 Фото {recvd} из {total}, жду еще...")
        return

    await message.answer("❌ Неизвестная команда. Нажмите /start")

def start():
    import asyncio
    asyncio.run(dp.start_polling(bot))

if __name__ == "__main__":
    start()
