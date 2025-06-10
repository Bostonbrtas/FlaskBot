import time
from sqlalchemy import and_
import os
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
from geopy.distance import geodesic
from urllib.parse import quote
import asyncio
import pytz
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
import aiohttp
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson.objectid import ObjectId

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.types import InputMediaPhoto, InputMediaDocument

from app import app
from mongo_models import db, create_user, create_project, create_report, create_report_photo, create_project_scan
from yadisk_utils import upload_to_yadisk, finalize_report

mongo_client = AsyncIOMotorClient("mongodb://localhost:27017")
db = mongo_client["users_db"]
users_col = db["users"]
reports_col = db["reports"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app.app_context().push()
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env")
TARGET_CHAT_ID = -1
TARGET_THREAD_ID = 1
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния
STATE_CHOOSE = "choose_project"
STATE_READY = "ready_to_start"
STATE_WAIT_LOC = "waiting_location"
STATE_WORKING = "working"
STATE_WAIT_TEXT = "waiting_text"
STATE_WAIT_PHOTOS = "waiting_photos"
STATE_SECOND_GEO = "waiting_second_geo"

# Память состояний
user_states = {}

def push_step(chat, step):
    steps = user_states[chat]["data"].setdefault("step_history", [])
    if not steps or steps[-1] != step:
        steps.append(step)

def pop_step(chat):
    return user_states[chat]["data"].setdefault("step_history", []).pop()

def current_step(chat):
    steps = user_states[chat]["data"].get("step_history", [])
    return steps[-1] if steps else None

from bson import ObjectId

async def finalize_null_report(chat):
    data = user_states[chat]["data"]

    user = await db.users.find_one({
        "telegram_id": str(chat),
        "archived": {"$ne": True}
    })
    if not user or not data.get("start_time") or not data.get("project_id"):
        return

    report = await db.reports.find_one({
        "user_id": user["_id"],
        "project_id": ObjectId(data["project_id"]),
        "start_time": data["start_time"]
    })

    if report:
        await db.reports.update_one(
            {"_id": report["_id"]},
            {"$set": {
                "text_report": "-",
                "photo_link": None,
                "end_time": None
            }}
        )

def finish_report_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton(text="✅ Закончить отправку", callback_data="finish_report"))
    return keyboard

def geo_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить геолокацию",  request_location=True)],
            [KeyboardButton(text="🔙 Шаг назад")]
        ],
        resize_keyboard=True
    )

def working_keyboard(buttons: list[str]) -> ReplyKeyboardMarkup:
    """
    Добавляет к переданным кнопкам кнопку '🔙 Шаг назад'
    """
    full = [[KeyboardButton(text=b)] for b in buttons]
    full.append([KeyboardButton(text="🔙 Шаг назад")])
    return ReplyKeyboardMarkup(keyboard=full, resize_keyboard=True)


async def fix_auto_report_if_needed(chat):
    data = user_states.get(chat, {}).get("data", {})
    if not data.get("start_time") or not data.get("project_id"):
        return

    user = await db.users.find_one({
        "telegram_id": str(chat),
        "archived": {"$ne": True}
    })
    if not user:
        return

    existing = await db.reports.find_one({
        "user_id": user["_id"],
        "project_id": ObjectId(data["project_id"]),
        "start_time": data["start_time"]
    })

    if existing:
        return

    await db.reports.insert_one({
        "user_id": user["_id"],
        "project_id": ObjectId(data["project_id"]),
        "start_time": data["start_time"],
        "end_time": None,
        "text_report": "отчет в разработке",
        "photo_link": None,
        "archived": False
    })

