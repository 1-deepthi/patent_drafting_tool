"""Small Firestore repository helpers shared by the API routers.

Firestore is the only system of record (ADR-005). Documents keep their
string IDs; callers never assume numeric identifiers. Queries intentionally
avoid composite indexes: equality filters are pushed to Firestore and any
ordering is done in Python, which is fine at the scale this single-instance
app targets (ADR-003).
"""
from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import HTTPException

from app.core.firebase import db

MAX_QUERY_LIMIT = 1000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(data: dict[str, Any]) -> dict[str, Any]:
    """Drop internal/projection keys before writing a document."""
    return {k: v for k, v in data.items() if not k.startswith("_")}


def get_doc_or_none(collection: str, doc_id: str) -> dict | None:
    snap = db().collection(collection).document(str(doc_id)).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    data["id"] = snap.id
    return data


def get_doc(collection: str, doc_id: str) -> dict:
    data = get_doc_or_none(collection, doc_id)
    if data is None:
        raise HTTPException(404, f'{collection.rstrip("s").capitalize()} not found.')
    return data


def query_docs(
    collection: str,
    *,
    filters: Iterable[tuple[str, str, Any]] | None = None,
    limit: int = MAX_QUERY_LIMIT,
) -> list[dict]:
    """Run equality/array-contains filters and return plain dicts with IDs."""
    query = db().collection(collection)
    for field, op, value in filters or ():
        query = query.where(field, op, value)
    out: list[dict] = []
    for snap in query.limit(max(1, min(limit, MAX_QUERY_LIMIT))).stream():
        item = snap.to_dict() or {}
        item["id"] = snap.id
        out.append(item)
    return out


def list_docs(collection: str, *, limit: int = MAX_QUERY_LIMIT) -> list[dict]:
    return query_docs(collection, limit=limit)


def count_docs(
    collection: str, *, filters: Iterable[tuple[str, str, Any]] | None = None
) -> int:
    return len(query_docs(collection, filters=filters, limit=MAX_QUERY_LIMIT))


def create_doc(collection: str, data: dict, doc_id: str | None = None) -> dict:
    ref = (
        db().collection(collection).document(str(doc_id))
        if doc_id
        else db().collection(collection).document()
    )
    payload = clean(data)
    payload.setdefault("created_at", now_iso())
    payload["updated_at"] = now_iso()
    ref.set(payload)
    payload["id"] = ref.id
    return payload


def set_doc(collection: str, doc_id: str, data: dict) -> dict:
    payload = clean(data)
    payload["updated_at"] = now_iso()
    db().collection(collection).document(str(doc_id)).set(payload, merge=True)
    return get_doc(collection, doc_id)


def patch_doc(collection: str, doc_id: str, data: dict) -> dict:
    ref = db().collection(collection).document(str(doc_id))
    if not ref.get().exists:
        raise HTTPException(404, f'{collection.rstrip("s").capitalize()} not found.')
    payload = clean(data)
    payload["updated_at"] = now_iso()
    ref.set(payload, merge=True)
    return get_doc(collection, doc_id)


def delete_doc(collection: str, doc_id: str) -> None:
    ref = db().collection(collection).document(str(doc_id))
    if not ref.get().exists:
        raise HTTPException(404, f'{collection.rstrip("s").capitalize()} not found.')
    ref.delete()


def sort_docs(
    items: list[dict], field: str, *, reverse: bool = False
) -> list[dict]:
    """Sort in Python so Firestore composite indexes are never required."""

    def key(item: dict):
        value = item.get(field)
        return (value is None, value if value is not None else "")

    return sorted(items, key=key, reverse=reverse)
