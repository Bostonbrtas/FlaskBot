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

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, \
    InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.types import InputMediaPhoto, InputMediaDocument

from app import app, db
from models import User, Project, Report, ReportPhoto

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app.app_context().push()
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env")
TARGET_CHAT_ID = -1002094043980
TARGET_THREAD_ID = 4294977329
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

async def finalize_null_report(chat):
    data = user_states[chat]["data"]
    user = db.session.query(User).filter_by(telegram_id=str(chat)).first()
    if not user or not data.get("start_time") or not data.get("project_id"):
        return
    report = db.session.query(Report).filter(
        and_(
            Report.user_id == user.id,
            Report.project_id == data["project_id"],
            Report.start_time == data["start_time"]
        )
    ).first()
    if report:
        report.text_report = "-"
        report.photo_link = None
        report.end_time = None
        db.session.commit()

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

async def remind_unfinished_reports():
    for chat, st in user_states.items():
        data = st.get("data", {})
        if data.get("project_id") and st.get("state") in (
            STATE_WAIT_TEXT, STATE_WORKING, STATE_WAIT_LOC, STATE_WAIT_PHOTOS, STATE_READY, STATE_CHOOSE
        ):
            try:
                await bot.send_message(chat, "⏰ Пришлите отчёт, пожалуйста.")
            except Exception:
                logging.exception(f"Не удалось напомнить чат {chat}")

async def scheduler():
    tz = pytz.timezone("Asia/Krasnoyarsk")
    while True:
        now = datetime.now(tz)
        target = now.replace(hour=17, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        await remind_unfinished_reports()

def upload_to_yadisk(project_name: str, telegram_id: int, file_bytes: bytes, filename: str) -> str:
    token = os.getenv("YADISK_TOKEN")
    headers = {"Authorization": f"OAuth {token}"}

    common_root = "Отчёты"
    safe_proj = project_name.replace(" ", "_").replace("/", "_")
    date_folder = datetime.now().date().isoformat()
    user = db.session.query(User).filter_by(telegram_id=str(telegram_id)).first()
    surname = user.surname.replace(" ", "_") if user and user.surname else str(telegram_id)

    last_folder = f"{common_root}/{safe_proj}/{date_folder}/{surname}"

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
    if not last_folder:
        return None
    token = os.getenv("YADISK_TOKEN")
    headers = {"Authorization": f"OAuth {token}"}
    base_url = "https://cloud-api.yandex.net/v1/disk/resources"

    requests.put(
        f"{base_url}/publish",
        headers=headers,
        params={"path": last_folder}
    ).raise_for_status()

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
            end_time=None,
            text_report="отчет в разработке",
            photo_link=None
        )
        db.session.add(report)
        db.session.commit()


def delete_last_uploaded_files(data):
    token = os.getenv("YADISK_TOKEN")
    headers = {"Authorization": f"OAuth {token}"}
    for rel_path in data.get("session_photos", []):
        full_path = "Отчёты/" + rel_path
        try:
            requests.delete(
                "https://cloud-api.yandex.net/v1/disk/resources",
                headers=headers,
                params={"path": full_path, "permanently": "true"}
            )
        except Exception as e:
            logger.warning(f"❌ Не удалось удалить файл {full_path}: {e}")

    # Удаляем только временные данные этой сессии
    data.pop("session_photos", None)
    data.pop("media_to_send", None)
    data.pop("last_folder", None)


