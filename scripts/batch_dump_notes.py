#!/usr/bin/env python3
"""Batch export note data from a URL list with deduplication.

Accepts a list of note URLs, deduplicates by note_id + author,
and exports structured note data as JSON + XLSX.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from _bootstrap_env import ensure_local_venv

ensure_local_venv()

from openpyxl import Workbook

from action_delay import resolve_delay_seconds, sleep_random_cooldown
from batch_generate_comment_materials import build_article_info, fetch_note_data, write_json
from dedupe_utils import (
    DEFAULT_DEDUPE_PATH,
    load_dedupe_index,
    normalize_author_key,
    parse_note_id_from_url,
    save_dedupe_index,
    update_dedupe_index,
)
from official_risk_guard import OfficialRiskDetectedError, RiskStopTracker


DEFAULT_OUTPUT_DIR = "deliveries/bid_notes"

XLSX_COLUMNS = [
    "note_id",
    "note_url",
    "title",
    "nickname",
    "desc",
    "tags",
    "note_type",
    "publish_time",
    "update_time",
    "ip_location",
    "liked_count",
    "collected_count",
    "comment_count",
    "share_count",
]


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def load_url_list(input_path: str) -> list[str]:
    """Parse input JSON into a flat list of note URLs.

    Accepted formats:
      - JSON array of strings: ["url1", "url2"]
      - JSON array of objects with note_url: [{"note_url": "..."}, ...]
      - JSON object with items key: {"items": [...]}
    """
    raw_text = Path(input_path).read_text(encoding="utf-8").strip()
    if not raw_text:
        raise ValueError("Input file is empty")

    data = json.loads(raw_text)

    # Object with items key
    if isinstance(data, dict):
        items = data.get("items")
        if not isinstance(items, list):
            raise ValueError("Input JSON object must contain an 'items' array")
        data = items

    if not isinstance(data, list):
        raise ValueError("Input must be a JSON array or an object with an 'items' key")

    urls: list[str] = []
    for index, entry in enumerate(data, start=1):
        if isinstance(entry, str):
            url = entry.strip()
        elif isinstance(entry, dict):
            url = str(entry.get("note_url", "")).strip()
        else:
            raise ValueError(f"Entry #{index} is neither a string nor an object")

        if not url:
            raise ValueError(f"Entry #{index} has no note_url")
        urls.append(url)

    return urls


# ---------------------------------------------------------------------------
# XLSX writer
# ---------------------------------------------------------------------------

def _flatten_item_for_xlsx(item: dict) -> dict:
    article = item.get("article_info", {})
    return {
        "note_id": item.get("note_id", ""),
        "note_url": item.get("note_url", ""),
        "title": article.get("title", ""),
        "nickname": article.get("nickname", ""),
        "desc": article.get("desc", ""),
        "tags": json.dumps(article.get("tags", []), ensure_ascii=False),
        "note_type": article.get("note_type", ""),
        "publish_time": article.get("publish_time", ""),
        "update_time": article.get("update_time", ""),
        "ip_location": article.get("ip_location", ""),
        "liked_count": article.get("liked_count", ""),
        "collected_count": article.get("collected_count", ""),
        "comment_count": article.get("comment_count", ""),
        "share_count": article.get("share_count", ""),
    }


def write_xlsx(path: Path, items: list[dict]) -> None:
    """Write items to an XLSX file with simplified columns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "notes"

    # Header row
    sheet.append(XLSX_COLUMNS)

    # Data rows
    for item in items:
        row = _flatten_item_for_xlsx(item)
        sheet.append([row[column] for column in XLSX_COLUMNS])

    workbook.save(path)


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_batch(
    urls: list[str],
    *,
    output_dir: Path,
    dedupe_path: Path,
    delay_seconds: float,
    limit: int,
    dry_run: bool,
    risk_stop_after: int,
    note_read_cooldown_min_seconds: float,
    note_read_cooldown_max_seconds: float,
    batch_read_cooldown_every: int,
    batch_read_cooldown_min_seconds: float,
    batch_read_cooldown_max_seconds: float,
) -> dict:
    if int(batch_read_cooldown_every) <= 0:
        raise ValueError("batch_read_cooldown_every must be greater than 0")

    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    created_at = datetime.now().isoformat(timespec="seconds")
    output_dir.mkdir(parents=True, exist_ok=True)
    risk_tracker = RiskStopTracker(stop_after=risk_stop_after)

    json_path = output_dir / f"{run_id}.json"
    xlsx_path = output_dir / f"{run_id}.xlsx"

    if dry_run:
        return {
            "run_id": run_id,
            "input_urls": len(urls),
            "attempted_note_reads": 0,
            "deduped_skipped": 0,
            "note_id_skipped": 0,
            "author_skipped": 0,
            "captured": 0,
            "failed": 0,
            "json_path": str(json_path),
            "xlsx_path": str(xlsx_path),
            "dedupe_path": str(dedupe_path),
            "delay_seconds": delay_seconds,
            "limit": limit,
            "dry_run": True,
            **risk_tracker.snapshot(),
        }

    # ------------------------------------------------------------------
    # First pass: pre-filter by note_id extracted from URL
    # ------------------------------------------------------------------
    dedupe_index = load_dedupe_index(dedupe_path)
    dedupe_items = dedupe_index.setdefault("items", {})
    dedupe_authors = dedupe_index.setdefault("authors", {})

    pending_urls: list[str] = []
    deduped_skipped = 0
    for url in urls:
        note_id = parse_note_id_from_url(url)
        if note_id and note_id in dedupe_items:
            deduped_skipped += 1
            continue
        pending_urls.append(url)

    # ------------------------------------------------------------------
    # Second pass: fetch and deduplicate with authoritative data
    # ------------------------------------------------------------------
    seen_note_ids: set[str] = set()
    seen_author_keys: set[str] = set()
    items: list[dict] = []
    attempted_note_reads = 0
    note_id_skipped = 0
    author_skipped = 0
    failed = 0
    captured = 0

    for url in pending_urls:
        if risk_tracker.stopped_due_to_risk:
            break

        if limit > 0 and captured >= limit:
            break

        # Apply per-note cooldown before each fetch
        if attempted_note_reads > 0:
            sleep_random_cooldown(
                "读取下一篇笔记前冷却",
                note_read_cooldown_min_seconds,
                note_read_cooldown_max_seconds,
            )

        attempted_note_reads += 1

        try:
            note_data = fetch_note_data(url, delay_seconds)
            risk_tracker.record_success()

            article_info = build_article_info(note_data)

            # Authoritative note_id from the fetched data
            authoritative_note_id = note_data.get("noteId") or parse_note_id_from_url(url)
            if not authoritative_note_id:
                print(f"⚠️ 无法解析 note_id: {url}")
                failed += 1
                continue

            # Authoritative note_id dedupe check
            if authoritative_note_id in dedupe_items or authoritative_note_id in seen_note_ids:
                note_id_skipped += 1
                deduped_skipped += 1
                continue

            # Author dedupe check
            author_name = article_info.get("nickname", "")
            author_key = normalize_author_key(author_name)
            if author_key and (
                author_key in dedupe_authors or author_key in seen_author_keys
            ):
                author_skipped += 1
                deduped_skipped += 1
                seen_note_ids.add(authoritative_note_id)
                update_dedupe_index(
                    dedupe_index,
                    note_id=authoritative_note_id,
                    author_name=author_name,
                    timestamp=created_at,
                    source_keyword="",
                    run_id=run_id,
                    status="skipped",
                    dedupe_reason="author_duplicate",
                )
                continue

            # Passed all checks — record the capture
            item = {
                "note_id": authoritative_note_id,
                "note_url": url,
                "article_info": article_info,
            }
            items.append(item)
            captured += 1
            seen_note_ids.add(authoritative_note_id)
            if author_key:
                seen_author_keys.add(author_key)

            update_dedupe_index(
                dedupe_index,
                note_id=authoritative_note_id,
                author_name=author_name,
                timestamp=created_at,
                source_keyword="",
                run_id=run_id,
                status="captured",
            )

        except OfficialRiskDetectedError as exc:
            risk_state = risk_tracker.record_risk(exc.matched_phrase, exc.detail)
            print(f"⚠️ 读取笔记触发官方风控: {url} -> {exc}")
            failed += 1
            if risk_state["stopped_due_to_risk"]:
                break

        except Exception as exc:
            print(f"⚠️ 抓取笔记失败: {url} -> {exc}")
            failed += 1

        # Batch cooldown every N reads
        if (
            attempted_note_reads > 0
            and attempted_note_reads % int(batch_read_cooldown_every) == 0
            and not risk_tracker.stopped_due_to_risk
        ):
            sleep_random_cooldown(
                "批次冷却",
                batch_read_cooldown_min_seconds,
                batch_read_cooldown_max_seconds,
            )

    # ------------------------------------------------------------------
    # Write outputs
    # ------------------------------------------------------------------
    aggregate_payload = {
        "run_id": run_id,
        "created_at": created_at,
        "counts": {
            "input_urls": len(urls),
            "attempted_note_reads": attempted_note_reads,
            "deduped_skipped": deduped_skipped,
            "note_id_skipped": note_id_skipped,
            "author_skipped": author_skipped,
            "captured": captured,
            "failed": failed,
        },
        **risk_tracker.snapshot(),
        "items": items,
    }

    write_json(json_path, aggregate_payload)
    write_xlsx(xlsx_path, items)
    save_dedupe_index(dedupe_path, dedupe_index)

    summary = {
        "run_id": run_id,
        "input_urls": len(urls),
        "attempted_note_reads": attempted_note_reads,
        "deduped_skipped": deduped_skipped,
        "note_id_skipped": note_id_skipped,
        "author_skipped": author_skipped,
        "captured": captured,
        "failed": failed,
        "json_path": str(json_path),
        "xlsx_path": str(xlsx_path),
        "dedupe_path": str(dedupe_path),
        **risk_tracker.snapshot(),
    }
    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="批量导出笔记数据（JSON + XLSX），支持去重",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input JSON file path (array of URLs, array of objects with note_url, or object with items key)",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--dedupe-path",
        default=DEFAULT_DEDUPE_PATH,
        help="Dedupe index path (default: from dedupe_utils)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max notes to capture; 0 means no limit (default: 0)",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="Fixed delay per note in seconds (default: 0.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only validate input, don't fetch",
    )
    parser.add_argument(
        "--risk-stop-after",
        type=int,
        default=3,
        help="Consecutive risk detections before stopping (default: 3)",
    )
    parser.add_argument(
        "--note-read-cooldown-min-seconds",
        type=float,
        default=4.0,
        help="Min cooldown between note reads (default: 4.0)",
    )
    parser.add_argument(
        "--note-read-cooldown-max-seconds",
        type=float,
        default=7.0,
        help="Max cooldown between note reads (default: 7.0)",
    )
    parser.add_argument(
        "--batch-read-cooldown-every",
        type=int,
        default=3,
        help="Trigger batch cooldown every N reads (default: 3)",
    )
    parser.add_argument(
        "--batch-read-cooldown-min-seconds",
        type=float,
        default=20.0,
        help="Min batch cooldown seconds (default: 20.0)",
    )
    parser.add_argument(
        "--batch-read-cooldown-max-seconds",
        type=float,
        default=35.0,
        help="Max batch cooldown seconds (default: 35.0)",
    )
    args = parser.parse_args()

    urls = load_url_list(args.input)
    resolved_delay = resolve_delay_seconds(args.delay_seconds)

    summary = run_batch(
        urls,
        output_dir=Path(args.output_dir),
        dedupe_path=Path(args.dedupe_path),
        delay_seconds=resolved_delay,
        limit=args.limit,
        dry_run=args.dry_run,
        risk_stop_after=args.risk_stop_after,
        note_read_cooldown_min_seconds=args.note_read_cooldown_min_seconds,
        note_read_cooldown_max_seconds=args.note_read_cooldown_max_seconds,
        batch_read_cooldown_every=args.batch_read_cooldown_every,
        batch_read_cooldown_min_seconds=args.batch_read_cooldown_min_seconds,
        batch_read_cooldown_max_seconds=args.batch_read_cooldown_max_seconds,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
