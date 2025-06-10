from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import User, UserField, UserScan, Project, ProjectScan, Report, ReportPhoto
from db import db

engine = create_engine("sqlite:///server/instance/users.db")
Session = sessionmaker(bind=engine)
session = Session()

from sqlalchemy.orm import declarative_base
Base = db.Model

Base.metadata.create_all(engine)

print("✅ SQLite база создана.")