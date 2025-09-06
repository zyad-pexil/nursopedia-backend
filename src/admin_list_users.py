import os
import json
import sys

# Ensure 'src' package is importable by adding backend root to sys.path
BACKEND_ROOT = os.path.dirname(os.path.dirname(__file__))  # .../nursopedia-backend
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

try:
    from src.main import app
    from src.models.user import User
except Exception as e:
    raise SystemExit(f"Import error: {e}")


def serialize_user(u):
    return {
        'id': u.id,
        'username': u.username,
        'email': u.email,
        'full_name': u.full_name,
        'phone_number': u.phone_number,
        'user_type': u.user_type,
        'is_active': bool(u.is_active),
        'created_at': u.created_at.isoformat() if getattr(u, 'created_at', None) else None,
        'last_login': u.last_login.isoformat() if getattr(u, 'last_login', None) else None,
    }


if __name__ == "__main__":
    with app.app_context():
        users = User.query.order_by(User.id.asc()).all()
        print(json.dumps([serialize_user(u) for u in users], ensure_ascii=False, indent=2))