async def delete_last_uploaded_files(data):
    token = os.getenv("YADISK_TOKEN")
    headers = {"Authorization": f"OAuth {token}"}

    async with aiohttp.ClientSession() as session:
        for rel_path in data.get("session_photos", []):
            full_path = "Отчёты/" + rel_path
            try:
                async with session.delete(
                    "https://cloud-api.yandex.net/v1/disk/resources",
                    headers=headers,
                    params={"path": full_path, "permanently": "true"}
                ) as resp:
                    if resp.status >= 400:
                        logger.warning(f"❌ Ошибка удаления файла {full_path}: {resp.status}")
            except Exception as e:
                logger.warning(f"❌ Не удалось удалить файл {full_path}: {e}")

    data.pop("session_photos", None)
    data.pop("media_to_send", None)
    data.pop("last_folder", None)


async def reset_state(chat):
    await fix_auto_report_if_needed(chat)
    if chat in user_states:
        del user_states[chat]

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat = message.chat.id
    await reset_state(chat)

    tid = str(message.from_user.id)
    user = await db.users.find_one({
        "telegram_id": tid,
        "is_active": True,
        "$or": [
            {"archived": {"$exists": False}},
            {"archived": False}
        ]
    })

    if not user:
        await message.answer("❌ Вы не зарегистрированы или были архивированы.")
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚀 Начать")]],
        resize_keyboard=True
    )
    await message.answer("👋 Добро пожаловать! Нажмите «🚀 Начать», чтобы приступить.", reply_markup=kb)

@dp.message(F.text == "🚀 Начать")
async def begin_flow(message: types.Message):
    chat = message.chat.id
    tid = str(message.from_user.id)

    user = await db.users.find_one({
        "telegram_id": tid,
        "is_active": True,
        "$or": [
            {"archived": {"$exists": False}},
            {"archived": False}
        ]
    })

    if not user:
        await message.answer("❌ Вы не зарегистрированы или были архивированы.")
        return

    # Получаем список разрешенных проектов
    allowed_ids = user.get("allowed_projects", [])
    if not allowed_ids:
        await message.answer("⚠️ Вам не назначено ни одного объекта.")
        return

    cursor = db.projects.find({
        "_id": {"$in": allowed_ids},
        "archived": {"$ne": True}
    })
    projects_raw = await cursor.to_list(length=None)

    if not projects_raw:
        await message.answer("⚠️ Нет доступных активных объектов.")
        return

    builder = ReplyKeyboardBuilder()
    project_map = {}

    for p in projects_raw:
        display = f"{p['name'].strip()} ({p['address'].strip()})"
        builder.add(KeyboardButton(text=display))
        project_map[display] = p["_id"]

    builder.adjust(1)

    user_states[chat] = {
        "state": STATE_CHOOSE,
        "data": {
            "projects": project_map,
            "telegram_id": tid
        }
    }

    await message.answer("🏢 Выберите проект:", reply_markup=builder.as_markup(resize_keyboard=True))

