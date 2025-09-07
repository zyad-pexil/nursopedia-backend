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

# Database configuration (supports external volume via DB_PATH)
# Default to /tmp on Railway (ephemeral, but writable); use repo folder locally

def _is_running_on_railway() -> bool:
    # Railway sets these env vars automatically
    return bool(
        os.getenv('RAILWAY_PROJECT_ID')
        or os.getenv('RAILWAY_ENVIRONMENT')
        or os.getenv('RAILWAY_ENVIRONMENT_NAME')
    )

_default_db_dir = '/tmp' if _is_running_on_railway() else os.path.join(os.path.dirname(__file__), 'database')
_db_default = os.path.join(_default_db_dir, 'app.db')

# Allow override via DB_PATH if provided
_db_path_env = os.getenv('DB_PATH')
db_path = _db_path_env if _db_path_env else _db_default

# Ensure parent directory exists
os.makedirs(os.path.dirname(db_path), exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
migrate = Migrate(app, db)
with app.app_context():
    db.create_all()

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