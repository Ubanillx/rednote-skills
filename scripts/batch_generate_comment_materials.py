import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from _bootstrap_env import ensure_local_venv

ensure_local_venv()

from openpyxl import Workbook

from action_delay import resolve_delay_seconds, sleep_random_cooldown
from browser_profile import (
    close_profile_context,
    launch_profile_context,
    page_requires_login,
)
from dedupe_utils import (
    DEDUPE_INDEX_VERSION,
    DEFAULT_DEDUPE_PATH,
    load_dedupe_index,
    normalize_author_key,
    normalize_note_detail_url,
    parse_note_id_from_url,
    save_dedupe_index,
    update_dedupe_index,
)
from note_content import clean_text, extract_note_data, humanize_note_page_before_extract
from official_risk_guard import OfficialRiskDetectedError, RiskStopTracker
from search_note_by_key_word import search


DEFAULT_OUTPUT_DIR = "logs/rednote/generated_comment_materials"

CSV_COLUMNS = [
    "note_id",
    "note_url",
    "source_keyword",
    "title",
    "desc",
    "tags",
    "nickname",
    "note_type",
    "publish_time",
    "update_time",
    "ip_location",
    "liked_count",
    "collected_count",
    "comment_count",
    "share_count",
    "image_urls",
    "video_url",
    "comment_status",
    "comment_text",
    "comment_style",
    "comment_notes",
    "reply_status",
    "reply_text",
    "reply_target",
    "reply_notes",
]


def load_json_payload(input_path: str | None) -> object:
    if input_path:
        raw_text = Path(input_path).read_text(encoding="utf-8")
    else:
        raw_text = sys.stdin.read()

    raw_text = raw_text.strip()
    if not raw_text:
        raise ValueError("批量抓取评论素材输入不能为空")

    return json.loads(raw_text)


def normalize_payloads(payload: object) -> list[dict]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            items = payload["items"]
        else:
            items = []
            for keyword, value in payload.items():
                if not isinstance(keyword, str):
                    raise ValueError("关键词必须是字符串")
                if isinstance(value, int):
                    items.append({"keyword": keyword, "top_n": value})
                elif isinstance(value, dict):
                    item = dict(value)
                    item["keyword"] = keyword
                    items.append(item)
                else:
                    raise ValueError(
                        "JSON 对象映射的值必须是 top_n 整数，或包含 top_n/meta 的对象"
                    )
    else:
        raise ValueError("批量抓取评论素材输入必须是 JSON 数组或 JSON 对象")

    normalized = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, str):
            item = {"keyword": item}
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 条记录不是 JSON 对象或字符串")

        keyword = str(item.get("keyword", "")).strip()
        if not keyword:
            raise ValueError(f"第 {index} 条记录缺少 keyword")

        normalized.append(
            {
                "index": index,
                "keyword": keyword,
                "top_n": item.get("top_n"),
                "start_index": item.get("start_index"),
                "end_index": item.get("end_index"),
                "max_scroll_rounds": item.get("max_scroll_rounds"),
                "max_idle_scroll_rounds": item.get("max_idle_scroll_rounds"),
                "delay_seconds": item.get("delay_seconds"),
                "filter": item.get("filter"),
                "meta": item.get("meta"),
            }
        )

    return normalized



def default_comment_info() -> dict:
    return {
        "status": "pending",
        "comment_text": "",
        "comment_style": "",
        "comment_notes": "",
    }


def default_reply_comment_info() -> dict:
    return {
        "status": "pending",
        "reply_text": "",
        "reply_target": "",
        "reply_notes": "",
    }


def _safe_video_url(note_data: dict) -> str:
    try:
        return (
            note_data.get("video", {})
            .get("media", {})
            .get("stream", {})
            .get("h264", [{}])[0]
            .get("masterUrl", "")
        )
    except Exception:
        return ""


def build_article_info(note_data: dict) -> dict:
    interact_info = note_data.get("interactInfo", {})
    tags = [
        clean_text(tag.get("name", ""))
        for tag in note_data.get("tagList", [])
        if clean_text(tag.get("name", ""))
    ]
    image_urls = [
        image.get("urlDefault", "")
        for image in note_data.get("imageList", [])
        if image.get("urlDefault")
    ]

    publish_time = note_data.get("time")
    update_time = note_data.get("lastUpdateTime")
    publish_time_iso = (
        datetime.fromtimestamp(publish_time / 1000).isoformat(timespec="seconds")
        if publish_time
        else ""
    )
    update_time_iso = (
        datetime.fromtimestamp(update_time / 1000).isoformat(timespec="seconds")
        if update_time
        else ""
    )

    return {
        "title": clean_text(note_data.get("title", "")),
        "desc": clean_text(note_data.get("desc", "")),
        "tags": tags,
        "nickname": clean_text(note_data.get("user", {}).get("nickname", "")),
        "note_type": clean_text(note_data.get("type", "")),
        "publish_time": publish_time_iso,
        "update_time": update_time_iso,
        "ip_location": clean_text(note_data.get("ipLocation", "")),
        "liked_count": str(interact_info.get("likedCount", "")),
        "collected_count": str(interact_info.get("collectedCount", "")),
        "comment_count": str(interact_info.get("commentCount", "")),
        "share_count": str(interact_info.get("shareCount", "")),
        "image_urls": image_urls,
        "video_url": _safe_video_url(note_data),
    }


