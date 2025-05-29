from flask import Flask, render_template, request, redirect, url_for, session, flash, current_app
import os
import logging
from sqlalchemy.orm import joinedload
from datetime import datetime
from models import db, User, UserField, Project, Report, UserScan, ProjectScan
import webbrowser
from werkzeug.utils import secure_filename


import pandas as pd
from io import BytesIO
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font
from flask import send_file

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate




# Допустимые расширения для фото
ALLOWED_PHOTO = {'png','jpg','jpeg','gif','pdf','dock'}
ALLOWED_SCAN  = ALLOWED_PHOTO

def _save_file(file, folder):
    os.makedirs(folder, exist_ok=True)
    filename = secure_filename(file.filename)
    path = os.path.join(folder, filename)
    file.save(path)
    return filename

# Список доступных должностей
POSITIONS = [
    "Монтажник",
    "Электрик",
    "Сантехник",
    "Прораб",
    "Инженер",
    "Другая"
]


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Путь к папке instance внутри server
INSTANCE_DIR = os.path.join(os.path.dirname(__file__), 'server', 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)

# Инициализируем Flask с относительным instance_path
app = Flask(
    __name__,
    instance_relative_config=True,
    instance_path=INSTANCE_DIR,
    template_folder='server/templates',
    static_folder='static',
    static_url_path='/static'
)

# Конфигурация SQLAlchemy — единая БД в папке instance
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"sqlite:///{os.path.join(app.instance_path, 'users.db')}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.secret_key = 'your_secret_key_here'

# Настройка загрузок
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Инициализация БД

db.init_app(app)

migrate = Migrate(app, db)

# Создание таблиц в базе данных
with app.app_context():
    db.create_all()

# === Рест кода без изменений ===

