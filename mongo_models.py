from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime

client = MongoClient("mongodb://localhost:27017/")
db = client["users_db"]  # ← замени на нужное имя

# Пример функции для вставки пользователя
def create_user(data):
    return db.users.insert_one({
        "telegram_id": data["telegram_id"],
        "surname": data["surname"],
        "name": data["name"],
        "patronymic": data.get("patronymic"),
        "birth_date": data["birth_date"],
        "position": data.get("position"),
        "passport": data["passport"],
        "inn": data["inn"],
        "snils": data["snils"],
        "phone": data["phone"],
        "reg_address": data["reg_address"],
        "res_address": data.get("res_address"),
        "clothing_size": data.get("clothing_size"),
        "shoe_size": data.get("shoe_size"),
        "photo_path": data.get("photo_path"),
        "is_active": True,
        "archived": False
    })

def create_project(data):
    return db.projects.insert_one({
        "name": data["name"],
        "address": data["address"],
        "latitude": data["latitude"],
        "longitude": data["longitude"],
        "responsible_id": data["responsible_id"],
        "ask_location": data.get("ask_location", True),
        "archived": False
    })

def create_report(data):
    return db.reports.insert_one({
        "user_id": data["user_id"],
        "project_id": data["project_id"],
        "start_time": data["start_time"],
        "end_time": data.get("end_time"),
        "text_report": data.get("text_report", "-"),
        "photo_link": data.get("photo_link"),
        "archived": False
    })

def create_report_photo(report_id, photo_path):
    return db.report_photos.insert_one({
        "report_id": report_id,
        "photo_path": photo_path
    })

def create_project_scan(project_id, scan_path, filename):
    return db.project_scans.insert_one({
        "project_id": project_id,
        "scan_path": scan_path,
        "filename": filename
    })

def create_user_scan(user_id, scan_path, description=None):
    return db.user_scans.insert_one({
        "user_id": user_id,
        "scan_path": scan_path,
        "description": description
    })

def create_user_field(user_id, field_name, field_value):
    return db.user_fields.insert_one({
        "user_id": user_id,
        "field_name": field_name,
        "field_value": field_value
    })