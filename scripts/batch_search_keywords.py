import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from _bootstrap_env import ensure_local_venv

ensure_local_venv()

from action_delay import resolve_delay_seconds, sleep_random_cooldown
from official_risk_guard import OfficialRiskDetectedError, RiskStopTracker
from search_note_by_key_word import _normalize_filter_option, search


ROOT_DEFAULT_FIELDS = (
    "top_n",
    "start_index",
    "end_index",
    "max_scroll_rounds",
    "max_idle_scroll_rounds",
    "delay_seconds",
    "filter",
    "meta",
)


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_json_payload(input_path: str | None) -> object:
    if input_path:
        raw_text = Path(input_path).read_text(encoding="utf-8")
    else:
        raw_text = sys.stdin.read()

    raw_text = raw_text.strip()
    if not raw_text:
        raise ValueError("批量关键词搜索输入不能为空")

    return json.loads(raw_text)


def merge_filter_options(*filter_options: object) -> dict[str, str] | None:
    merged: dict[str, str] = {}
    for filter_option in filter_options:
        normalized = _normalize_filter_option(filter_option)
        merged.update(normalized)
    return merged or None


def extract_root_defaults(payload: object) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return {}

    defaults = {}
    for field_name in ROOT_DEFAULT_FIELDS:
        if field_name in payload:
            defaults[field_name] = payload[field_name]

    return defaults


def normalize_payloads(payload: object) -> list[dict]:
    root_defaults = extract_root_defaults(payload)

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
        raise ValueError("批量关键词搜索输入必须是 JSON 数组或 JSON 对象")

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
                "top_n": item.get("top_n", root_defaults.get("top_n")),
                "start_index": item.get("start_index", root_defaults.get("start_index")),
                "end_index": item.get("end_index", root_defaults.get("end_index")),
                "max_scroll_rounds": item.get(
                    "max_scroll_rounds",
                    root_defaults.get("max_scroll_rounds"),
                ),
                "max_idle_scroll_rounds": item.get(
                    "max_idle_scroll_rounds",
                    root_defaults.get("max_idle_scroll_rounds"),
                ),
                "delay_seconds": item.get(
                    "delay_seconds",
                    root_defaults.get("delay_seconds"),
                ),
                "filter": merge_filter_options(
                    root_defaults.get("filter"),
                    item.get("filter"),
                ),
                "meta": item.get("meta", root_defaults.get("meta")),
            }
        )

    return normalized


