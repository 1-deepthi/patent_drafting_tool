from datetime import datetime, timezone
from typing import Any
from fastapi import HTTPException
from app.core.firebase import db

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def clean(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if not k.startswith('_')}

def get_doc(collection: str, doc_id: str) -> dict:
    snap = db().collection(collection).document(str(doc_id)).get()
    if not snap.exists:
        raise HTTPException(404, f'{collection.rstrip("s").capitalize()} not found.')
    data = snap.to_dict() or {}
    data['id'] = snap.id
    return data

def list_docs(collection: str, *, limit: int = 100) -> list[dict]:
    out = []
    for snap in db().collection(collection).limit(max(1, min(limit, 500))).stream():
        item = snap.to_dict() or {}
        item['id'] = snap.id
        out.append(item)
    return out

def create_doc(collection: str, data: dict, doc_id: str | None = None) -> dict:
    ref = db().collection(collection).document(str(doc_id)) if doc_id else db().collection(collection).document()
    payload = clean(data)
    payload.setdefault('created_at', now_iso())
    payload['updated_at'] = now_iso()
    ref.set(payload)
    payload['id'] = ref.id
    return payload

def patch_doc(collection: str, doc_id: str, data: dict) -> dict:
    ref = db().collection(collection).document(str(doc_id))
    if not ref.get().exists:
        raise HTTPException(404, f'{collection.rstrip("s").capitalize()} not found.')
    payload = clean(data)
    payload['updated_at'] = now_iso()
    ref.set(payload, merge=True)
    return get_doc(collection, doc_id)

def delete_doc(collection: str, doc_id: str) -> None:
    ref = db().collection(collection).document(str(doc_id))
    if not ref.get().exists:
        raise HTTPException(404, f'{collection.rstrip("s").capitalize()} not found.')
    ref.delete()