def reset_state(chat):
    fix_auto_report_if_needed(chat)
    if chat in user_states:
        del user_states[chat]


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat = message.chat.id
    reset_state(chat)

    tid = str(message.from_user.id)
    user = db.session.query(User).filter_by(
        telegram_id=tid,
        is_active=True,
        archived=False
    ).first()
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
    user = db.session.query(User).filter_by(
        telegram_id=tid,
        is_active=True,
        archived=False
    ).first()
    if not user:
        await message.answer("❌ Вы не зарегистрированы или были архивированы.")
        return

    projects = db.session.query(Project).filter_by(archived=False).all()
    builder = ReplyKeyboardBuilder()
    project_map = {}
    for p in projects:
        display = f"{p.name.strip()} ({p.address.strip()})"
        builder.add(KeyboardButton(text=display))
        project_map[display] = p.id
    builder.adjust(1)
    user_states[chat] = {
        "state": STATE_CHOOSE,
        "data": {
            "projects": project_map,
            "telegram_id": tid  # 👈 обязательно для защиты
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
            reset_state(chat)
            await begin_flow(message)
            return

        if len(history) <= 1:
            await message.answer("🔙 Это минимальный шаг. Пожалуйста, выберите объект.")
            return

        last_step = pop_step(chat)
        new_step = current_step(chat)
        user_states[chat]["state"] = new_step

        # Удаляем только если уходим С фото
        if last_step == STATE_WAIT_PHOTOS:
            delete_last_uploaded_files(data)
            data.pop("uploaded_photos", None)
            data.pop("media_to_send", None)
            data.pop("last_folder", None)

        # Переходы
        if new_step == STATE_CHOOSE:
            await finalize_null_report(chat)
            delete_last_uploaded_files(data)
            data.pop("uploaded_photos", None)
            data.pop("media_to_send", None)
            data.pop("last_folder", None)
            reset_state(chat)
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
        proj = db.session.get(Project, pid)
        data["project_id"] = pid
        data["ask_location"] = proj.ask_location
        push_step(chat, STATE_CHOOSE)

        if proj.ask_location:
            user_states[chat]["state"] = STATE_READY
            push_step(chat, STATE_READY)
            await message.answer("✅ Вы выбрали проект. Нажмите 🏁 Начать",
                                 reply_markup=working_keyboard(["🏁 Начать"]))
        else:
            data["start_time"] = datetime.now()  # ✅ фиксируем сразу для проектов без гео
            fix_auto_report_if_needed(chat)  # 👈 ДОБАВЬ ЭТО
            user_states[chat]["state"] = STATE_WORKING
            await message.answer("✅ Вы выбрали проект. Нажмите 📝 Отчет в конце.", reply_markup=working_keyboard(["📝 Отчет"]))
        return

    if state == STATE_READY and text == "🏁 Начать":
        data["start_time"] = datetime.now()
        fix_auto_report_if_needed(chat) # ✅ фиксируем только здесь
        proj = db.session.get(Project, data["project_id"])
        data["target_coords"] = (proj.latitude, proj.longitude)
        user_states[chat]["state"] = STATE_WAIT_LOC
        push_step(chat, STATE_WAIT_LOC)
        await message.answer("📍 Отправьте геолокацию:", reply_markup=geo_keyboard())
        return

    if state == STATE_WAIT_LOC and message.location:
        target = data["target_coords"]
        current = (message.location.latitude, message.location.longitude)
        dist = geodesic(target, current).meters
        if dist <= 150:
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
        if dist <= 150:
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
    if state == STATE_WAIT_PHOTOS and (message.photo or message.document):
        if message.photo:
            file_obj = message.photo[-1]
            kind = 'photo'
            ext = 'jpg'
        else:
            file_obj = message.document
            kind = 'document'
            ext = os.path.splitext(message.document.file_name or "")[1].lstrip('.') or 'bin'

        push_step(chat, STATE_WAIT_PHOTOS)

        file_info = await bot.get_file(file_obj.file_id)
        file_bytes = await bot.download_file(file_info.file_path)

        if kind == 'photo':
            filename = f"{datetime.now().strftime('%H-%M-%S')}.{ext}"
        else:
            filename = message.document.file_name or f"{file_obj.file_id}.{ext}"

        project = db.session.get(Project, data["project_id"])
        telegram_id = message.from_user.id

        last_folder = upload_to_yadisk(project.name, telegram_id, file_bytes, filename)
        data["last_folder"] = last_folder

        relpath = last_folder.removeprefix("Отчёты/") + "/" + filename
        data.setdefault("uploaded_photos", []).append(relpath)  # сохраняем для БД
        data.setdefault("session_photos", []).append(relpath)  # сохраняем для удаления если нужно
        data.setdefault("media_to_send", []).append((kind, file_obj.file_id, filename))  # для отправки

        total = len(data["media_to_send"])
        if kind == "photo":
            await message.answer(f"📷 Фото загружено. Всего: {total}")
        else:
            await message.answer(f"📄 Файл «{filename}» загружен. Всего: {total}")
        return

    # --- Блок "✅ Закончить отправку" (STATE_WAIT_PHOTOS + текст) ---
    if state == STATE_WAIT_PHOTOS and message.text == "✅ Закончить отправку":
        push_step(chat, STATE_WAIT_PHOTOS)
        # сохраняем в БД
        user_record = db.session.query(User).filter_by(telegram_id=str(message.from_user.id)).first()
        proj = db.session.get(Project, data["project_id"])
        last_folder = data.get("last_folder")
        public_url = finalize_report(last_folder)

        report = db.session.query(Report).filter_by(
            user_id=user_record.id,
            project_id=proj.id,
            start_time=data["start_time"]
        ).first()

        if report:
            report.end_time = datetime.now()
            report.text_report = data.get("text_report")
            report.photo_link = public_url
        else:
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

        # вот тут гарантированно есть все три:
        project = proj
        report = report
        user = user_record

        # собираем текст для отправки в ответственный чат
        msg = (
            f"👷 Сотрудник: {user.surname} {user.name}\n"
            f"🏢 Объект: {project.name}\n"
            f"🕑 начало: {report.start_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🕑 конец: {report.end_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"✏️ Текст отчета: {report.text_report or '—'}\n"
            f"Фото:"
        )
        await bot.send_message(
            chat_id=message.from_user.id,
            text=msg,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

        await bot.send_message(
            chat_id=TARGET_CHAT_ID,
            message_thread_id=TARGET_THREAD_ID,
            text=msg,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

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
            await bot.send_media_group(
                chat_id=TARGET_CHAT_ID,
                message_thread_id=TARGET_THREAD_ID,
                media=photos
            )
            await bot.send_media_group(chat_id=message.from_user.id, media=photos)

        if docs:
            await bot.send_media_group(
                chat_id=TARGET_CHAT_ID,
               message_thread_id=TARGET_THREAD_ID,
                media=docs
            )
            await bot.send_media_group(chat_id=message.from_user.id, media=docs)

        # отвечаем пользователю
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🚀 Начать")]],
            resize_keyboard=True
        )
        await message.answer("✅ Отчет сохранен.", reply_markup=kb)
        reset_state(chat)
        return

    if state == STATE_WAIT_PHOTOS and message.text:
        await message.answer("📸 Отправьте фото/документ или нажмите '✅ Закончить отправку'.")
        return

    # Финальная защита — неизвестная команда
    await message.answer("❌ Неизвестная команда. Нажмите /start")

async def main():
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())