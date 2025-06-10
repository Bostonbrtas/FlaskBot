from db import db


class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.String(50), unique=True, nullable=False)
    surname = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    patronymic = db.Column(db.String(100))
    birth_date = db.Column(db.Date, nullable=False)
    position = db.Column(db.String(100))
    passport = db.Column(db.String(20), nullable=False)
    inn = db.Column(db.String(12), nullable=False)
    snils = db.Column(db.String(14), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    reg_address = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    res_address = db.Column(db.Text)
    clothing_size = db.Column(db.String(10))
    shoe_size = db.Column(db.String(10))
    photo_path = db.Column(db.String(255))


class UserField(db.Model):
    __tablename__ = 'user_field'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    field_name = db.Column(db.String(100), nullable=False)
    field_value = db.Column(db.String(500))


class UserScan(db.Model):
    __tablename__ = 'userscan'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    scan_path = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255))


class Project(db.Model):
    __tablename__ = 'project'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    address = db.Column(db.Text, nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    responsible_id = db.Column(db.Integer)
    ask_location = db.Column(db.Boolean, default=True)
    archived = db.Column(db.Boolean, nullable=False, default=False)


class ProjectScan(db.Model):
    __tablename__ = 'projectscan'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer)
    scan_path = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255))


class Report(db.Model):
    __tablename__ = 'report'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    project_id = db.Column(db.Integer)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime)
    text_report = db.Column(db.Text)
    photo_link = db.Column(db.String)
    archived = db.Column(db.Boolean, default=False)


class ReportPhoto(db.Model):
    __tablename__ = 'report_photo'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer)
    photo_path = db.Column(db.String(255))