def run_batch(
    payloads: list[dict],
    *,
    log_path: Path,
    risk_stop_after: int = 3,
    keyword_cooldown_min_seconds: float = 8.0,
    keyword_cooldown_max_seconds: float = 15.0,
    dry_run: bool = False,
) -> dict:
    results = []
    risk_tracker = RiskStopTracker(stop_after=risk_stop_after)
    summary = {
        "total": len(payloads),
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
        "dry_run": dry_run,
        "log_path": str(log_path),
        "risk_stop_after": int(risk_stop_after),
        "keyword_cooldown_min_seconds": float(keyword_cooldown_min_seconds),
        "keyword_cooldown_max_seconds": float(keyword_cooldown_max_seconds),
        **risk_tracker.snapshot(),
        "results": results,
    }

    for payload_index, payload in enumerate(payloads):
        if risk_tracker.stopped_due_to_risk:
            break

        started_at = datetime.now().isoformat(timespec="seconds")
        summary["attempted"] += 1

        keyword = payload["keyword"]
        top_n = int(payload["top_n"])
        delay_seconds = resolve_delay_seconds(payload["delay_seconds"])
        base_row = {
            "keyword": keyword,
            "top_n": top_n,
            "start_index": payload.get("start_index"),
            "end_index": payload.get("end_index"),
            "max_scroll_rounds": payload.get("max_scroll_rounds"),
            "max_idle_scroll_rounds": payload.get("max_idle_scroll_rounds"),
            "delay_seconds": delay_seconds,
            "filter": payload.get("filter"),
            "meta": payload.get("meta"),
        }

        try:
            if dry_run:
                urls = []
                status = "success"
                result_row = {
                    **base_row,
                    "urls": urls,
                    "status": status,
                    "result": "DRY_RUN",
                    "risk_signal": False,
                    "risk_phrase": "",
                    "stopped_due_to_risk": False,
                    "consecutive_risk_hits": risk_tracker.consecutive_risk_hits,
                }
            else:
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
                has_error = any(
                    isinstance(item, str) and item.startswith("❌")
                    for item in urls
                )
                status = "error" if has_error else "success"
                if status == "success":
                    risk_tracker.record_success()
                result_row = {
                    **base_row,
                    "urls": urls,
                    "status": status,
                    "risk_signal": False,
                    "risk_phrase": "",
                    "stopped_due_to_risk": risk_tracker.stopped_due_to_risk,
                    "consecutive_risk_hits": risk_tracker.consecutive_risk_hits,
                }

            results.append(result_row)
            append_jsonl(
                log_path,
                {
                    "time": started_at,
                    "index": payload["index"],
                    **result_row,
                },
            )

            if result_row["status"] == "success":
                summary["succeeded"] += 1
            else:
                summary["failed"] += 1
        except OfficialRiskDetectedError as exc:
            summary["failed"] += 1
            risk_state = risk_tracker.record_risk(exc.matched_phrase, exc.detail)
            error_row = {
                **base_row,
                "urls": [],
                "status": "error",
                "error": str(exc),
                "risk_signal": True,
                "risk_phrase": exc.matched_phrase,
                "risk_detail": exc.detail,
                "stopped_due_to_risk": risk_state["stopped_due_to_risk"],
                "consecutive_risk_hits": risk_state["consecutive_risk_hits"],
            }
            results.append(error_row)
            append_jsonl(
                log_path,
                {
                    "time": started_at,
                    "index": payload["index"],
                    **error_row,
                },
            )
        except Exception as exc:
            summary["failed"] += 1
            error_row = {
                **base_row,
                "urls": [],
                "status": "error",
                "error": str(exc),
                "risk_signal": False,
                "risk_phrase": "",
                "stopped_due_to_risk": risk_tracker.stopped_due_to_risk,
                "consecutive_risk_hits": risk_tracker.consecutive_risk_hits,
            }
            results.append(error_row)
            append_jsonl(
                log_path,
                {
                    "time": started_at,
                    "index": payload["index"],
                    **error_row,
                },
            )

        summary.update(risk_tracker.snapshot())

        if (
            not dry_run
            and not risk_tracker.stopped_due_to_risk
            and payload_index < len(payloads) - 1
        ):
            sleep_random_cooldown(
                "关键词批次间冷却",
                keyword_cooldown_min_seconds,
                keyword_cooldown_max_seconds,
            )

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量执行关键词搜索")
    parser.add_argument(
        "--input",
        help="JSON 输入文件路径；不传时从 stdin 读取",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="默认返回条数；单条记录可用 top_n 覆盖",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="默认固定等待秒数；单条记录可用 delay_seconds 覆盖",
    )
    parser.add_argument(
        "--filter",
        help=(
            "默认筛选 JSON，应用到所有关键词；单条记录的 filter 会覆盖同名字段，例如: "
            '\'{"sort_by":"最新","note_type":"图文","publish_time":"一周内"}\''
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验输入和记录日志，不实际执行搜索",
    )
    parser.add_argument(
        "--risk-stop-after",
        type=int,
        default=3,
        help="连续命中官方风控多少次后停止整批任务",
    )
    parser.add_argument(
        "--keyword-cooldown-min-seconds",
        type=float,
        default=8.0,
        help="真实关键词批次间冷却最小秒数",
    )
    parser.add_argument(
        "--keyword-cooldown-max-seconds",
        type=float,
        default=15.0,
        help="真实关键词批次间冷却最大秒数",
    )
    parser.add_argument(
        "--log-path",
        default="logs/rednote/batch_search_keywords.jsonl",
        help="JSONL 日志输出路径",
    )
    args = parser.parse_args()

    payload = load_json_payload(args.input)
    payloads = normalize_payloads(payload)
    default_top_n = int(args.top_n)
    default_delay_seconds = resolve_delay_seconds(args.delay_seconds)
    default_filter = merge_filter_options(args.filter)

    for payload_item in payloads:
        if payload_item["top_n"] is None:
            payload_item["top_n"] = default_top_n
        if payload_item["delay_seconds"] is None:
            payload_item["delay_seconds"] = default_delay_seconds
        payload_item["filter"] = merge_filter_options(
            default_filter,
            payload_item.get("filter"),
        )

    summary = run_batch(
        payloads,
        log_path=Path(args.log_path),
        risk_stop_after=args.risk_stop_after,
        keyword_cooldown_min_seconds=args.keyword_cooldown_min_seconds,
        keyword_cooldown_max_seconds=args.keyword_cooldown_max_seconds,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
