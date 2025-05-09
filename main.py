import os
from dotenv import load_dotenv
import logging
import asyncio

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from geopy.distance import geodesic
from datetime import datetime

from app import app, db

app.app_context().push()
from models import User, Project, Report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден. Убедитесь, что он указан в файле .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Простое хранилище состояния: chat_id -> {state:str, data:dict}
user_states = {}

# Возможные состояния
STATE_CHOOSE = "choose_project"
STATE_READY = "ready_to_start"
STATE_WAIT_LOC = "waiting_location"
STATE_WORKING = "working"
STATE_WAIT_TEXT = "waiting_text"
STATE_WAIT_PHOTO = "waiting_photo"

# Запрос геолокации
loc_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
    resize_keyboard=True
)

def reset_state(chat_id: int):
    user_states[chat_id] = {"state": None, "data": {}}


from aiogram.utils.keyboard import ReplyKeyboardBuilder

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    chat = message.chat.id
    reset_state(chat)

    tid = str(message.from_user.id)
    logger.info(f"[START] Chat={chat}, UserID={tid}")

    user = db.session.query(User).filter_by(telegram_id=tid, is_active=True).first()
    if not user:
        await message.answer(
            f"❌ Вы не зарегистрированы.",
            parse_mode="HTML"
        )
        return

    projects = db.session.query(Project).all()
    if not projects:
        await message.answer("📭 Нет доступных адресов.")
        return

    # Собираем кнопки через Builder
    builder = ReplyKeyboardBuilder()
    for p in projects:
        text = f"{p.city}, {p.street}, {p.building}"
        builder.add(KeyboardButton(text=text))
    builder.adjust(1)

    # Сохраняем состояние и маппинг для проекта
    user_states[chat]["state"] = STATE_CHOOSE
    user_states[chat]["data"]["projects"] = {
        f"{p.city}, {p.street}, {p.building}": p.id for p in projects
    }

    await message.answer(
        "🏢 Выберите адрес:",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )

from aiogram.types import KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

@dp.message()
async def all_messages(message: types.Message):
    chat = message.chat.id
    st = user_states.get(chat, {"state": None})["state"]
    text = message.text or ""

    # 1) Выбор адреса
    if st == STATE_CHOOSE:
        proj_map = user_states[chat]["data"]["projects"]
        if text not in proj_map:
            await message.answer("❌ Неизвестный адрес, выберите кнопкой.")
            return

        pid = proj_map[text]
        proj = db.session.get(Project, pid)
        user_states[chat]["data"]["project_id"] = pid
        user_states[chat]["data"]["ask_location"] = proj.ask_location

        if proj.ask_location:
            user_states[chat]["state"] = STATE_READY
            builder = ReplyKeyboardBuilder()
            builder.add(KeyboardButton(text="🏁 Начать")).adjust(1)
            await message.answer(
                f"✅ Вы выбрали: <b>{text}</b>\nНажмите «🏁 Начать»",
                parse_mode="HTML",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )
        else:
            user_states[chat]["state"] = STATE_WORKING
            builder = ReplyKeyboardBuilder()
            builder.add(KeyboardButton(text="📝 Отчет")).adjust(1)
            await message.answer(
                f"✅ Вы выбрали: <b>{text}</b>\nКогда закончите работу, нажмите «📝 Отчет»",
                parse_mode="HTML",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )
        return

    # 2) «🏁 Начать»
    if st == STATE_READY and text in ["🏁 Начать", "Начать"]:
        pid = user_states[chat]["data"]["project_id"]
        proj = db.session.get(Project, pid)
        user_states[chat]["data"]["target_coords"] = (proj.latitude, proj.longitude)
        user_states[chat]["state"] = STATE_WAIT_LOC

        await message.answer(
            "📍 Отправьте вашу геолокацию:",
            reply_markup=loc_kb
        )
        return

    # 3) Получили локацию
    if st == STATE_WAIT_LOC and message.location:
        tgt = user_states[chat]["data"]["target_coords"]
        loc = (message.location.latitude, message.location.longitude)
        dist = geodesic(tgt, loc).meters
        if dist <= 250:
            user_states[chat]["data"]["start_time"] = datetime.now()
            user_states[chat]["state"] = STATE_WORKING

            # Кнопка «📝 Отчет»
            builder = ReplyKeyboardBuilder()
            builder.add(KeyboardButton(text="📝 Отчет")).adjust(1)
            await message.answer(
                "✅ Вы на месте! Нажмите «📝 Отчет» в конце дня.",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )
        else:
            await message.answer(
                f"❌ Слишком далеко: {dist:.0f} м. Попробуйте ещё раз.",
                reply_markup=loc_kb
            )
        return

    # 4) «📝 Отчет» — текст
    if st == STATE_WORKING and text in ["📝 Отчет", "Отчет"]:
        user_states[chat]["state"] = STATE_WAIT_TEXT
        await message.answer("📋 Пришлите текст отчёта:", reply_markup=ReplyKeyboardRemove())
        return

    # 5) Текст отчёта
    if st == STATE_WAIT_TEXT and text:
        user_states[chat]["data"]["text_report"] = text
        user_states[chat]["state"] = STATE_WAIT_PHOTO
        await message.answer("📸 Теперь пришлите фото с объекта.")
        return

    # 6) Фото отчёта
    if st == STATE_WAIT_PHOTO and message.photo:
        data = user_states[chat]["data"]
        uid = db.session.query(User).filter_by(telegram_id=str(message.from_user.id)).first().id
        pid = data["project_id"]

        BASE = os.path.dirname(os.path.abspath(__file__))
        folder = os.path.join(BASE, "static", "reports")
        os.makedirs(folder, exist_ok=True)
        photo = message.photo[-1]
        finfo = await bot.get_file(photo.file_id)
        path = os.path.join(folder, f"{photo.file_id}.jpg")
        await bot.download_file(finfo.file_path, path)

        start = data.get("start_time") or datetime.now()

        report = Report(
            user_id=uid,
            project_id=pid,
            start_time=start,
            end_time=datetime.now(),
            text_report=data["text_report"],
            photo_path=f"reports/{photo.file_id}.jpg"
        )
        db.session.add(report)
        db.session.commit()

        await message.answer("✅ Отчет сохранен!", reply_markup=ReplyKeyboardRemove())
        reset_state(chat)
        return

    # 7) Фоллбеки (ни в одной ветке клавиатуры не создаём напрямую)
    if st is None:
        await message.answer("❌ Нажмите /start, чтобы начать.")
    else:
        await message.answer("❌ Действуйте по запросам.")

async def main():
    # Создадим таблицы, если их нет
    with app.app_context():
        db.create_all()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())