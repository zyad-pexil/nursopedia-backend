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
from sqlalchemy import text, event
from sqlalchemy.engine import Engine
from src.routes.user import user_bp
from src.routes.auth import auth_bp
from src.routes.content import content_bp
from src.routes.admin import admin_bp

# Optimize SQLite connections when used (dev/fallback)
try:
    import sqlite3

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        # Apply only to SQLite connections
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            # WAL improves concurrency on reads
            cursor.execute("PRAGMA journal_mode=WAL;")
            # NORMAL reduces fsyncs while keeping reasonable durability
            cursor.execute("PRAGMA synchronous=NORMAL;")
            # Cache ~20MB in-memory for query speed (negative => KiB)
            cursor.execute("PRAGMA cache_size=-20000;")
            # Enforce foreign keys
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.close()
except Exception:
    pass

# PostgreSQL session tuning (timeouts, app name, timezone)
try:
    @event.listens_for(Engine, "connect")
    def _set_postgres_settings(dbapi_connection, connection_record):
        """Configure safe per-connection settings for PostgreSQL.
        Runs in autocommit and rolls back on any error to avoid leaving
        the connection in an aborted transaction state.
        """
        try:
            # Allow disabling via env if needed for debugging
            if os.getenv('PG_TUNING_DISABLE', '0') == '1':
                return

            # Ensure we are on a PostgreSQL connection (psycopg3 or psycopg2)
            is_pg = False
            try:
                import psycopg as psycopg3  # v3
                from psycopg import Connection as PG3Conn
                if isinstance(dbapi_connection, PG3Conn):
                    is_pg = True
            except Exception:
                pass
            if not is_pg:
                try:
                    import psycopg2  # v2
                    from psycopg2.extensions import connection as PG2Conn
                    if isinstance(dbapi_connection, PG2Conn):
                        is_pg = True
                except Exception:
                    pass
            if not is_pg:
                return

            # Sanitize numeric envs (milliseconds)
            def _digits(val: str, default: int) -> str:
                try:
                    return str(int(str(val)))
                except Exception:
                    return str(default)

            st = _digits(os.getenv('PG_STATEMENT_TIMEOUT_MS', '30000'), 30000)  # Increased to 30s
            ixt = _digits(os.getenv('PG_IDLE_IN_XACT_TIMEOUT_MS', '60000'), 60000)  # Increased to 60s
            lt = _digits(os.getenv('PG_LOCK_TIMEOUT_MS', '10000'), 10000)  # Increased to 10s
            app_name = os.getenv('PG_APPLICATION_NAME', 'nursopedia-backend')

            with dbapi_connection.cursor() as cur:
                # Avoid parameterization for SET numeric values; set directly
                cur.execute(f"SET SESSION statement_timeout = {st}")
                cur.execute(f"SET SESSION idle_in_transaction_session_timeout = {ixt}")
                cur.execute(f"SET SESSION lock_timeout = {lt}")
                cur.execute("SET SESSION TIME ZONE 'UTC'")
                # application_name: prefer param, fallback to quoted string
                try:
                    cur.execute("SET SESSION application_name = %s", (app_name,))
                except Exception:
                    _escaped = app_name.replace("'", "''")
                    cur.execute(f"SET SESSION application_name = '{_escaped}'")
                # Commit the settings
                dbapi_connection.commit()
        except Exception:
            # If anything failed, ensure the connection is not left aborted
            try:
                dbapi_connection.rollback()
            except Exception:
                pass
except Exception:
    pass

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'))
app.config['SECRET_KEY'] = 'nursopedia_secret_key_2024_very_secure'

# Database URI is normalized and assigned later in the unified builder below.
# (Removed early assignment to avoid conflicting values and to ensure SSL is appended once.)

# Optional: zero admin dashboard counters for demo/delivery
app.config['DASHBOARD_ZERO_COUNTS'] = os.getenv('DASHBOARD_ZERO_COUNTS', '0') == '1'

# Enable CORS for API routes with explicit origins and headers
CORS(
    app,
    resources={r"/api/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "expose_headers": ["Content-Type"],
    }},
    supports_credentials=False,
)

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