def fetch_note_data(note_url: str, delay_seconds: float = 0.0) -> dict:
    detail_url = normalize_note_detail_url(note_url)
    driver = browser = context = page = settings = chrome_process = None
    try:
        driver, browser, context, page, settings, chrome_process = launch_profile_context(
            headless=False,
            startup_url=detail_url,
        )
        print(f"🌐 打开文章详情页：{detail_url}")
        page.wait_for_timeout(1000)
        if page_requires_login(page):
            raise RuntimeError(
                f'❌ 当前 Chrome {settings["profile_directory"]} 未登录，请先运行 '
                "python3 scripts/manual_login.py"
            )

        humanize_note_page_before_extract(page, "读取文章内容", delay_seconds)
        return extract_note_data(page)
    finally:
        if driver:
            close_profile_context(
                driver,
                browser,
                page=page,
                settings=settings,
                chrome_process=chrome_process,
            )


def build_item(note_url: str, source_keyword: str, note_data: dict) -> dict:
    detail_url = normalize_note_detail_url(note_url)
    note_id = note_data.get("noteId") or parse_note_id_from_url(detail_url)
    if not note_id:
        raise RuntimeError("未能从文章数据中解析 note_id")

    return {
        "note_id": note_id,
        "note_url": detail_url,
        "source_keyword": source_keyword,
        "article_info": build_article_info(note_data),
        "comment_info": default_comment_info(),
        "reply_comment_info": default_reply_comment_info(),
    }


def flatten_item(item: dict) -> dict:
    article = item["article_info"]
    comment = item["comment_info"]
    reply = item["reply_comment_info"]
    return {
        "note_id": item["note_id"],
        "note_url": item["note_url"],
        "source_keyword": item["source_keyword"],
        "title": article["title"],
        "desc": article["desc"],
        "tags": json.dumps(article["tags"], ensure_ascii=False),
        "nickname": article["nickname"],
        "note_type": article["note_type"],
        "publish_time": article["publish_time"],
        "update_time": article["update_time"],
        "ip_location": article["ip_location"],
        "liked_count": article["liked_count"],
        "collected_count": article["collected_count"],
        "comment_count": article["comment_count"],
        "share_count": article["share_count"],
        "image_urls": json.dumps(article["image_urls"], ensure_ascii=False),
        "video_url": article["video_url"],
        "comment_status": comment["status"],
        "comment_text": comment["comment_text"],
        "comment_style": comment["comment_style"],
        "comment_notes": comment["comment_notes"],
        "reply_status": reply["status"],
        "reply_text": reply["reply_text"],
        "reply_target": reply["reply_target"],
        "reply_notes": reply["reply_notes"],
    }


