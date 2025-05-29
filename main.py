import time
import os
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
from geopy.distance import geodesic
from urllib.parse import quote

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.types import InputMediaPhoto, InputMediaDocument


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

def upload_to_yadisk(project_name: str, telegram_id: int, file_bytes: bytes, filename: str) -> str:
    """
    Загружает файл на Я.Диск в папку Отчёты/Проект/Дата/ФИО и возвращает путь этой папки.
    """
    token = os.getenv("YADISK_TOKEN")
    headers = {"Authorization": f"OAuth {token}"}

    common_root = "Отчёты"
    safe_proj   = project_name.replace(" ", "_").replace("/", "_")
    date_folder = datetime.now().date().isoformat()
    user = db.session.query(User).filter_by(telegram_id=str(telegram_id)).first()
    surname = user.surname.replace(" ", "_") if user and user.surname else str(telegram_id)

    last_folder = f"{common_root}/{safe_proj}/{date_folder}/{surname}"

    # создаём иерархию папок
    for path in [
        common_root,
        f"{common_root}/{safe_proj}",
        f"{common_root}/{safe_proj}/{date_folder}",
        last_folder
    ]:
        requests.put(
            "https://cloud-api.yandex.net/v1/disk/resources",
            headers=headers,
            params={"path": path}
        )

    # загружаем файл
    upload_resp = requests.get(
        "https://cloud-api.yandex.net/v1/disk/resources/upload",
        headers=headers,
        params={"path": f"{last_folder}/{filename}", "overwrite": "true"}
    )
    upload_resp.raise_for_status()
    upload_url = upload_resp.json()["href"]
    requests.put(upload_url, data=file_bytes)

    return last_folder



def finalize_report(last_folder: str) -> str | None:
    """
    Делаем публичной только эту папку last_folder
    и возвращаем прямую ссылку на неё.
    """
    if not last_folder:
        return None

    token = os.getenv("YADISK_TOKEN")
    headers = {"Authorization": f"OAuth {token}"}
    base_url = "https://cloud-api.yandex.net/v1/disk/resources"

    # 1) Публикуем вашу целевую папку
    publish_resp = requests.put(
        f"{base_url}/publish",
        headers=headers,
        params={"path": last_folder}
    )
    publish_resp.raise_for_status()

    # 2) Получаем public_url этой же папки
    info_resp = requests.get(
        base_url,
        headers=headers,
        params={"path": last_folder, "fields": "public_url"}
    )
    info_resp.raise_for_status()
    return info_resp.json().get("public_url")

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
    # Ищем только неархивированных активных пользователей
    user = db.session.query(User).filter_by(
        telegram_id=tid,
        is_active=True,
        archived=False
    ).first()
    if not user:
        await message.answer("❌ Вы не зарегистрированы или были архивированы.")
        return

    # Показываем только неархивные проекты
    projects = db.session.query(Project).filter_by(archived=False).all()
    builder = ReplyKeyboardBuilder()
    for p in projects:
        builder.add(KeyboardButton(text=f"{p.name}, {p.address}"))
    builder.adjust(1)

    user_states[chat] = {
        "state": STATE_CHOOSE,
        "data": {"projects": {f"{p.name}, {p.address}": p.id for p in projects}}
    }

    await message.answer(
        "🏢 Выберите проект:",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )

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

    # ОБРАБОТКА ФОТО И ЛЮБЫХ ДОКУМЕНТОВ
    if state == STATE_WAIT_PHOTOS and (message.photo or message.document):
        if message.photo:
            file_obj = message.photo[-1]
            kind = 'photo'
            filename = "Фото"
        else:
            file_obj = message.document
            kind = 'document'
            filename = message.document.file_name or file_obj.file_id

        file_info = await bot.get_file(file_obj.file_id)
        file_bytes = await bot.download_file(file_info.file_path)

        project = db.session.get(Project, data["project_id"])
        telegram_id = message.from_user.id
        last_folder = upload_to_yadisk(project.name, telegram_id, file_bytes, filename)
        data["last_user_folder"] = last_folder

        relpath = f"{last_folder}/{filename}"
        data.setdefault("uploaded_photos", []).append(relpath)
        data.setdefault("media_to_send", []).append((kind, file_obj.file_id))

        total = len(data["media_to_send"])
        await message.answer(f"📎 Файл «{filename}» загружен. Всего: {total}")
        return

    if state == STATE_WAIT_PHOTOS and text == "✅ Закончить отправку":
        user_record = db.session.query(User).filter_by(telegram_id=str(message.from_user.id)).first()
        proj = db.session.get(Project, data["project_id"])
        last_folder = data.get("last_user_folder")
        public_url = finalize_report(last_folder)

        report = Report(
            user_id=user_record.id,
            project_id=proj.id,
            start_time=data["start_time"],
            end_time=datetime.now(),
            text_report=data.get("text_report"),
            photo_link=public_url
        )
        db.session.add(report)
        db.session.flush()
        for rel in data.get("uploaded_photos", []):
            db.session.add(ReportPhoto(report_id=report.id, photo_path=rel))
        db.session.commit()

        user_record = db.session.query(User).filter_by(telegram_id=str(message.from_user.id)).first()
        project = db.session.get(Project, data["project_id"])
        msg = (
            f"📝 <b>Отчёт сохранён</b>\n"
            f"💬 Telegram ID: {user_record.telegram_id}\n"
            f"👷 Сотрудник: {user_record.surname} {user_record.name}\n"
            f"🏢 Объект: {project.name}\n"
            f"🕑 начало: {report.start_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🕑 конец: {report.end_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"✏️ Текст отчета: {report.text_report or '—'}\n"
            f"Фото:"
        )
        responsible = db.session.get(User, proj.responsible_id)
        if responsible and responsible.telegram_id:
            target_chat = int(-)
            if target_chat != message.from_user.id:
                await bot.send_message(
                    chat_id=target_chat,
                    text=msg,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

                # 2) разделяем собранные media_to_send по типу
                photos = [
                    InputMediaPhoto(media=file_id)
                    for kind, file_id in data.get("media_to_send", [])
                    if kind == "photo"
                ]
                docs = [
                    InputMediaDocument(media=file_id)
                    for kind, file_id in data.get("media_to_send", [])
                    if kind == "document"
                ]

                # 3) отправляем сначала все фото в одной группе (если есть)
                if photos:
                    await bot.send_media_group(chat_id=target_chat, media=photos)

                # 4) потом все документы в другой группе (если есть)
                if docs:
                    await bot.send_media_group(chat_id=target_chat, media=docs)

        await message.answer("✅ Отчет сохранен.", reply_markup=ReplyKeyboardRemove())
        reset_state(chat)
        return

    if state == STATE_WAIT_PHOTOS and message.text:
        await message.answer("📸 Отправьте фото/документ или нажмите '✅ Закончить отправку'.")
        return

    # Финальная защита — неизвестная команда
    await message.answer("❌ Неизвестная команда. Нажмите /start")


def start():
    import asyncio
    asyncio.run(dp.start_polling(bot))

if __name__ == "__main__":
    start()