# Build SQLALCHEMY_DATABASE_URI from env vars (Render Postgres preferred, then MySQL, else SQLite)
# 1) Render PostgreSQL / generic Postgres
_database_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL') or os.getenv('EXTERNAL_DATABASE_URL')
PGHOST = os.getenv('PGHOST') or os.getenv('POSTGRES_HOST')
PGPORT = os.getenv('PGPORT') or os.getenv('POSTGRES_PORT', '5432')
PGUSER = os.getenv('PGUSER') or os.getenv('POSTGRES_USER')
PGPASSWORD = os.getenv('PGPASSWORD') or os.getenv('POSTGRES_PASSWORD')
PGDATABASE = os.getenv('PGDATABASE') or os.getenv('POSTGRES_DB') or os.getenv('POSTGRES_DATABASE')

from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


def _ensure_psycopg_and_ssl(uri: str) -> str:
    # Normalize to psycopg v3 driver and preserve query params
    if uri.startswith('postgres://'):
        uri = uri.replace('postgres://', 'postgresql+psycopg://', 1)
    elif uri.startswith('postgresql://'):
        uri = uri.replace('postgresql://', 'postgresql+psycopg://', 1)

    # Append sslmode if missing
    if uri.startswith('postgresql+psycopg://'):
        parsed = urlparse(uri)
        q = dict(parse_qsl(parsed.query or "", keep_blank_values=True))
        if 'sslmode' not in q:
            q['sslmode'] = os.getenv('PGSSLMODE', 'require')
        uri = urlunparse(parsed._replace(query=urlencode(q)))
    return uri


db_uri = None
if _database_url:
    db_uri = _ensure_psycopg_and_ssl(_database_url)
elif PGHOST and PGUSER and PGPASSWORD and PGDATABASE:
    db_uri = _ensure_psycopg_and_ssl(f"postgresql+psycopg://{PGUSER}:{PGPASSWORD}@{PGHOST}:{PGPORT}/{PGDATABASE}")

# 2) MySQL (Railway or custom)
if not db_uri:
    MYSQL_HOST = os.getenv('MYSQLHOST') or os.getenv('DB_HOST')
    MYSQL_PORT = os.getenv('MYSQLPORT') or os.getenv('DB_PORT', '3306')
    MYSQL_USER = os.getenv('MYSQLUSER') or os.getenv('DB_USER')
    MYSQL_PASSWORD = os.getenv('MYSQLPASSWORD') or os.getenv('DB_PASSWORD')
    MYSQL_DATABASE = os.getenv('MYSQLDATABASE') or os.getenv('DB_NAME')
    if MYSQL_HOST and MYSQL_USER and MYSQL_PASSWORD and MYSQL_DATABASE:
        # e.g., mysql+pymysql://user:pass@host:3306/dbname
        db_uri = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"

# 3) Fallback to SQLite (local dev or when no DB configured)
if not db_uri:
    _default_db_dir = '/tmp' if _is_running_on_railway() else os.path.join(os.path.dirname(__file__), 'database')
    _db_default = os.path.join(_default_db_dir, 'app.db')
    _db_path_env = os.getenv('DB_PATH')
    db_path = _db_path_env if _db_path_env else _db_default
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db_uri = f"sqlite:///{db_path}"

app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Performance optimizations
app.config['SQLALCHEMY_COMMIT_ON_TEARDOWN'] = False

# Configure engine/pool options to better handle cold starts on Railway
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,           # validate connections before use
    'pool_recycle': 280,             # recycle before MySQL 8 default wait_timeout (in secs)
    'pool_size': int(os.getenv('DB_POOL_SIZE', 10)),  # Increased pool size for better performance
    'max_overflow': int(os.getenv('DB_MAX_OVERFLOW', 20)),  # Increased max overflow
    'pool_timeout': 30,              # timeout for getting connection from pool
    'echo': False,                   # disable SQL logging in production
    'connect_args': {
        # Enforce SSL and timeouts for psycopg v3 if applicable
        'sslmode': os.getenv('PGSSLMODE', 'require'),
        'connect_timeout': int(os.getenv('PG_CONNECT_TIMEOUT', '10')),
    }
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