@dp.message()
async def AllMessage(message: types.Message):
    chat = message.chat.id
    text = message.text or ""
    state = user_states.get(chat, {}).get("state")
    data = user_states.setdefault(chat, {}).setdefault("data", {})


    if text == "🔙 Шаг назад":
        history = data.get("step_history", [])

        if current_step(chat) == STATE_CHOOSE and not data.get("start_time"):
            await message.answer("🔙 Это минимальный шаг. Пожалуйста, выберите объект.")
            return

        if current_step(chat) == STATE_CHOOSE and data.get("start_time"):
            await finalize_null_report(chat)
            await reset_state(chat)
            await begin_flow(message)
            return

        if len(history) <= 1:
            await message.answer("🔙 Это минимальный шаг. Пожалуйста, выберите объект.")
            return

        last_step = pop_step(chat)
        new_step = current_step(chat)
        user_states[chat]["state"] = new_step

        if last_step == STATE_WAIT_PHOTOS:
            delete_last_uploaded_files(data)
            data.pop("uploaded_photos", None)
            data.pop("media_to_send", None)
            data.pop("last_folder", None)

        if new_step == STATE_CHOOSE:
            await finalize_null_report(chat)
            delete_last_uploaded_files(data)
            data.pop("uploaded_photos", None)
            data.pop("media_to_send", None)
            data.pop("last_folder", None)
            await reset_state(chat)
            await begin_flow(message)
        elif new_step == STATE_WAIT_TEXT:
            await message.answer("🔙 Возврат к вводу текста отчета:")
            await message.answer("📝 Введите текст отчета:")
        elif new_step == STATE_WORKING:
            await message.answer("🔙 Возврат к ожиданию отчета:", reply_markup=working_keyboard(["📝 Отчет"]))
        elif new_step == STATE_WAIT_LOC:
            await message.answer("🔙 Возврат к ожиданию геолокации:", reply_markup=geo_keyboard())
        elif new_step == STATE_READY:
            await message.answer("🔙 Возврат к готовности:", reply_markup=working_keyboard(["🏁 Начать"]))
        elif new_step == STATE_WAIT_PHOTOS:
            await message.answer("🔙 Возврат к отправке фото. Нажмите '✅ Закончить отправку' после загрузки всех фото.")
        elif new_step == STATE_SECOND_GEO:
            await message.answer("🔙 Возврат к повторной геолокации:", reply_markup=geo_keyboard())
        else:
            await message.answer("🔙 Шаг отменён. Продолжайте работу.")
        return

    if state == STATE_CHOOSE:
        projects = data["projects"]
        if text not in projects:
            await message.answer("❌ Неизвестный адрес, выберите кнопкой.")
            return

        pid = projects[text]
        proj = await db.projects.find_one({"_id": pid})
        if not proj:
            await message.answer("❌ Проект не найден.")
            return

        data["project_id"] = pid
        data["ask_location"] = proj.get("ask_location", True)
        push_step(chat, STATE_CHOOSE)

        if proj.get("ask_location", True):
            user_states[chat]["state"] = STATE_READY
            push_step(chat, STATE_READY)
            await message.answer("✅ Вы выбрали проект. Нажмите 🏁 Начать",
                                 reply_markup=working_keyboard(["🏁 Начать"]))
        else:
            data["start_time"] = datetime.now()
            await fix_auto_report_if_needed(chat)
            user_states[chat]["state"] = STATE_WORKING
            await message.answer("✅ Вы выбрали проект. Нажмите 📝 Отчет в конце.",
                                 reply_markup=working_keyboard(["📝 Отчет"]))
        return

    if state == STATE_READY and text == "🏁 Начать":
        data["start_time"] = datetime.now()
        await fix_auto_report_if_needed(chat)

        proj = await db.projects.find_one({"_id": data["project_id"]})
        if not proj:
            await message.answer("❌ Проект не найден.")
            return

        data["target_coords"] = (proj["latitude"], proj["longitude"])
        user_states[chat]["state"] = STATE_WAIT_LOC
        push_step(chat, STATE_WAIT_LOC)
        await message.answer("📍 Отправьте геолокацию:", reply_markup=geo_keyboard())
        return

    if state == STATE_WAIT_LOC and message.location:
        target = data["target_coords"]
        current = (message.location.latitude, message.location.longitude)
        dist = geodesic(target, current).meters
        # Определение метода отправки геолокации
        if hasattr(message.location, "horizontal_accuracy") or hasattr(message.location, "live_period"):
            method = "кнопка"
        else:
            method = "вручную"
        if dist <= 350:
            user_states[chat]["state"] = STATE_WORKING
            push_step(chat, STATE_WORKING)
            await message.answer("✅ Вы на месте! Нажмите 📝 Отчет в конце.", reply_markup=working_keyboard(["📝 Отчет"]))
        else:
            await message.answer(f"❌ Слишком далеко: {dist:.0f} м. Попробуйте ещё раз.", reply_markup=geo_keyboard())
        return

    if state == STATE_SECOND_GEO and message.location:
        target = data["target_coords"]
        current = (message.location.latitude, message.location.longitude)
        dist = geodesic(target, current).meters
        if dist <= 350:
            user_states[chat]["state"] = STATE_WAIT_TEXT
            push_step(chat, STATE_WAIT_TEXT)
            await message.answer("✅ Спасибо, местоположение подтверждено.")
            await message.answer(
                "📝 Введите текст отчета:",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="🔙 Шаг назад")]],
                    resize_keyboard=True
                )
            )
        else:
            await message.answer(f"❌ Слишком далеко: {dist:.0f} м. Попробуйте ещё раз.", reply_markup=geo_keyboard())
        return

    if state == STATE_WORKING and text == "📝 Отчет":
        if data.get("ask_location"):
            user_states[chat]["state"] = STATE_SECOND_GEO
            push_step(chat, STATE_SECOND_GEO)
            await message.answer("📍 Пожалуйста, повторно отправьте геолокацию для подтверждения:",
                                 reply_markup=geo_keyboard())
        else:
            user_states[chat]["state"] = STATE_WAIT_TEXT
            push_step(chat, STATE_WAIT_TEXT)
            await message.answer(
                "📝 Введите текст отчета:",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="🔙 Шаг назад")]],
                    resize_keyboard=True
                )
            )
        return

    if state == STATE_WAIT_TEXT and text:
        data["text_report"] = text
        data["photo_paths"] = []
        user_states[chat]["state"] = STATE_WAIT_PHOTOS
        push_step(chat, STATE_WAIT_PHOTOS)

        finish_kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="✅ Закончить отправку")]],
            resize_keyboard=True
        )
        await message.answer(
            "📸 Теперь отправьте фото-отчет. Когда закончите — нажмите '✅ Закончить отправку'.",
            reply_markup=working_keyboard(["✅ Закончить отправку"])
        )
        return

    if state == STATE_WAIT_PHOTOS and (message.photo or message.document or message.video or message.video_note or message.media_group_id):
        media = []

        # --- 1. Сбор всех фото и документов ---
        if message.photo:
            media.append(("photo", message.photo[-1]))
        elif message.document:
            media.append(("document", message.document))
        elif message.video:
            media.append(("video", message.video))
        elif message.video_note:
            media.append(("video_note", message.video_note))

        for kind, file_obj in media:
            # --- 1. Определение расширения ---
            if kind == "photo":
                ext = "jpg"
            elif kind == "video" or kind == "video_note":
                ext = "mp4"
            else:
                ext = os.path.splitext(file_obj.file_name or "")[1].lstrip(".") or "bin"

            # --- 2. Генерация имени файла ---
            if kind == "photo":
                filename = f"{datetime.now().strftime('%H-%M-%S-%f')}.{ext}"
            elif kind in ("video", "video_note"):
                filename = f"{kind}_{datetime.now().strftime('%H-%M-%S-%f')}.{ext}"
            else:
                filename = getattr(file_obj, "file_name", None) or f"{file_obj.file_id}.{ext}"

            # --- 3. Проверка на дубли ---
            already = data.setdefault("media_to_send", [])
            if any(name == filename for _, _, name in already):
                continue  # такой файл уже был

            # --- 4. Загрузка файла ---
            file_info = await bot.get_file(file_obj.file_id)
            file_bytes = await bot.download_file(file_info.file_path)

            # --- 5. Загрузка в Я.Диск ---
            project = await db.projects.find_one({"_id": data["project_id"]})
            telegram_id = message.from_user.id
            last_folder = await upload_to_yadisk(db, project["name"], telegram_id, file_bytes, filename)
            data["last_folder"] = last_folder

            relpath = last_folder.removeprefix("Отчёты/") + "/" + filename
            data.setdefault("uploaded_photos", []).append(relpath)
            data.setdefault("session_photos", []).append(relpath)
            data["media_to_send"].append((kind, file_obj.file_id, filename))

            # --- 6. Ответ пользователю ---
            if kind == "photo":
                await message.answer(f"📷 Загружено фото: {len(data['media_to_send'])}")
            elif kind == "video":
                await message.answer(f"🎥 Загружено видео: {len(data['media_to_send'])}")
            elif kind == "video_note":
                await message.answer(f"🟠 Загружен кружок: {len(data['media_to_send'])}")
            else:
                await message.answer(f"📄 Загружен файл «{filename}»: {len(data['media_to_send'])}")

        return

    # --- Блок "✅ Закончить отправку" (STATE_WAIT_PHOTOS + текст) ---
    if state == STATE_WAIT_PHOTOS and message.text == "✅ Закончить отправку":
        push_step(chat, STATE_WAIT_PHOTOS)

        user_record = await db.users.find_one({"telegram_id": str(message.from_user.id)})
        proj = await db.projects.find_one({"_id": data["project_id"]})
        last_folder = data.get("last_folder")
        public_url = finalize_report(last_folder)

        existing_report = await db.reports.find_one({
            "user_id": user_record["_id"],
            "project_id": proj["_id"],
            "start_time": data["start_time"]
        })

        report_data = {
            "user_id": user_record["_id"],
            "project_id": proj["_id"],
            "start_time": data["start_time"],
            "end_time": datetime.now(),
            "text_report": data.get("text_report"),
            "photo_link": public_url,
            "archived": False,
            "entry_location_method": data.get("entry_location_method", "—"),
            "exit_location_method": data.get("exit_location_method", "—"),
        }

        if existing_report:
            await db.reports.update_one(
                {"_id": existing_report["_id"]},
                {"$set": report_data}
            )
            report_id = existing_report["_id"]
        else:
            result = await db.reports.insert_one(report_data)
            report_id = result.inserted_id

        for rel in data.get("uploaded_photos", []):
            await db.report_photos.insert_one({
                "report_id": report_id,
                "photo_path": rel
            })

        msg = (
            f"👷 Сотрудник: {user_record.get('surname')} {user_record.get('name')}\n"
            f"🏢 Объект: {proj.get('name')}\n"
            f"🕑 начало: {data['start_time'].strftime('%d.%m.%Y %H:%M')}\n"
            f"🕑 конец: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
            f"✏️ Текст отчета: {data.get('text_report') or '—'}\n"
            f"Фото:"
        )

        await bot.send_message(chat_id=message.from_user.id, text=msg, parse_mode="HTML", disable_web_page_preview=True)
        await bot.send_message(chat_id=TARGET_CHAT_ID, message_thread_id=TARGET_THREAD_ID, text=msg, parse_mode="HTML",
                               disable_web_page_preview=True)

        photos = [
            InputMediaPhoto(media=file_id)
            for kind, file_id, _ in data.get("media_to_send", [])
            if kind == "photo"
       ]
        docs = [
            InputMediaDocument(media=file_id, caption=filename)
            for kind, file_id, filename in data.get("media_to_send", [])
            if kind == "document"
        ]

        if photos:
            await bot.send_media_group(chat_id=TARGET_CHAT_ID, message_thread_id=TARGET_THREAD_ID, media=photos)
            await bot.send_media_group(chat_id=message.from_user.id, media=photos)

        if docs:
            await bot.send_media_group(chat_id=TARGET_CHAT_ID, message_thread_id=TARGET_THREAD_ID, media=docs)
            await bot.send_media_group(chat_id=message.from_user.id, media=docs)

        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚀 Начать")]], resize_keyboard=True)
        await message.answer("✅ Отчет сохранен.", reply_markup=kb)
        await reset_state(chat)
        return

    if state == STATE_WAIT_PHOTOS and message.text:
        push_step(chat, STATE_WAIT_PHOTOS)
        data["text_report"] = message.text
        await message.answer("✏️ Текст отчета сохранен.")
        return

    # Финальная защита — неизвестная команда
    if chat == TARGET_CHAT_ID:
        return  # ⛔️ Не реагируем в чат отчётов

    await message.answer("❌ Неизвестная команда. Нажмите /start")

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())