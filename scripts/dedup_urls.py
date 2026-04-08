#!/usr/bin/env python3
"""Deduplicate note URLs against a persistent dedupe index.

Pure data script — does not launch a browser.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap_env import ensure_local_venv

ensure_local_venv()

from dedupe_utils import (
    DEFAULT_DEDUPE_PATH,
    load_dedupe_index,
    parse_note_id_from_url,
    save_dedupe_index,
    update_dedupe_index,
)
from note_content import clean_text


def _load_input(input_path: Path):
    """Load and normalise input data into a list of (url, original_entry) tuples.

    Supports three auto-detected formats:
      - Array of strings:  ["url1", "url2"]
      - Array of objects:  [{"note_url": "...", ...}]
      - Object with items: {"items": [...]}
    """
    raw_text = input_path.read_text(encoding="utf-8").strip()
    data = json.loads(raw_text)

    # Object with "items" key
    if isinstance(data, dict):
        items = data.get("items")
        if not isinstance(items, list):
            print("错误: 输入 JSON 对象缺少 'items' 数组", file=sys.stderr)
            sys.exit(1)
        entries = items
    elif isinstance(data, list):
        entries = data
    else:
        print("错误: 输入 JSON 必须是数组或对象", file=sys.stderr)
        sys.exit(1)

    results = []
    for entry in entries:
        if isinstance(entry, str):
            results.append((entry, None))
        elif isinstance(entry, dict):
            url = clean_text(entry.get("note_url", ""))
            if url:
                results.append((url, entry))
        # skip anything else silently
    return results


def main():
    parser = argparse.ArgumentParser(
        description="去重笔记 URL（纯数据脚本，不启动浏览器）",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="输入 JSON 文件路径（URL 数组或含 note_url 字段的对象数组）",
    )
    parser.add_argument(
        "--output",
        default=None,
        type=Path,
        help="输出去重后 URL 的 JSON 文件路径（默认输出到 stdout）",
    )
    parser.add_argument(
        "--dedupe-path",
        default=DEFAULT_DEDUPE_PATH,
        type=Path,
        help=f"去重索引文件路径（默认: {DEFAULT_DEDUPE_PATH}）",
    )
    parser.add_argument(
        "--update-index",
        action="store_true",
        help="将新出现的 note_id 写入去重索引",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅显示统计信息，不写入输出文件",
    )
    args = parser.parse_args()

    # Load dedupe index
    dedupe_index = load_dedupe_index(args.dedupe_path)

    # Load input
    entries = _load_input(args.input)
    total_input = len(entries)

    unique_entries = []
    duplicated_count = 0
    seen_note_ids: set[str] = set()

    for url, original in entries:
        note_id = parse_note_id_from_url(url)
        if note_id and (note_id in dedupe_index.get("items", {}) or note_id in seen_note_ids):
            duplicated_count += 1
            continue
        if note_id:
            seen_note_ids.add(note_id)
        unique_entries.append((url, original, note_id))

    # Optionally update index
    if args.update_index:
        now = datetime.now(timezone.utc).isoformat()
        for _url, _original, note_id in unique_entries:
            if not note_id:
                continue
            update_dedupe_index(
                dedupe_index,
                note_id=note_id,
                author_name="",
                timestamp=now,
                source_keyword="",
                run_id="",
                status="seen",
            )
        save_dedupe_index(args.dedupe_path, dedupe_index)
        print(f"已更新去重索引: {args.dedupe_path}", file=sys.stderr)

    # Build output — preserve original objects when available
    output = []
    for url, original, _note_id in unique_entries:
        output.append(original if original is not None else url)

    # Write output
    if not args.dry_run:
        output_json = json.dumps(output, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output_json + "\n", encoding="utf-8")
            print(f"已写入: {args.output}", file=sys.stderr)
        else:
            print(output_json)

    # Summary
    unique_count = len(unique_entries)
    print(
        f"统计: 总输入={total_input}, 唯一={unique_count}, 重复={duplicated_count}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