def ensure_academic_data_seeded():
    """Seed academic years and subjects if they do not exist (idempotent)."""
    from src.models.user import AcademicYear, Subject
    from decimal import Decimal

    years = [
        {"id": 1, "name": "الفرقة الأولى", "description": "الفرقة الأولى - كلية التمريض", "is_active": True},
        {"id": 2, "name": "الفرقة الثانية", "description": "الفرقة الثانية - كلية التمريض", "is_active": True},
    ]

    subjects = [
        {"id": 1, "name": "أساسيات تمريض (عملي)", "description": "أساسيات العناية بالمرضى والرعاية السريرية.", "academic_year_id": 1, "price": 150, "is_active": True},
        {"id": 2, "name": "أساسيات تمريض(نظري)", "description": "مبادئ وأسس التمريض النظري.", "academic_year_id": 1, "price": 150, "is_active": True},
        {"id": 3, "name": "تشريح", "description": "دراسة تركيب جسم الإنسان.", "academic_year_id": 1, "price": 30, "is_active": True},
        {"id": 4, "name": "ميكروبيولوجي", "description": "دراسة الكائنات الدقيقة وتأثيرها على الجسم.", "academic_year_id": 1, "price": 150, "is_active": True},
        {"id": 5, "name": "تمريض اطفال عملي", "description": "رعاية الأطفال المرضى سريريًا.", "academic_year_id": 2, "price": 125, "is_active": True},
        {"id": 6, "name": "تمريض اطفال نظري", "description": "مبادئ تمريض الأطفال نظريًا.", "academic_year_id": 2, "price": 125, "is_active": True},
        {"id": 7, "name": "النساء والتوليد عملي", "description": "رعاية الحوامل والمواليد سريريًا.", "academic_year_id": 2, "price": 125, "is_active": True},
        {"id": 8, "name": "النساء والتوليد نظري", "description": "مبادئ تمريض الحمل والولادة نظريًا.", "academic_year_id": 2, "price": 125, "is_active": True},
        {"id": 9, "name": "وظائف الاعضاء", "description": "دراسة وظائف أعضاء الجسم.", "academic_year_id": 1, "price": 30, "is_active": True},
        {"id": 10, "name": "كيمياء حيوية", "description": "دراسة العمليات الكيميائية في الجسم.", "academic_year_id": 1, "price": 20, "is_active": True},
        {"id": 11, "name": "جراحه اطفال", "description": "دراسة العمليات الجراحية ورعاية المرضى قبل وبعد الجراحة.", "academic_year_id": 2, "price": 20, "is_active": True},
        {"id": 12, "name": "طب اطفال", "description": "دراسة صحة وعلاج الأطفال.", "academic_year_id": 2, "price": 30, "is_active": True},
        {"id": 13, "name": "طب النساء والتوليد", "description": "دراسة الحمل، الولادة، وأمراض النساء.", "academic_year_id": 2, "price": 30, "is_active": True},
    ]

    created_any = False

    # Ensure academic years exist
    for y in years:
        if not AcademicYear.query.get(y["id"]):
            ay = AcademicYear(
                id=y["id"],
                name=y["name"],
                description=y.get("description"),
                is_active=bool(y.get("is_active", True)),
            )
            db.session.add(ay)
            created_any = True

    db.session.flush()

    # Ensure subjects exist
    for s in subjects:
        if not Subject.query.get(s["id"]):
            try:
                price_val = Decimal(str(s.get("price", 0)))
            except Exception:
                price_val = s.get("price", 0)
            sub = Subject(
                id=s["id"],
                name=s["name"],
                description=s.get("description"),
                academic_year_id=s["academic_year_id"],
                price=price_val,
                is_active=bool(s.get("is_active", True)),
            )
            db.session.add(sub)
            created_any = True

    if created_any:
        db.session.commit()
        # Fix Postgres sequences if needed to avoid duplicate key on future inserts
        try:
            if db.engine.url.get_backend_name().startswith('postgresql'):
                from sqlalchemy import text as _text
                with db.engine.connect() as conn:
                    conn.execute(_text("SELECT setval(pg_get_serial_sequence('academic_years','id'), COALESCE((SELECT MAX(id) FROM academic_years), 1), true)"))
                    conn.execute(_text("SELECT setval(pg_get_serial_sequence('subjects','id'), COALESCE((SELECT MAX(id) FROM subjects), 1), true)"))
        except Exception:
            pass

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
    ensure_academic_data_seeded()

    # Migrate old questions to new format if needed
    from src.migrate_questions import migrate_questions_to_exam_questions
    migrate_questions_to_exam_questions()

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