@app.route('/')
def index():
    # вместо User.query.order_by(...) берём только не-архивированных
    users = User.query.filter_by(archived=False).order_by(User.id).all()
    return render_template(
        'index.html',
        users=users,
        active_tab='users',
        archive=False
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Проверка правильности логина и пароля
        if username == 'admin' and password == '1234':
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return "Неверный логин или пароль", 403

    return render_template('login.html')

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        # 1. Обновление основных данных
        user.telegram_id   = request.form['telegram_id'].strip()
        user.surname       = request.form['surname'].strip()
        user.name          = request.form['name'].strip()
        user.patronymic    = request.form.get('patronymic') or None
        bd_str = request.form['birth_date'].strip()
        try:
            # первый приоритет — привычный вам формат с точками
            user.birth_date = datetime.strptime(bd_str, '%d.%m.%Y').date()
        except ValueError:
            # если не совпало, пробуем ISO-формат YYYY-MM-DD (текстовый date input)
            try:
                user.birth_date = datetime.strptime(bd_str, '%Y-%m-%d').date()
            except ValueError:
                # на крайний случай, если ни один формат не подошёл,
                # вы можете оставить None или присвоить как есть (строку),
                # но тогда model.birth_date должен быть String, а не Date
                user.birth_date = None
        user.position      = request.form['position']
        user.passport      = request.form['passport'].strip()
        user.inn           = request.form['inn'].strip()
        user.snils         = request.form['snils'].strip()
        user.phone         = request.form['phone'].strip()
        user.reg_address   = request.form['reg_address'].strip()
        user.res_address   = request.form.get('res_address') or None
        user.clothing_size = request.form.get('clothing_size') or None
        user.shoe_size     = request.form.get('shoe_size') or None

        # Обновление фото
        photo = request.files.get('photo')
        if photo and photo.filename:
            user_folder = os.path.join(app.static_folder, 'uploads', str(user.id))
            os.makedirs(user_folder, exist_ok=True)
            filename = f"photo_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{photo.filename}"
            path = os.path.join(user_folder, filename)
            photo.save(path)
            rel_path = f"uploads/{user.id}/{filename}"
            user.photo_path = rel_path

        # Доп. поля
        user.userfields.clear()
        names = request.form.getlist('field_name[]')
        values = request.form.getlist('field_value[]')
        for name, value in zip(names, values):
            if name.strip() and value.strip():
                user.userfields.append(UserField(field_name=name.strip(), field_value=value.strip()))

        # Обработка сканов
        user.scans.clear()
        scan_files = request.files.getlist('scan_file')
        scan_descs = request.form.getlist('scan_desc')

        scans_dir = os.path.join(app.static_folder, 'scans', str(user.id))
        os.makedirs(scans_dir, exist_ok=True)

        for file, desc in zip(scan_files, scan_descs):
            if file and file.filename:
                fname = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"
                filepath = os.path.join(scans_dir, fname)
                file.save(filepath)
                relpath = f"scans/{user.id}/{fname}"
                user.scans.append(UserScan(scan_path=relpath, description=desc.strip()))

        # Сохраняем
        db.session.commit()
        return redirect(url_for('index'))

    return render_template('edit_user.html',
                           user=user,
                           positions=['Монтажник', 'Электрик', 'Сантехник', 'Прораб', 'Инженер', 'Другая'],
                           active_tab='users')

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg'}

from flask import request, render_template, redirect, url_for, flash
from datetime import datetime
import os
from models import db, User, UserField, UserScan

@app.route('/add_user', methods=['GET', 'POST'])
def add_user():
    if request.method == 'POST':
        tg_id = request.form['telegram_id'].strip()

        if User.query.filter_by(telegram_id=tg_id).first():
            return "Пользователь с таким Telegram ID уже существует.", 400

        user = User(telegram_id=tg_id)

        # обязательные поля
        user.surname = request.form['surname'].strip()
        user.name = request.form['name'].strip()
        # в функции add_user
        bd_str = request.form['birth_date'].strip()
        try:
            # первый приоритет — привычный вам формат с точками
            user.birth_date = datetime.strptime(bd_str, '%d.%m.%Y').date()
        except ValueError:
            # если не совпало, пробуем ISO-формат YYYY-MM-DD (текстовый date input)
            try:
                user.birth_date = datetime.strptime(bd_str, '%Y-%m-%d').date()
            except ValueError:
                # на крайний случай, если ни один формат не подошёл,
                # вы можете оставить None или присвоить как есть (строку),
                # но тогда model.birth_date должен быть String, а не Date
                user.birth_date = None
        user.position = request.form['position']
        user.passport = request.form['passport'].strip()
        user.inn = request.form['inn'].strip()
        user.snils = request.form['snils'].strip()
        user.phone = request.form['phone'].strip()
        user.reg_address = request.form['reg_address'].strip()

        # необязательные
        user.patronymic = request.form.get('patronymic') or None
        user.res_address = request.form.get('res_address') or None
        user.clothing_size = request.form.get('clothing_size') or None
        user.shoe_size = request.form.get('shoe_size') or None

        db.session.add(user)
        db.session.flush()  # user.id доступен

        # === Фото ===
        photo = request.files.get('photo')
        if photo and photo.filename:
            photo_dir = os.path.join(app.static_folder, 'uploads', str(user.id))
            os.makedirs(photo_dir, exist_ok=True)
            filename = f"{datetime.utcnow().timestamp()}_{photo.filename}"
            path = os.path.join(photo_dir, filename)
            photo.save(path)
            user.photo_path = f"uploads/{user.id}/{filename}"

        # === Дополнительные поля ===
        names = request.form.getlist('field_name[]')
        values = request.form.getlist('field_value[]')
        for name, value in zip(names, values):
            if name.strip() and value.strip():
                user.userfields.append(UserField(field_name=name.strip(), field_value=value.strip()))

        # === Сканы ===
        scan_files = request.files.getlist('scan_file')
        scan_descs = request.form.getlist('scan_desc')
        scan_dir = os.path.join(app.static_folder, 'scans', str(user.id))
        os.makedirs(scan_dir, exist_ok=True)

        for f, desc in zip(scan_files, scan_descs):
            if f and f.filename:
                fname = f"{datetime.utcnow().timestamp()}_{f.filename}"
                fpath = os.path.join(scan_dir, fname)
                f.save(fpath)
                user.scans.append(UserScan(scan_path=f"scans/{user.id}/{fname}", description=desc.strip()))

        db.session.commit()
        return redirect(url_for('index'))

    return render_template('add_user.html', positions=POSITIONS, active_tab='users')

@app.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    try:
        # Удаление фото с диска
        if user.photo_path:
            photo_path = os.path.join(app.static_folder, user.photo_path)
            if os.path.exists(photo_path):
                os.remove(photo_path)

        # Удаление дополнительных полей
        UserField.query.filter_by(user_id=user.id).delete()

        # Удаление пользователя
        db.session.delete(user)
        db.session.commit()
        return redirect(url_for('index'))

    except Exception as e:
        db.session.rollback()
        return render_template('error.html', error=f"Ошибка при удалении пользователя: {e}")



@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/projects')
def projects():
    # читаем параметры сортировки из строки запроса
    sort = request.args.get('sort', 'id')
    direction = request.args.get('dir', 'asc')

    # В app.py, внутри valid_sorts:
    valid_sorts = {
        'alpha': Project.name,
        'address': Project.address,
        'latitude': Project.latitude,
        'longitude': Project.longitude,
        'ask_location': Project.ask_location
    }
    column = valid_sorts.get(sort, Project.id)

    # направление
    if direction == 'desc':
        column = column.desc()

    # только неархивные
    projects = Project.query.filter_by(archived=False).order_by(column).all()

    return render_template(
        'projects.html',
        projects=projects,
        active_tab='projects',
        archive=False,
        sort=sort,
        dir=direction
    )

@app.route("/project/add", methods=["GET", "POST"])
def add_project():
    if request.method == "POST":
        name           = request.form["name"]
        address        = request.form["address"]
        responsible_id = request.form["responsible_id"]
        ask_location   = bool(request.form.get("ask_location"))

        # конвертация координат
        try:
            latitude  = float(request.form.get("latitude", ""))
            longitude = float(request.form.get("longitude", ""))
        except ValueError:
            flash("Широта или долгота введены неверно", "danger")
            return redirect(url_for("add_project"))

        new_project = Project(
            name=name,
            address=address,
            latitude=latitude,
            longitude=longitude,
            responsible_id=responsible_id,
            ask_location=ask_location
        )
        db.session.add(new_project)
        db.session.commit()

        # сохранение сканов
        project_id = new_project.id
        scan_folder = os.path.join(current_app.static_folder, "scanProject", str(project_id))
        os.makedirs(scan_folder, exist_ok=True)

        for f in request.files.getlist("scans"):
            if f.filename:
                filename = secure_filename(f.filename)
                fpath = os.path.join(scan_folder, filename)
                f.save(fpath)
                db.session.add(ProjectScan(
                    project_id=project_id,
                    scan_path=os.path.join("scanProject", str(project_id), filename),
                    filename=filename
                ))
        db.session.commit()
        return redirect(url_for("projects"))

    users = User.query.all()
    project = None
    return render_template("add_project.html", users=users, project=project, active_tab='projects')
# Роут для отображения отчетов
from sqlalchemy.orm import joinedload

@app.route('/reports')
def show_reports():
    reports = Report.query.filter_by(archived=False).options(
        joinedload(Report.user),
        joinedload(Report.project),
        joinedload(Report.photos)
    ).order_by(Report.start_time.desc()).all()
    return render_template(
        'reports.html',
        reports=reports,
        active_tab='reports',
        archive=False
    )

@app.route("/edit_project/<int:project_id>", methods=["GET", "POST"])
def edit_project(project_id):
    project = Project.query.get_or_404(project_id)

    if request.method == "POST":
        project.name           = request.form["name"]
        project.address        = request.form["address"]
        project.responsible_id = request.form["responsible_id"]
        project.ask_location   = bool(request.form.get("ask_location"))

        # обновляем координаты
        try:
            project.latitude  = float(request.form.get("latitude", project.latitude))
            project.longitude = float(request.form.get("longitude", project.longitude))
        except ValueError:
            pass  # оставляем старые

        # удаление отмеченных сканов
        for scan_id in request.form.getlist("delete_scans"):
            scan = ProjectScan.query.get(scan_id)
            if scan:
                fullpath = os.path.join(current_app.static_folder, "scanProject", str(project.id), scan.filename)
                if os.path.exists(fullpath):
                    os.remove(fullpath)
                db.session.delete(scan)

        # добавление новых сканов
        scan_folder = os.path.join(current_app.static_folder, "scanProject", str(project.id))
        os.makedirs(scan_folder, exist_ok=True)
        for f in request.files.getlist("scans"):
            if f.filename:
                filename = secure_filename(f.filename)
                fpath = os.path.join(scan_folder, filename)
                f.save(fpath)
                db.session.add(ProjectScan(
                    project_id=project.id,
                    scan_path=os.path.join("scanProject", str(project.id), filename),
                    filename=filename
                ))

        db.session.commit()
        return redirect(url_for("projects"))

    users = User.query.all()
    return render_template("edit_project.html",
                           project=project,
                           users=users,
                           active_tab='projects')

@app.route('/delete_project/<int:project_id>', methods=['POST'])
def delete_project(project_id):
    project = Project.query.get(project_id)
    if project:
        db.session.delete(project)
        db.session.commit()
        logger.info(f"Проект с ID {project_id} удалён.")
    return redirect(url_for('projects'))

@app.route('/delete_project_scan/<int:scan_id>', methods=['POST'])
def delete_project_scan(scan_id):
    scan = ProjectScan.query.get_or_404(scan_id)
    project_id = scan.project_id

    # Удаление файла с диска
    scan_path = os.path.join('static', 'scanProject', str(project_id), scan.filename)
    if os.path.exists(scan_path):
        os.remove(scan_path)

    # Удаление из БД
    db.session.delete(scan)
    db.session.commit()

    flash("Скан успешно удалён.")
    return redirect(url_for('edit_project', project_id=project_id))


@app.route('/delete_report/<int:report_id>', methods=['POST'])
def delete_report(report_id):
    try:
        report = Report.query.options(joinedload(Report.photos)).get_or_404(report_id)

        # Удаление всех связанных фото
        for photo in report.photos:
            try:
                full_path = os.path.join(app.static_folder, photo.photo_path)
                if os.path.exists(full_path):
                    os.remove(full_path)
                db.session.delete(photo)
            except Exception as e:
                logging.error(f"Ошибка удаления фото: {str(e)}")

        db.session.delete(report)
        db.session.commit()
        return redirect(url_for('show_reports'))

    except Exception as e:
        db.session.rollback()
        return render_template('error.html', error=str(e))

@app.route('/export_users')
def export_users():
    users = User.query.all()
    data = []

    for user in users:
        fields = {f.field_name: f.field_value for f in user.userfields}
        data.append({
            'Telegram ID': user.telegram_id,
            'Фамилия': user.surname,
            'Имя': user.name,
            'Отчество': user.patronymic,
            'Дата рождения': user.birth_date,
            'Должность': user.position,
            'Паспорт': user.passport,
            'ИНН': user.inn,
            'СНИЛС': user.snils,
            'Телефон': user.phone,
            'Адрес прописки': user.reg_address,
            'Адрес проживания': user.res_address,
            'Размер одежды': user.clothing_size,
            'Размер обуви': user.shoe_size,
            **fields  # динамические поля
        })

    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)

    return send_file(output, download_name="сотрудники.xlsx", as_attachment=True)


