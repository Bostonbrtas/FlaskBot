import asyncio
from bson import ObjectId
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import User, UserField, UserScan, Project, ProjectScan, Report, ReportPhoto
from db_mongo import users, user_fields, user_scans, projects, project_scans, reports, report_photos

engine = create_engine("sqlite:///server/instance/users.db")
Session = sessionmaker(bind=engine)
session = Session()

# Для сопоставления старых ID (из SQLite) и новых Mongo ObjectId
id_maps = {
    "users": {},
    "projects": {},
    "reports": {}
}
from datetime import date, datetime

def convert_dates(doc):
    for k, v in doc.items():
        if isinstance(v, date) and not isinstance(v, datetime):
            doc[k] = datetime.combine(v, datetime.min.time())
    return doc

async def transfer_data():
    # --- Users ---
    for user in session.query(User).all():
        doc = user.__dict__.copy()
        doc.pop("_sa_instance_state", None)
        doc = convert_dates(doc)
        old_id = doc.pop("id")
        new_id = ObjectId()
        id_maps["users"][old_id] = new_id
        doc["_id"] = new_id
        await users.insert_one(doc)

    # --- UserFields ---
    for obj in session.query(UserField).all():
        doc = obj.__dict__.copy()
        doc.pop("_sa_instance_state", None)
        doc.pop("id")
        doc = convert_dates(doc)
        doc["user_id"] = id_maps["users"][doc["user_id"]]
        await user_fields.insert_one(doc)

    # --- UserScans ---
    for obj in session.query(UserScan).all():
        doc = obj.__dict__.copy()
        doc.pop("_sa_instance_state", None)
        doc.pop("id")
        doc = convert_dates(doc)
        doc["user_id"] = id_maps["users"][doc["user_id"]]
        await user_scans.insert_one(doc)

    # --- Projects ---
    for obj in session.query(Project).all():
        doc = obj.__dict__.copy()
        doc.pop("_sa_instance_state", None)
        old_id = doc.pop("id")
        new_id = ObjectId()
        doc = convert_dates(doc)
        id_maps["projects"][old_id] = new_id
        doc["_id"] = new_id
        doc["responsible_id"] = id_maps["users"][doc["responsible_id"]]
        await projects.insert_one(doc)

    # --- ProjectScans ---
    for obj in session.query(ProjectScan).all():
        doc = obj.__dict__.copy()
        doc.pop("_sa_instance_state", None)
        doc.pop("id")
        doc = convert_dates(doc)
        doc["project_id"] = id_maps["projects"][doc["project_id"]]
        await project_scans.insert_one(doc)

    # --- Reports ---
    for obj in session.query(Report).all():
        doc = obj.__dict__.copy()
        doc.pop("_sa_instance_state", None)
        old_id = doc.pop("id")
        doc = convert_dates(doc)
        new_id = ObjectId()
        id_maps["reports"][old_id] = new_id
        doc["_id"] = new_id
        doc["user_id"] = id_maps["users"].get(doc["user_id"])
        doc["project_id"] = id_maps["projects"].get(doc["project_id"])
        await reports.insert_one(doc)

    # --- ReportPhotos ---
    for obj in session.query(ReportPhoto).all():
        doc = obj.__dict__.copy()
        doc.pop("_sa_instance_state", None)
        doc.pop("id")
        doc = convert_dates(doc)
        doc["report_id"] = id_maps["reports"].get(doc["report_id"])
        await report_photos.insert_one(doc)

    print("✅ Миграция завершена успешно.")

asyncio.run(transfer_data())