from db import db, app
from models import User

with app.app_context():
    users = User.query.all()
    for u in users:
        new_id = u.telegram_id.strip()
        if new_id != u.telegram_id:
            u.telegram_id = new_id
    db.session.commit()
    print(f"✓ Обрезано пробелов у {len(users)} пользователей")