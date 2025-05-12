
import os
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
from geopy.distance import geodesic

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
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
STATE_WAIT_PHOTOS = "waiting_photos"

# Память состояний
user_states = {}

def finish_report_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton(text = "✅ Закончить отправку", callback_data="finish_report"))
    return keyboard

# Гео-кнопка
loc_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
    resize_keyboard=True
)


def upload_to_yadisk(project_name, telegram_id, file_bytes, filename):
    token = os.getenv("YADISK_TOKEN")
    headers = {"Authorization": f"OAuth {token}"}

    safe_project_name = project_name.replace(" ", "_").replace("/", "_")
    root_folder = safe_project_name
    user_folder = f"{safe_project_name}/{telegram_id}"
    remote_path = f"{user_folder}/{filename}"

    folder_url = "https://cloud-api.yandex.net/v1/disk/resources"
    requests.put(folder_url, headers=headers, params={"path": root_folder})
    requests.put(folder_url, headers=headers, params={"path": user_folder})

    response = requests.get(
        f"{folder_url}/upload",
        headers=headers,
        params={"path": remote_path, "overwrite": "true"}
    )

    if response.status_code != 200:
        print("Ошибка при запросе upload_url:", response.status_code, response.text)
        raise Exception("Не удалось получить ссылку для загрузки")

    upload_url = response.json().get("href")
    requests.put(upload_url, data=file_bytes)

    return f"https://disk.yandex.ru/client/disk/{user_folder}"


def fix_auto_report_if_needed(chat):
    data = user_states.get(chat, {}).get("data", {})
    if data.get("start_time") and data.get("project_id"):
        user = db.session.query(User).filter_by(telegram_id=str(chat)).first()
        if not user:
            return

        existing = db.session.query(Report).filter_by(
            user_id=user.id,
            project_id=data["project_id"],
            start_time=data["start_time"]
        ).first()

        if existing:
            return

        report = Report(
            user_id=user.id,
            project_id=data["project_id"],
            start_time=data["start_time"],
            end_time=datetime.now(),
            text_report=None,
            photo_link=None
        )
        db.session.add(report)
        db.session.commit()


def reset_state(chat):
    fix_auto_report_if_needed(chat)
    if chat in user_states:
        del user_states[chat]


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
            await message.answer("✅ Вы выбрали проект. Нажмите 🏁 Начать",
                                 reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🏁 Начать")]],
                                                                  resize_keyboard=True))
        else:
            data["start_time"] = datetime.now()  # ✅ фиксируем сразу для проектов без гео
            user_states[chat]["state"] = STATE_WORKING
            await message.answer("✅ Вы выбрали проект. Нажмите 📝 Отчет в конце.",
                                 reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📝 Отчет")]],
                                                                  resize_keyboard=True))
        return

    if state == STATE_READY and text == "🏁 Начать":
        data["start_time"] = datetime.now()  # ✅ фиксируем только здесь
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
        data["photo_paths"] = []
        user_states[chat]["state"] = STATE_WAIT_PHOTOS

        finish_kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="✅ Закончить отправку")]],
            resize_keyboard=True
        )
        await message.answer(
            "📸 Теперь отправьте фото-отчет. Когда закончите — нажмите '✅ Закончить отправку'.",
            reply_markup=finish_kb
        )
        return

    if state == STATE_WAIT_PHOTOS and message.photo:
        uid = db.session.query(User).filter_by(telegram_id=str(message.from_user.id)).first().id
        telegram_id = message.from_user.id
        project = db.session.get(Project, data["project_id"])

        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)

        filename = f"{photo.file_id}.jpg"
        remote_url = upload_to_yadisk(project.name, telegram_id, file_bytes, filename)

        data.setdefault("uploaded_photos", []).append(f"{project.name}/{telegram_id}/{filename}")

        await message.answer(f"📷 Фото загружено. Всего: {len(data['uploaded_photos'])}")
        return

    if state == STATE_WAIT_PHOTOS and message.text == "✅ Закончить отправку":
        uid = db.session.query(User).filter_by(telegram_id=str(message.from_user.id)).first().id
        project = db.session.get(Project, data["project_id"])

        safe_project_name = project.name.replace(" ", "_").replace("/", "_")
        photo_link = f"https://disk.yandex.ru/client/disk/{safe_project_name}/{message.from_user.id}"

        report = Report(
            user_id=uid,
            project_id=project.id,
            start_time=data.get("start_time") or datetime.now(),
            end_time=datetime.now(),
            text_report=data["text_report"],
            photo_link=photo_link
        )
        db.session.add(report)
        db.session.flush()

        for path in data.get("uploaded_photos", []):
            db.session.add(ReportPhoto(report_id=report.id, photo_path=path))

        db.session.commit()
        user_states[chat]["data"].pop("start_time", None)
        await message.answer("✅ Отчет сохранен!", reply_markup=ReplyKeyboardRemove())
        reset_state(chat)
        return

    if state == STATE_WAIT_PHOTOS and message.text:
        await message.answer("📸 Отправьте фотографии или нажмите '✅ Закончить отправку'.")
        return

        # Финальная защита — неизвестная команда
    await message.answer("❌ Неизвестная команда. Нажмите /start")


def start():
    import asyncio
    asyncio.run(dp.start_polling(bot))

if __name__ == "__main__":
    start()
