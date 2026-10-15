"""Lazy Firebase Admin initialization. Never store service-account keys in Git."""
import os
from pathlib import Path
from typing import Any
import firebase_admin
from firebase_admin import credentials, firestore, auth, storage
from app.core.config import settings

_app = None
_db = None
_bucket = None

class FirebaseNotConfigured(RuntimeError):
    pass

def initialize_firebase():
    global _app, _db, _bucket
    if _app is not None:
        return _app
    if settings.firebase_emulator_host:
        os.environ['FIRESTORE_EMULATOR_HOST'] = settings.firebase_emulator_host
    try:
        _app = firebase_admin.get_app()
    except ValueError:
        key_path = Path(settings.firebase_service_account_path)
        options: dict[str, Any] = {}
        if settings.firebase_project_id:
            options['projectId'] = settings.firebase_project_id
        if settings.firebase_storage_bucket:
            options['storageBucket'] = settings.firebase_storage_bucket
        if key_path.is_file():
            _app = firebase_admin.initialize_app(credentials.Certificate(str(key_path)), options or None)
        elif settings.firebase_project_id:
            # Application Default Credentials are useful on supported hosts/emulators.
            _app = firebase_admin.initialize_app(options=options or None)
        else:
            raise FirebaseNotConfigured('Configure FIREBASE_PROJECT_ID and a service-account JSON path in .env.')
    _db = firestore.client(_app)
    if settings.firebase_storage_bucket:
        _bucket = storage.bucket(app=_app)
    return _app

def db():
    if _db is None:
        initialize_firebase()
    return _db

def bucket():
    if _bucket is None:
        initialize_firebase()
        if _bucket is None:
            raise FirebaseNotConfigured('Set FIREBASE_STORAGE_BUCKET in .env to enable file storage.')
    return _bucket

def verify_id_token(token: str) -> dict:
    initialize_firebase()
    return auth.verify_id_token(token, app=_app, check_revoked=True)

def create_custom_token(uid: str) -> str:
    initialize_firebase()
    return auth.create_custom_token(uid, app=_app).decode('utf-8')