@app.route('/export_projects')
def export_projects():
    projects = Project.query.all()
    # Собираем данные для Excel-файла
    data = []
    for p in projects:
        data.append({
            'ID': p.id,
            'Название': p.name,
            'Адрес': p.address,
            'Широта': p.latitude,
            'Долгота': p.longitude
        })
    df = pd.DataFrame(data)
    file_path = os.path.join(app.instance_path, "projects_export.xlsx")
    df.to_excel(file_path, index=False)
    return send_file(file_path, as_attachment=True)

@app.route('/export_reports')
def export_reports():
    reports = Report.query.all()

    # Создаём рабочую книгу
    wb = Workbook()
    ws = wb.active
    ws.title = "Отчёты"

    # Заголовки
    headers = ["Telegram ID", "ФИО", "Проект", "Начало", "Конец", "Текст отчета", "Фото"]
    ws.append(headers)

    for report in reports:
        user = report.user
        project = report.project

        telegram_id = user.telegram_id if user else ""
        full_name   = f"{user.surname} {user.name}" if user else ""
        # Берём название проекта и его адрес
        project_address = f"{project.name}, {project.address}" if project else ""
        start = report.start_time.strftime("%Y-%m-%d %H:%M") if report.start_time else ""
        end   = report.end_time.strftime("%Y-%m-%d %H:%M") if report.end_time else ""
        text  = report.text_report or ""

        # Фото — гиперссылка, если есть
        if report.photo_link:
            photo_url = report.photo_link
        else:
            photo_url = None

        row = [telegram_id, full_name, project_address, start, end, text, ""]
        ws.append(row)

        if photo_url:
            cell = ws.cell(row=ws.max_row, column=7)
            cell.value = "Ссылка"
            cell.hyperlink = photo_url
            cell.font = Font(color="0000FF", underline="single")

    # Подгоняем ширину колонок
    for i, _ in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(i)].width = 20

    export_path = os.path.join(app.instance_path, "reports_export.xlsx")
    wb.save(export_path)
    return send_file(export_path, as_attachment=True)