def write_csv(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for item in items:
            writer.writerow(flatten_item(item))


def write_xlsx(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "materials"
    sheet.append(CSV_COLUMNS)
    for item in items:
        row = flatten_item(item)
        sheet.append([row[column] for column in CSV_COLUMNS])
    workbook.save(path)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_batch(
    payloads: list[dict],
    *,
    output_dir: Path,
    dedupe_path: Path,
    default_top_n: int,
    default_delay_seconds: float,
    risk_stop_after: int = 3,
    note_read_cooldown_min_seconds: float = 4.0,
    note_read_cooldown_max_seconds: float = 7.0,
    batch_read_cooldown_every: int = 3,
    batch_read_cooldown_min_seconds: float = 20.0,
    batch_read_cooldown_max_seconds: float = 35.0,
    dry_run: bool = False,
) -> dict:
    if int(batch_read_cooldown_every) <= 0:
        raise ValueError("batch_read_cooldown_every must be greater than 0")

    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    created_at = datetime.now().isoformat(timespec="seconds")
    output_dir.mkdir(parents=True, exist_ok=True)
    risk_tracker = RiskStopTracker(stop_after=risk_stop_after)

    json_path = output_dir / f"{run_id}.json"
    csv_path = output_dir / f"{run_id}.csv"
    xlsx_path = output_dir / f"{run_id}.xlsx"

    if dry_run:
        return {
            "run_id": run_id,
            "total_keywords": len(payloads),
            "attempted_urls": 0,
            "deduped_skipped": 0,
            "note_id_skipped": 0,
            "author_skipped": 0,
            "captured": 0,
            "failed": 0,
            "json_path": str(json_path),
            "csv_path": str(csv_path),
            "xlsx_path": str(xlsx_path),
            "dedupe_path": str(dedupe_path),
            "attempted_note_reads": 0,
            "risk_stop_after": int(risk_stop_after),
            "note_read_cooldown_min_seconds": float(note_read_cooldown_min_seconds),
            "note_read_cooldown_max_seconds": float(note_read_cooldown_max_seconds),
            "batch_read_cooldown_every": int(batch_read_cooldown_every),
            "batch_read_cooldown_min_seconds": float(batch_read_cooldown_min_seconds),
            "batch_read_cooldown_max_seconds": float(batch_read_cooldown_max_seconds),
            **risk_tracker.snapshot(),
        }

    dedupe_index = load_dedupe_index(dedupe_path)
    dedupe_items = dedupe_index.setdefault("items", {})
    dedupe_authors = dedupe_index.setdefault("authors", {})
    seen_note_ids = set()
    seen_author_keys = set()
    items = []

    attempted_urls = 0
    attempted_note_reads = 0
    deduped_skipped = 0
    note_id_skipped = 0
    author_skipped = 0
    failed = 0

    for payload in payloads:
        if risk_tracker.stopped_due_to_risk:
            break

        keyword = payload["keyword"]
        top_n = int(payload["top_n"])
        delay_seconds = resolve_delay_seconds(payload["delay_seconds"])

        try:
            urls = search(
                keyword,
                top_n,
                delay_seconds,
                payload.get("filter"),
                start_index=int(payload.get("start_index") or 1),
                end_index=(
                    int(payload["end_index"])
                    if payload.get("end_index") is not None
                    else None
                ),
                max_scroll_rounds=(
                    int(payload["max_scroll_rounds"])
                    if payload.get("max_scroll_rounds") is not None
                    else None
                ),
                max_idle_scroll_rounds=(
                    int(payload["max_idle_scroll_rounds"])
                    if payload.get("max_idle_scroll_rounds") is not None
                    else None
                ),
            )
        except OfficialRiskDetectedError as exc:
            risk_state = risk_tracker.record_risk(exc.matched_phrase, exc.detail)
            print(f"⚠️ 关键词搜索触发官方风控：{keyword} -> {exc}")
            failed += 1
            if risk_state["stopped_due_to_risk"]:
                break
            continue
        except Exception as exc:
            print(f"⚠️ 关键词搜索失败：{keyword} -> {exc}")
            failed += 1
            continue

        if any(isinstance(item, str) and item.startswith("❌") for item in urls):
            print(f"⚠️ 关键词搜索失败：{keyword} -> {urls[0]}")
            failed += 1
            continue
        risk_tracker.record_success()

        for note_url in urls:
            if risk_tracker.stopped_due_to_risk:
                break

            attempted_urls += 1
            parsed_note_id = parse_note_id_from_url(note_url)
            if parsed_note_id and (
                parsed_note_id in dedupe_items or parsed_note_id in seen_note_ids
            ):
                deduped_skipped += 1
                note_id_skipped += 1
                continue

            if attempted_note_reads > 0:
                sleep_random_cooldown(
                    "读取下一篇文章前冷却",
                    note_read_cooldown_min_seconds,
                    note_read_cooldown_max_seconds,
                )

            attempted_note_reads += 1
            try:
                note_data = fetch_note_data(note_url, delay_seconds)
                risk_tracker.record_success()
                item = build_item(note_url, keyword, note_data)
                note_id = item["note_id"]
                if note_id in dedupe_items or note_id in seen_note_ids:
                    deduped_skipped += 1
                    note_id_skipped += 1
                    continue

                author_name = item["article_info"].get("nickname", "")
                author_key = normalize_author_key(author_name)
                if author_key and (
                    author_key in dedupe_authors or author_key in seen_author_keys
                ):
                    deduped_skipped += 1
                    author_skipped += 1
                    seen_note_ids.add(note_id)
                    update_dedupe_index(
                        dedupe_index,
                        note_id=note_id,
                        author_name=author_name,
                        timestamp=created_at,
                        source_keyword=keyword,
                        run_id=run_id,
                        status="skipped",
                        dedupe_reason="author_duplicate",
                    )
                    continue

                items.append(item)
                seen_note_ids.add(note_id)
                if author_key:
                    seen_author_keys.add(author_key)
                update_dedupe_index(
                    dedupe_index,
                    note_id=note_id,
                    author_name=author_name,
                    timestamp=created_at,
                    source_keyword=keyword,
                    run_id=run_id,
                    status="captured",
                )
            except OfficialRiskDetectedError as exc:
                risk_state = risk_tracker.record_risk(exc.matched_phrase, exc.detail)
                print(f"⚠️ 读取文章触发官方风控：{note_url} -> {exc}")
                failed += 1
                if risk_state["stopped_due_to_risk"]:
                    break
            except Exception as exc:
                print(f"⚠️ 抓取文章失败：{note_url} -> {exc}")
                failed += 1

            if (
                attempted_note_reads > 0
                and attempted_note_reads % int(batch_read_cooldown_every) == 0
                and not risk_tracker.stopped_due_to_risk
            ):
                sleep_random_cooldown(
                    "正文抓取批次冷却",
                    batch_read_cooldown_min_seconds,
                    batch_read_cooldown_max_seconds,
                )

    aggregate_payload = {
        "run_id": run_id,
        "created_at": created_at,
        "keywords": [payload["keyword"] for payload in payloads],
        "top_n": default_top_n,
        "delay_seconds": default_delay_seconds,
        "counts": {
            "total_keywords": len(payloads),
            "attempted_urls": attempted_urls,
            "deduped_skipped": deduped_skipped,
            "note_id_skipped": note_id_skipped,
            "author_skipped": author_skipped,
            "captured": len(items),
            "failed": failed,
            "attempted_note_reads": attempted_note_reads,
        },
        **risk_tracker.snapshot(),
        "items": items,
    }

    write_json(json_path, aggregate_payload)
    write_csv(csv_path, items)
    write_xlsx(xlsx_path, items)
    save_dedupe_index(dedupe_path, dedupe_index)

    return {
        "run_id": run_id,
        "total_keywords": len(payloads),
        "attempted_urls": attempted_urls,
        "deduped_skipped": deduped_skipped,
        "note_id_skipped": note_id_skipped,
        "author_skipped": author_skipped,
        "captured": len(items),
        "failed": failed,
        "attempted_note_reads": attempted_note_reads,
        "json_path": str(json_path),
        "csv_path": str(csv_path),
        "xlsx_path": str(xlsx_path),
        "dedupe_path": str(dedupe_path),
        **risk_tracker.snapshot(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量抓取评论素材并导出 JSON/CSV/XLSX")
    parser.add_argument(
        "--input",
        help="JSON 输入文件路径；不传时从 stdin 读取",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="默认每个关键词抓取条数；单条记录可用 top_n 覆盖",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="默认搜索阶段固定等待秒数；单条记录可用 delay_seconds 覆盖",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="输出目录",
    )
    parser.add_argument(
        "--dedupe-path",
        default=DEFAULT_DEDUPE_PATH,
        help="note_id/作者 去重索引路径",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验输入和输出路径，不实际抓取",
    )
    parser.add_argument(
        "--risk-stop-after",
        type=int,
        default=3,
        help="连续命中官方风控多少次后停止整批任务",
    )
    parser.add_argument(
        "--note-read-cooldown-min-seconds",
        type=float,
        default=4.0,
        help="相邻正文读取之间的最小冷却秒数",
    )
    parser.add_argument(
        "--note-read-cooldown-max-seconds",
        type=float,
        default=7.0,
        help="相邻正文读取之间的最大冷却秒数",
    )
    parser.add_argument(
        "--batch-read-cooldown-every",
        type=int,
        default=3,
        help="每读取多少篇正文后触发一次批次冷却",
    )
    parser.add_argument(
        "--batch-read-cooldown-min-seconds",
        type=float,
        default=20.0,
        help="正文抓取批次冷却最小秒数",
    )
    parser.add_argument(
        "--batch-read-cooldown-max-seconds",
        type=float,
        default=35.0,
        help="正文抓取批次冷却最大秒数",
    )
    args = parser.parse_args()

    payload = load_json_payload(args.input)
    payloads = normalize_payloads(payload)
    default_top_n = int(args.top_n)
    default_delay_seconds = resolve_delay_seconds(args.delay_seconds)

    for payload_item in payloads:
        if payload_item["top_n"] is None:
            payload_item["top_n"] = default_top_n
        if payload_item["delay_seconds"] is None:
            payload_item["delay_seconds"] = default_delay_seconds

    summary = run_batch(
        payloads,
        output_dir=Path(args.output_dir),
        dedupe_path=Path(args.dedupe_path),
        default_top_n=default_top_n,
        default_delay_seconds=default_delay_seconds,
        risk_stop_after=args.risk_stop_after,
        note_read_cooldown_min_seconds=args.note_read_cooldown_min_seconds,
        note_read_cooldown_max_seconds=args.note_read_cooldown_max_seconds,
        batch_read_cooldown_every=args.batch_read_cooldown_every,
        batch_read_cooldown_min_seconds=args.batch_read_cooldown_min_seconds,
        batch_read_cooldown_max_seconds=args.batch_read_cooldown_max_seconds,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
