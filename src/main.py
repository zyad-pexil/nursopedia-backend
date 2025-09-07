import os
import sys
# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Load environment variables from backend/.env.local if present
try:
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
except Exception:
    pass

from flask import Flask, send_from_directory
from flask_cors import CORS
from src.models.user import db
from flask_migrate import Migrate
from sqlalchemy import text
from src.routes.user import user_bp
from src.routes.auth import auth_bp
from src.routes.content import content_bp
from src.routes.admin import admin_bp

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'))
app.config['SECRET_KEY'] = 'nursopedia_secret_key_2024_very_secure'

# Optional: zero admin dashboard counters for demo/delivery
app.config['DASHBOARD_ZERO_COUNTS'] = os.getenv('DASHBOARD_ZERO_COUNTS', '0') == '1'

# Enable CORS for all routes
CORS(app, origins="*")

# Register blueprints
app.register_blueprint(user_bp, url_prefix='/api')
app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(content_bp, url_prefix='/api/content')
app.register_blueprint(admin_bp, url_prefix='/api/admin')

# Database configuration updated to support Railway MySQL or local SQLite

def _is_running_on_railway() -> bool:
    return bool(
        os.getenv('RAILWAY_PROJECT_ID')
        or os.getenv('RAILWAY_ENVIRONMENT')
        or os.getenv('RAILWAY_ENVIRONMENT_NAME')
    )

# Build SQLALCHEMY_DATABASE_URI from envs when available (Railway MySQL)
# Use discrete env vars only; no MYSQL_PUBLIC_URL/DATABASE_URL support
MYSQL_HOST = os.getenv('MYSQLHOST') or os.getenv('DB_HOST')
MYSQL_PORT = os.getenv('MYSQLPORT') or os.getenv('DB_PORT', '3306')
MYSQL_USER = os.getenv('MYSQLUSER') or os.getenv('DB_USER')
MYSQL_PASSWORD = os.getenv('MYSQLPASSWORD') or os.getenv('DB_PASSWORD')
MYSQL_DATABASE = os.getenv('MYSQLDATABASE') or os.getenv('DB_NAME')

if MYSQL_HOST and MYSQL_USER and MYSQL_PASSWORD and MYSQL_DATABASE:
    # e.g., mysql+pymysql://user:pass@host:3306/dbname
    db_uri = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
else:
    # Fallback to SQLite (local dev or when MySQL not configured)
    _default_db_dir = '/tmp' if _is_running_on_railway() else os.path.join(os.path.dirname(__file__), 'database')
    _db_default = os.path.join(_default_db_dir, 'app.db')
    _db_path_env = os.getenv('DB_PATH')
    db_path = _db_path_env if _db_path_env else _db_default
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db_uri = f"sqlite:///{db_path}"

app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configure engine/pool options to better handle cold starts on Railway
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,           # validate connections before use
    'pool_recycle': 280,             # recycle before MySQL 8 default wait_timeout (in secs)
    'pool_size': int(os.getenv('DB_POOL_SIZE', 5)),
    'max_overflow': int(os.getenv('DB_MAX_OVERFLOW', 5)),
}

# Configure max content length if needed (e.g., 10MB receipts)
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 10 * 1024 * 1024))

db.init_app(app)
migrate = Migrate(app, db)

# Ensure at least one admin user exists on every startup
from src.models.user import User

def ensure_admin_exists():
    admin_username = os.getenv('DEFAULT_ADMIN_USERNAME', 'admin')
    admin_email = os.getenv('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
    admin_password = os.getenv('DEFAULT_ADMIN_PASSWORD', 'Admin1234')
    admin_phone = os.getenv('DEFAULT_ADMIN_PHONE', '01000000000')
    admin_fullname = os.getenv('DEFAULT_ADMIN_FULLNAME', 'Administrator')

    admin = User.query.filter_by(user_type='admin').first()
    if not admin:
        admin = User(
            username=admin_username,
            email=admin_email,
            full_name=admin_fullname,
            phone_number=admin_phone,
            user_type='admin',
            is_active=True,
        )
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()

# Try connecting with retries to wait for MySQL readiness
import time

def wait_for_db(max_attempts: int = int(os.getenv('DB_CONNECT_RETRIES', 10)), delay: float = float(os.getenv('DB_CONNECT_DELAY', 1.5))):
    for attempt in range(1, max_attempts + 1):
        try:
            with app.app_context():
                with db.engine.connect() as conn:
                    conn.execute(text('SELECT 1'))
                    return True
        except Exception as e:
            if attempt == max_attempts:
                raise
            time.sleep(delay)

with app.app_context():
    wait_for_db()
    db.create_all()
    ensure_admin_exists()

# Serve uploaded receipts stored under configurable dir
@app.route('/uploads/receipts/<path:filename>')
def serve_receipts(filename):
    default_receipts_dir = '/tmp/receipts' if _is_running_on_railway() else os.path.join(os.path.dirname(__file__), 'database', 'receipts')
    receipts_dir = os.getenv('RECEIPTS_DIR', default_receipts_dir)
    os.makedirs(receipts_dir, exist_ok=True)
    return send_from_directory(receipts_dir, filename)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    static_folder_path = app.static_folder
    if static_folder_path is None:
        return "Static folder not configured", 404

    # Serve any request under /static/* correctly from the static folder
    if path.startswith('static/'):
        subpath = path[len('static/'):]
        abs_path = os.path.join(static_folder_path, subpath)
        if os.path.exists(abs_path):
            return send_from_directory(static_folder_path, subpath)

    # Serve direct files inside the static folder
    if path != "" and os.path.exists(os.path.join(static_folder_path, path)):
        return send_from_directory(static_folder_path, path)

    # Fallback to SPA index.html
    index_path = os.path.join(static_folder_path, 'index.html')
    if os.path.exists(index_path):
        return send_from_directory(static_folder_path, 'index.html')
    else:
        return "index.html not found", 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)