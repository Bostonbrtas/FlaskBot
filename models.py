from flask_sqlalchemy import SQLAlchemy


from db import db

class User(db.Model):
    __tablename__ = 'user'
    id           = db.Column(db.Integer, primary_key=True)
    telegram_id  = db.Column(db.String(50), unique=True, nullable=False)
    surname      = db.Column(db.String(100), nullable=False)
    name         = db.Column(db.String(100), nullable=False)
    patronymic   = db.Column(db.String(100))
    birth_date   = db.Column(db.Date, nullable=False)
    position     = db.Column(db.String(100))
    passport     = db.Column(db.String(20), nullable=False)
    inn          = db.Column(db.String(12), nullable=False)
    snils        = db.Column(db.String(14), nullable=False)
    phone        = db.Column(db.String(20), nullable=False)
    reg_address  = db.Column(db.Text, nullable=False)
    is_active    = db.Column(db.Boolean, default=True, nullable=False)
    res_address  = db.Column(db.Text)
    clothing_size= db.Column(db.String(10))
    shoe_size    = db.Column(db.String(10))
    photo_path   = db.Column(db.String(255), nullable=True)
    scans = db.relationship('UserScan', backref='user', cascade='all, delete-orphan')
    userfields = db.relationship('UserField', backref='user', cascade='all, delete-orphan')


class UserField(db.Model):
    __tablename__ = 'user_field'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    field_name  = db.Column(db.String(100), nullable=False)
    field_value = db.Column(db.String(500), nullable=True)

    # Опционально можно настроить связь backref в User:
    # user = db.relationship('User', backref=db.backref('fields', lazy='joined'))

class UserScan(db.Model):
    __tablename__ = 'userscan'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    scan_path   = db.Column(db.String(255), nullable=False)   # относительный путь к статике
    description = db.Column(db.String(255))

class Project(db.Model):
    __tablename__ = 'project'
    id        = db.Column(db.Integer, primary_key=True)
    city      = db.Column(db.String(100), nullable=False)
    street    = db.Column(db.String(100), nullable=False)
    building  = db.Column(db.String(50), nullable=False)
    latitude  = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)

class Report(db.Model):
    __tablename__ = 'report'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'))
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'))
    start_time = db.Column(db.DateTime, nullable=False)
    end_time   = db.Column(db.DateTime)
    text_report= db.Column(db.Text)
    photo_path = db.Column(db.String(255))
    user       = db.relationship('User',   backref='reports', lazy='joined')
    project    = db.relationship('Project',backref='reports', lazy='joined')