@app.route('/delete_user_scan/<int:scan_id>', methods=['POST'])
def delete_user_scan(scan_id):
    scan = UserScan.query.get_or_404(scan_id)
    # Удаляем файл с диска
    file_path = os.path.join(current_app.static_folder, scan.scan_path)
    if os.path.exists(file_path):
        os.remove(file_path)
    # Удаляем запись из БД
    db.session.delete(scan)
    db.session.commit()
    return '', 204

@app.route('/archive/users')
def archive_users():
    users = User.query.filter_by(archived=True).order_by(User.id).all()
    return render_template(
        'archive_users.html',
        users=users,
        active_tab='users',
        archive=True
    )

@app.route('/archive/projects')
def archive_projects():
    # читаем параметры сортировки из строки запроса
    sort = request.args.get('sort', 'alpha')
    direction = request.args.get('dir', 'asc')

    # ключи сортировки → колонки модели
    valid_sorts = {
        'alpha':        Project.name,
        'address':      Project.address,
        'latitude':     Project.latitude,
        'longitude':    Project.longitude,
        'ask_location': Project.ask_location
    }
    column = valid_sorts.get(sort, Project.name)

    # направление
    if direction == 'desc':
        column = column.desc()

    # выбираем только архивные проекты и сортируем
    projects = Project.query.filter_by(archived=True).order_by(column).all()

    return render_template(
        'archive_projects.html',
        projects=projects,
        active_tab='projects',
        archive=True,
        sort=sort,
        dir=direction
    )

