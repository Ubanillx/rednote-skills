import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from _bootstrap_env import ensure_local_venv

ensure_local_venv()

from comment_note import comment_note, resolve_auto_like_probability
from action_delay import resolve_delay_seconds


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
        raise ValueError("批量评论输入不能为空")

    return json.loads(raw_text)


def normalize_payloads(payload: object) -> list[dict]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            items = payload["items"]
        elif all(isinstance(key, str) and isinstance(value, str) for key, value in payload.items()):
            items = [
                {"note_url": note_url, "comment_text": comment_text}
                for note_url, comment_text in payload.items()
            ]
        else:
            raise ValueError(
                "JSON 对象必须是 {'items': [...]}，或 {'note_url': 'comment_text'} 这种映射"
            )
    else:
        raise ValueError("批量评论输入必须是 JSON 数组或 JSON 对象")

    normalized = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 条记录不是 JSON 对象")

        note_url = str(item.get("note_url", "")).strip()
        comment_text = str(item.get("comment_text", "")).strip()
        if not note_url:
            raise ValueError(f"第 {index} 条记录缺少 note_url")
        if not comment_text:
            raise ValueError(f"第 {index} 条记录缺少 comment_text")

        normalized.append(
            {
                "index": index,
                "note_url": note_url,
                "comment_text": comment_text,
                "delay_seconds": item.get("delay_seconds"),
                "like_probability": item.get("like_probability"),
                "meta": item.get("meta"),
            }
        )

    return normalized


def run_batch(
    payloads: list[dict],
    *,
    log_path: Path,
    dry_run: bool = False,
) -> dict:
    summary = {
        "total": len(payloads),
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
        "dry_run": dry_run,
        "log_path": str(log_path),
    }

    for payload in payloads:
        started_at = datetime.now().isoformat(timespec="seconds")
        summary["attempted"] += 1

        delay_seconds = resolve_delay_seconds(payload.get("delay_seconds"))
        like_probability = resolve_auto_like_probability(payload.get("like_probability"))
        note_url = payload["note_url"]
        comment_text = payload["comment_text"]

        try:
            if dry_run:
                result = "DRY_RUN"
                ok = True
            else:
                result = comment_note(
                    note_url,
                    comment_text,
                    delay_seconds,
                    like_probability,
                )
                ok = result.startswith("💬 评论已发布")

            append_jsonl(
                log_path,
                {
                    "time": started_at,
                    "index": payload["index"],
                    "note_url": note_url,
                    "comment_text": comment_text,
                    "delay_seconds": delay_seconds,
                    "like_probability": like_probability,
                    "status": "success" if ok else "error",
                    "result": result,
                    "meta": payload.get("meta"),
                },
            )

            if ok:
                summary["succeeded"] += 1
            else:
                summary["failed"] += 1
        except Exception as exc:
            summary["failed"] += 1
            append_jsonl(
                log_path,
                {
                    "time": started_at,
                    "index": payload["index"],
                    "note_url": note_url,
                    "comment_text": comment_text,
                    "delay_seconds": delay_seconds,
                    "like_probability": like_probability,
                    "status": "error",
                    "error": str(exc),
                    "meta": payload.get("meta"),
                },
            )

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量执行小红书评论任务")
    parser.add_argument(
        "--input",
        help="JSON 输入文件路径；不传时从 stdin 读取",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=5.0,
        help="默认固定等待秒数；单条记录可用 delay_seconds 覆盖",
    )
    parser.add_argument(
        "--like-probability",
        type=float,
        default=None,
        help="默认评论前自动点赞概率；单条记录可用 like_probability 覆盖",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验输入和记录日志，不实际发送评论",
    )
    parser.add_argument(
        "--log-path",
        default="logs/rednote/batch_context_comments.jsonl",
        help="JSONL 日志输出路径",
    )
    args = parser.parse_args()

    payload = load_json_payload(args.input)
    payloads = normalize_payloads(payload)
    default_delay_seconds = resolve_delay_seconds(args.delay_seconds)
    default_like_probability = resolve_auto_like_probability(args.like_probability)

    for payload_item in payloads:
        if payload_item["delay_seconds"] is None:
            payload_item["delay_seconds"] = default_delay_seconds
        if payload_item["like_probability"] is None:
            payload_item["like_probability"] = default_like_probability

    summary = run_batch(
        payloads,
        log_path=Path(args.log_path),
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
