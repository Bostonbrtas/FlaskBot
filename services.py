import logging
from sqlalchemy.exc import SQLAlchemyError

from db import db
from models import User

# Настройка логгирования для модуля сервисов
logger = logging.getLogger(__name__)


def is_user_allowed(telegram_id: str) -> bool:
    """
    Проверяет, существует ли в базе активный пользователь с данным telegram_id.
    Возвращает True, если пользователь найден и активен, иначе False.
    """
    try:
        user = db.session.query(User) \
            .filter_by(telegram_id=telegram_id, is_active=True) \
            .first()
        return user is not None
    except SQLAlchemyError as e:
        logger.error(f"Database error in is_user_allowed: {e}")
        return False


def register_user(telegram_id: str, name: str) -> bool:
    """
    Регистрирует нового пользователя с указанным telegram_id и именем.
    Возвращает False, если пользователь с таким telegram_id и именем уже существует или возникла ошибка.
    """
    try:
        existing = db.session.query(User) \
            .filter_by(telegram_id=telegram_id, name=name) \
            .first()
        if existing:
            return False

        new_user = User(telegram_id=telegram_id, name=name)
        db.session.add(new_user)
        db.session.commit()
        return True
    except SQLAlchemyError as e:
        logger.error(f"Error registering user: {e}")
        return False
