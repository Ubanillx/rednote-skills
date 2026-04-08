"""Shared deduplication utilities for rednote-skills scripts.

Provides note_id / author_key level deduplication with a persistent JSON index.
"""

import json
import re
import unicodedata
from pathlib import Path

from note_content import clean_text

NOTE_ID_RE = re.compile(r"/(?:search_result|explore)/([0-9a-f]{24})", re.IGNORECASE)
SEARCH_RESULT_URL_RE = re.compile(r"/search_result/([0-9a-f]{24})", re.IGNORECASE)
DEFAULT_DEDUPE_PATH = "logs/rednote/note_dedupe_index.json"
DEDUPE_INDEX_VERSION = 2


def parse_note_id_from_url(note_url: str) -> str | None:
    match = NOTE_ID_RE.search(note_url or "")
    return match.group(1) if match else None


def normalize_note_detail_url(note_url: str) -> str:
    return SEARCH_RESULT_URL_RE.sub(r"/explore/\1", note_url or "")


def normalize_author_key(author_name: str) -> str:
    normalized = unicodedata.normalize("NFKC", clean_text(author_name or ""))
    return re.sub(r"\s+", "", normalized).casefold()


def empty_dedupe_index() -> dict:
    return {"version": DEDUPE_INDEX_VERSION, "items": {}, "authors": {}}


def _coerce_note_items(raw_data: dict) -> dict:
    if isinstance(raw_data, dict) and isinstance(raw_data.get("items"), dict):
        return raw_data["items"]
    if isinstance(raw_data, dict):
        return raw_data
    raise ValueError("去重索引格式无效")


def _upsert_author_index(
    authors: dict,
    *,
    author_name: str,
    author_key: str,
    note_id: str,
    timestamp: str,
    source_keyword: str,
    run_id: str,
) -> None:
    if not author_key:
        return

    existing = authors.get(author_key)
    if existing:
        existing["author_name"] = author_name or existing.get("author_name", "")
        existing["last_seen_at"] = timestamp
        existing["last_note_id"] = note_id
        existing["source_keyword"] = source_keyword
        existing["last_run_id"] = run_id
        return

    authors[author_key] = {
        "author_key": author_key,
        "author_name": author_name,
        "first_seen_at": timestamp,
        "last_seen_at": timestamp,
        "first_note_id": note_id,
        "last_note_id": note_id,
        "source_keyword": source_keyword,
        "last_run_id": run_id,
    }


def ensure_dedupe_index_shape(raw_data: dict) -> dict:
    items = _coerce_note_items(raw_data)
    authors = raw_data.get("authors", {}) if isinstance(raw_data, dict) else {}
    if not isinstance(authors, dict):
        authors = {}

    dedupe_index = {
        "version": DEDUPE_INDEX_VERSION,
        "items": items,
        "authors": authors,
    }

    for note_id, record in items.items():
        if not isinstance(record, dict):
            continue
        record.setdefault("note_id", note_id)
        author_name = clean_text(
            record.get("author_name")
            or record.get("nickname")
            or record.get("author")
            or ""
        )
        author_key = record.get("author_key") or normalize_author_key(author_name)
        record["author_name"] = author_name
        record["author_key"] = author_key
        _upsert_author_index(
            dedupe_index["authors"],
            author_name=author_name,
            author_key=author_key,
            note_id=note_id,
            timestamp=record.get("last_seen_at") or record.get("first_seen_at") or "",
            source_keyword=record.get("source_keyword", ""),
            run_id=record.get("last_run_id", ""),
        )

    return dedupe_index


def load_dedupe_index(path: Path) -> dict:
    if not path.exists():
        return empty_dedupe_index()

    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return empty_dedupe_index()

    raw_data = json.loads(raw_text)
    if not isinstance(raw_data, dict):
        raise ValueError("去重索引格式无效")

    return ensure_dedupe_index_shape(raw_data)


def save_dedupe_index(path: Path, dedupe_index: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dedupe_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_dedupe_index(
    dedupe_index: dict,
    *,
    note_id: str,
    author_name: str,
    timestamp: str,
    source_keyword: str,
    run_id: str,
    status: str,
    dedupe_reason: str = "",
) -> None:
    items = dedupe_index.setdefault("items", {})
    authors = dedupe_index.setdefault("authors", {})
    author_name = clean_text(author_name)
    author_key = normalize_author_key(author_name)
    existing = items.get(note_id)
    if existing:
        existing["last_seen_at"] = timestamp
        existing["source_keyword"] = source_keyword
        existing["last_run_id"] = run_id
        existing["author_name"] = author_name or existing.get("author_name", "")
        existing["author_key"] = author_key or existing.get("author_key", "")
        existing["status"] = status
        existing["dedupe_reason"] = dedupe_reason
    else:
        items[note_id] = {
            "note_id": note_id,
            "author_name": author_name,
            "author_key": author_key,
            "first_seen_at": timestamp,
            "last_seen_at": timestamp,
            "source_keyword": source_keyword,
            "last_run_id": run_id,
            "status": status,
            "dedupe_reason": dedupe_reason,
        }

    _upsert_author_index(
        authors,
        author_name=author_name,
        author_key=author_key,
        note_id=note_id,
        timestamp=timestamp,
        source_keyword=source_keyword,
        run_id=run_id,
    )
