from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv('STREAMBOX_DATA_DIR', BASE_DIR / 'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv('STREAMBOX_DB_PATH', DATA_DIR / 'streambox.sqlite3'))
DATABASE_URL = os.getenv('DATABASE_URL')
TEMP_DIR = Path(os.getenv('STREAMBOX_TEMP_DIR', DATA_DIR / 'tmp'))
TEMP_DIR.mkdir(parents=True, exist_ok=True)

LOCAL_STORAGE_DIR = Path(os.getenv('STREAMBOX_STORAGE_DIR', DATA_DIR / 'storage'))
LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

B2_KEY_ID = os.getenv('B2_KEY_ID')
B2_APPLICATION_KEY = os.getenv('B2_APPLICATION_KEY')
B2_BUCKET_NAME = os.getenv('B2_BUCKET_NAME')
B2_ENDPOINT = os.getenv('B2_ENDPOINT')
B2_REGION = os.getenv('B2_REGION')

SECRET_KEY = os.getenv('SECRET_KEY', 'dev-streambox-secret-key-change-me')
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH', '')

APP_HOST = os.getenv('APP_HOST', '127.0.0.1')
APP_PORT = int(os.getenv('APP_PORT', '5000'))
DEBUG = os.getenv('FLASK_DEBUG', '1') == '1'

API_ALLOWED_ORIGIN = os.getenv('API_ALLOWED_ORIGIN', 'http://localhost:5173')
SESSION_COOKIE_NAME = os.getenv('SESSION_COOKIE_NAME', 'streambox_session')

MAX_UPLOAD_BYTES = int(1.5 * 1024 * 1024 * 1024)
UPLOAD_SESSION_TTL_SECONDS = int(os.getenv('UPLOAD_SESSION_TTL_SECONDS', str(60 * 60)))
SIGNED_URL_TTL_SECONDS = int(os.getenv('SIGNED_URL_TTL_SECONDS', str(15 * 60)))
B2_MULTIPART_PART_SIZE_BYTES = 16 * 1024 * 1024
# URLs are intentionally short-lived even if an environment value is set too high.
B2_MULTIPART_URL_TTL_SECONDS = max(1, min(int(os.getenv('B2_MULTIPART_URL_TTL_SECONDS', str(15 * 60))), 60 * 60))
B2_MULTIPART_URL_BATCH_SIZE = 10

STORAGE_BACKEND = os.getenv('STORAGE_BACKEND', 'local').lower()
