# db_mongo.py
from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient("mongodb://localhost:27017")
db = client["users_db"]  # ← название новой базы данных

# Коллекции (эквиваленты таблиц)
users = db.users
user_fields = db.user_fields
user_scans = db.user_scans
projects = db.projects
project_scans = db.project_scans
reports = db.reports
report_photos = db.report_photos