@app.route('/archive/reports')
def archive_reports():
    reports = Report.query.filter_by(archived=True).options(
        joinedload(Report.user),
        joinedload(Report.project),
        joinedload(Report.photos)
    ).order_by(Report.start_time.desc()).all()
    return render_template(
        'archive_reports.html',
        reports=reports,
        active_tab='reports',
        archive=True
    )
@app.route('/user/<int:user_id>/archive', methods=['POST'])
def toggle_archive_user(user_id):
    user = User.query.get_or_404(user_id)
    user.archived = not user.archived
    db.session.commit()
    # вернуться на ту же страницу (список или архив)
    return redirect(request.referrer or url_for('index'))

@app.route('/project/<int:project_id>/archive', methods=['POST'])
def toggle_archive_project(project_id):
    project = Project.query.get_or_404(project_id)
    project.archived = not project.archived
    db.session.commit()
    return redirect(request.referrer or url_for('projects'))

@app.route('/report/<int:report_id>/archive', methods=['POST'])
def toggle_archive_report(report_id):
    report = Report.query.get_or_404(report_id)
    report.archived = not report.archived
    db.session.commit()
    return redirect(request.referrer or url_for('show_reports'))


@app.route('/edit_report/<int:report_id>', methods=['GET', 'POST'])
def edit_report(report_id):
    report = Report.query.get_or_404(report_id)
    if request.method == 'POST':
        # Обновляем поля из формы
        report.project_id = int(request.form['project_id'])

        # Новая строка парсинга начала в формате "дд.мм.гггг, чч:мм"
        report.start_time = datetime.strptime(
            request.form['start_time'],
            '%d.%m.%Y, %H:%M'
        )

        # Парсим окончание только если есть непустое значение
        end_str = request.form.get('end_time', '').strip()
        if end_str:
            report.end_time = datetime.strptime(
                end_str,
                '%d.%m.%Y, %H:%M'
            )
        else:
            report.end_time = None

        report.text_report = request.form['text_report'].strip()
        db.session.commit()
        return redirect(url_for('show_reports'))

    # GET — отображаем форму
    projects = Project.query.filter_by(archived=False).all()
    return render_template(
        'edit_report.html',
        report=report,
        projects=projects,
        active_tab='reports',
        archive=False
    )
def open_browser():
    # Пауза, чтобы сервер успел подняться
    webbrowser.open_new("http://127.0.0.1:5001/")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)