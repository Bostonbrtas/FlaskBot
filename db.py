# db.py
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# 1) Создаём папку instance рядом с этим файлом
app = Flask(__name__, instance_relative_config=True)
os.makedirs(app.instance_path, exist_ok=True)

# 2) Настраиваем путь к базе внутри instance/
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"sqlite:///{os.path.join(app.instance_path, 'users.db')}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 3) Инициализируем SQLAlchemy
db = SQLAlchemy(app)

# (Больше ничего лишнего: модели будут в models.py)