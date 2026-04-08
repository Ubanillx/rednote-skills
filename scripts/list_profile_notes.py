import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

from _bootstrap_env import ensure_local_venv

ensure_local_venv()

from action_delay import add_delay_argument, resolve_delay_seconds, wait_before_sensitive_action
from browser_profile import (
    close_profile_context,
    launch_profile_context,
    page_requires_login,
)


DEFAULT_MAX_SCROLL_ROUNDS = 80
DEFAULT_MAX_IDLE_SCROLL_ROUNDS = 4
PROFILE_SETTLE_TIMEOUT_MS = 6_000
PROFILE_NOTE_EMPTY_MARKERS = (
    "还没有笔记",
    "暂无笔记",
    "还没有发布笔记",
    "暂时没有笔记",
)
PROFILE_RISK_TEXT_MARKERS = (
    "安全限制",
    "请切换可靠网络环境后重试",
    "验证",
    "访问频次异常",
)


def _resolve_profile_url(
    profile_url: str | None = None,
    user_id: str | None = None,
) -> str:
    if isinstance(profile_url, str) and profile_url.strip():
        return profile_url.strip()
    if isinstance(user_id, str) and user_id.strip():
        return f"https://www.xiaohongshu.com/user/profile/{user_id.strip()}"
    raise ValueError("必须提供 --profile-url 或 --user-id 其中之一")


def _normalize_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    resolved = int(limit)
    if resolved <= 0:
        return None
    return min(resolved, 5000)


def _normalize_scroll_config(
    max_scroll_rounds: int | None,
    max_idle_scroll_rounds: int | None,
) -> tuple[int, int]:
    resolved_max_scroll_rounds = (
        DEFAULT_MAX_SCROLL_ROUNDS
        if max_scroll_rounds is None
        else int(max_scroll_rounds)
    )
    resolved_max_idle_scroll_rounds = (
        DEFAULT_MAX_IDLE_SCROLL_ROUNDS
        if max_idle_scroll_rounds is None
        else int(max_idle_scroll_rounds)
    )

    if resolved_max_scroll_rounds < 0:
        raise ValueError("max_scroll_rounds 不能小于 0")
    if resolved_max_idle_scroll_rounds <= 0:
        raise ValueError("max_idle_scroll_rounds 必须大于 0")
    if (
        resolved_max_scroll_rounds > 0
        and resolved_max_idle_scroll_rounds > resolved_max_scroll_rounds
    ):
        raise ValueError("max_idle_scroll_rounds 不能大于 max_scroll_rounds")

    return min(resolved_max_scroll_rounds, 300), min(resolved_max_idle_scroll_rounds, 20)


def _extract_note_cards_from_profile_dom(
    page,
    limit: int | None = None,
) -> dict[str, Any]:
    js_limit = 0 if limit is None else int(limit)
    script = """
        (limit) => {
            const hardLimit = Number(limit) > 0 ? Number(limit) : Number.MAX_SAFE_INTEGER;
            const normalize = (text) => (text || "").replace(/\\s+/g, " ").trim();
            const toAbs = (href) => {
                try {
                    return new URL(href, window.location.href).href;
                } catch (error) {
                    return "";
                }
            };
            const parseLink = (href) => {
                const abs = toAbs(href);
                if (!abs) {
                    return null;
                }
                let parsed;
                try {
                    parsed = new URL(abs);
                } catch (error) {
                    return null;
                }
                const match = parsed.pathname.match(
                    /\\/(?:explore|discovery\\/item|user\\/profile\\/[^/?#]+\\/)\\/?([0-9a-zA-Z]{24})/
                );
                if (!match) {
                    return null;
                }
                return {
                    id: match[1],
                    xsec_token: parsed.searchParams.get("xsec_token") || "",
                    xsec_source: parsed.searchParams.get("xsec_source") || "",
                    url: parsed.toString(),
                };
            };

            const selectorList = [
                "a[href*='/explore/']",
                "a[href*='/discovery/item/']",
                "a[href*='/user/profile/']",
            ];
            const links = Array.from(document.querySelectorAll(selectorList.join(",")));
            const noteMap = new Map();

            for (const link of links) {
                if (!(link instanceof HTMLAnchorElement)) {
                    continue;
                }
                const parsed = parseLink(link.getAttribute("href") || link.href || "");
                if (!parsed) {
                    continue;
                }

                const card = link.closest(
                    "[class*='note-item'], [class*='card'], [class*='cover'], li, article, section, div"
                ) || link;
                const titleNode = card.querySelector(
                    "[class*='title'], [class*='name'], h1, h2, h3, img[alt]"
                );
                const coverNode = card.querySelector("img");
                const title = normalize(
                    (titleNode && (titleNode.getAttribute("alt") || titleNode.textContent)) ||
                    link.getAttribute("title") ||
                    link.textContent
                );
                const cover = coverNode instanceof HTMLImageElement
                    ? (coverNode.currentSrc || coverNode.src || coverNode.getAttribute("src") || "")
                    : "";

                const existing = noteMap.get(parsed.id);
                if (!existing) {
                    noteMap.set(parsed.id, {
                        id: parsed.id,
                        xsec_token: parsed.xsec_token,
                        xsec_source: parsed.xsec_source,
                        note_url: parsed.url,
                        title,
                        cover,
                    });
                } else {
                    if (parsed.xsec_token && !existing.xsec_token) {
                        existing.xsec_token = parsed.xsec_token;
                        existing.xsec_source = parsed.xsec_source;
                        existing.note_url = parsed.url;
                    }
                    if (title && !existing.title) {
                        existing.title = title;
                    }
                    if (cover && !existing.cover) {
                        existing.cover = cover;
                    }
                }
            }

            const notes = Array.from(noteMap.values()).slice(0, hardLimit);

            return {
                ok: true,
                notes,
                count: notes.length,
                page_url: window.location.href,
                page_title: document.title || "",
            };
        }
    """
    result = page.evaluate(script, js_limit)
    if not isinstance(result, dict):
        return {"ok": False, "reason": "invalid_dom_payload", "notes": []}
    return result


def _note_ids_snapshot(extracted: dict[str, Any]) -> tuple[str, ...]:
    notes = extracted.get("notes", [])
    if not isinstance(notes, list):
        return ()
    snapshot = []
    for item in notes:
        if not isinstance(item, dict):
            continue
        note_id = str(item.get("id", "")).strip()
        if note_id:
            snapshot.append(note_id)
    return tuple(snapshot)


def _wait_for_profile_feed_settle(
    page,
    limit: int | None = None,
    timeout_ms: int = PROFILE_SETTLE_TIMEOUT_MS,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_ms / 1000
    last_snapshot: tuple[str, ...] | None = None
    stable_rounds = 0
    latest = _extract_note_cards_from_profile_dom(page, limit=limit)

    while time.monotonic() < deadline:
        page.wait_for_timeout(350)
        current = _extract_note_cards_from_profile_dom(page, limit=limit)
        snapshot = _note_ids_snapshot(current)
        if snapshot != last_snapshot:
            latest = current
            last_snapshot = snapshot
            stable_rounds = 0
            continue

        stable_rounds += 1
        if stable_rounds >= 3:
            break

    return latest


def _merge_note_batch(
    ordered_ids: list[str],
    note_index: dict[str, dict[str, Any]],
    notes: list[dict[str, Any]],
    limit: int | None = None,
) -> int:
    added = 0
    for raw_note in notes:
        if not isinstance(raw_note, dict):
            continue
        note_id = str(raw_note.get("id", "")).strip()
        if not note_id:
            continue

        note = {
            "id": note_id,
            "xsec_token": str(raw_note.get("xsec_token", "")).strip(),
            "xsec_source": str(raw_note.get("xsec_source", "")).strip(),
            "note_url": str(raw_note.get("note_url", "")).strip(),
            "title": str(raw_note.get("title", "")).strip(),
            "cover": str(raw_note.get("cover", "")).strip(),
        }

        existing = note_index.get(note_id)
        if existing is None:
            note_index[note_id] = note
            ordered_ids.append(note_id)
            added += 1
            if limit is not None and len(ordered_ids) >= limit:
                break
            continue

        for key, value in note.items():
            if value and not existing.get(key):
                existing[key] = value

        if note["xsec_token"] and not existing.get("xsec_token"):
            existing["xsec_token"] = note["xsec_token"]
            existing["xsec_source"] = note["xsec_source"]
            existing["note_url"] = note["note_url"]

    return added


def _profile_page_status(page) -> tuple[str | None, str | None]:
    try:
        body_text = page.locator("body").inner_text(timeout=2_000)
    except Exception:
        body_text = ""

    compact_text = " ".join(body_text.split())
    if not compact_text:
        return None, None

    for marker in PROFILE_RISK_TEXT_MARKERS:
        if marker in compact_text:
            return "risk_control", compact_text[:200]

    for marker in PROFILE_NOTE_EMPTY_MARKERS:
        if marker in compact_text:
            return "empty_profile", marker

    if "用户不存在" in compact_text or "该用户不存在" in compact_text:
        return "profile_not_found", compact_text[:200]

    return None, None


def _scroll_profile_page(page, scroll_round: int) -> None:
    distance = random.randint(900, 1600)
    print(f"📄 主页下滑第 {scroll_round} 轮，滚动距离约 {distance}px")

    page.evaluate(
        """
        (distance) => {
            const targets = [];
            const seen = new Set();

            const addTarget = (node) => {
                if (!node || seen.has(node)) {
                    return;
                }
                seen.add(node);
                targets.push(node);
            };

            addTarget(document.scrollingElement || document.documentElement || document.body);

            const anchors = Array.from(
                document.querySelectorAll("a[href*='/explore/'], a[href*='/discovery/item/']")
            );

            for (const anchor of anchors.slice(-6)) {
                let node = anchor.parentElement;
                while (node) {
                    const style = getComputedStyle(node);
                    const isScrollable =
                        node.clientHeight > 0 &&
                        (
                            node.scrollHeight > node.clientHeight + 20 ||
                            style.overflowY === "auto" ||
                            style.overflowY === "scroll"
                        );
                    if (isScrollable) {
                        addTarget(node);
                    }
                    if (node === document.body || node === document.documentElement) {
                        break;
                    }
                    node = node.parentElement;
                }
            }

            for (const target of targets) {
                try {
                    target.scrollTop = Math.min(
                        target.scrollHeight,
                        (target.scrollTop || 0) + distance
                    );
                } catch (error) {
                    // Ignore individual target failures.
                }
            }

            window.scrollBy(0, distance);
        }
        """,
        distance,
    )
    page.mouse.wheel(0, distance)
    page.wait_for_timeout(random.randint(600, 1_100))


def list_profile_notes(
    profile_url: str | None = None,
    user_id: str | None = None,
    *,
    limit: int | None = None,
    max_scroll_rounds: int | None = None,
    max_idle_scroll_rounds: int | None = None,
    delay_seconds: float = 0.0,
) -> dict[str, Any]:
    resolved_limit = _normalize_limit(limit)
    resolved_max_scroll_rounds, resolved_max_idle_scroll_rounds = _normalize_scroll_config(
        max_scroll_rounds,
        max_idle_scroll_rounds,
    )
    target_url = _resolve_profile_url(profile_url=profile_url, user_id=user_id)

    driver, browser, context, page, settings, chrome_process = launch_profile_context(
        headless=False,
        startup_url=None,
    )
    try:
        print(f"🌐 导航到用户主页: {target_url}")
        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2_000)

        if page_requires_login(page):
            return {
                "ok": False,
                "reason": "not_logged_in",
                "message": (
                    f'当前 Chrome {settings["profile_directory"]} 未登录小红书，请先运行 '
                    "python3 scripts/manual_login.py"
                ),
                "profile_url": target_url,
                "notes": [],
                "count": 0,
                "limit": resolved_limit,
            }

        wait_before_sensitive_action(
            page,
            "开始浏览主页笔记",
            delay_seconds,
            do_scroll=True,
            do_blank_click=True,
        )

        ordered_ids: list[str] = []
        note_index: dict[str, dict[str, Any]] = {}
        last_page_url = target_url
        last_page_title = ""
        idle_rounds = 0

        for scroll_round in range(resolved_max_scroll_rounds + 1):
            extracted = _wait_for_profile_feed_settle(page, limit=resolved_limit)
            notes = extracted.get("notes", []) if isinstance(extracted, dict) else []
            if isinstance(extracted, dict) and extracted.get("page_url"):
                last_page_url = str(extracted["page_url"])
            if isinstance(extracted, dict) and extracted.get("page_title"):
                last_page_title = str(extracted["page_title"])

            added = 0
            if isinstance(notes, list):
                added = _merge_note_batch(
                    ordered_ids,
                    note_index,
                    notes,
                    limit=resolved_limit,
                )

            print(
                f"🧾 第 {scroll_round + 1} 轮提取 {len(notes) if isinstance(notes, list) else 0} 条，"
                f"新增 {added} 条，累计 {len(ordered_ids)} 条"
            )

            if resolved_limit is not None and len(ordered_ids) >= resolved_limit:
                print(f"✅ 已达到目标数量 {resolved_limit}，停止继续滚动")
                break

            if scroll_round >= resolved_max_scroll_rounds:
                break

            if added == 0:
                idle_rounds += 1
                print(f"⚪️ 连续无新增轮次: {idle_rounds}/{resolved_max_idle_scroll_rounds}")
            else:
                idle_rounds = 0

            if idle_rounds >= resolved_max_idle_scroll_rounds:
                print("⚠️ 连续多轮没有新增笔记，提前结束抓取")
                break

            _scroll_profile_page(page, scroll_round + 1)

        notes = [note_index[note_id] for note_id in ordered_ids]
        status_reason, status_detail = _profile_page_status(page)
        ok = status_reason not in {"risk_control", "profile_not_found"}

        result = {
            "ok": ok,
            "reason": status_reason,
            "message": status_detail,
            "profile_url": last_page_url,
            "requested_profile_url": target_url,
            "page_title": last_page_title,
            "count": len(notes),
            "limit": resolved_limit,
            "max_scroll_rounds": resolved_max_scroll_rounds,
            "max_idle_scroll_rounds": resolved_max_idle_scroll_rounds,
            "notes": notes[:resolved_limit] if resolved_limit is not None else notes,
        }
        return result
    finally:
        close_profile_context(
            driver,
            browser,
            page=page,
            settings=settings,
            chrome_process=chrome_process,
        )


def _write_output(result: dict[str, Any], output_path: str | None) -> dict[str, Any]:
    if not output_path:
        return result

    output_file = Path(output_path).expanduser().resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result = dict(result)
    result["output_path"] = str(output_file)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抓取小红书用户主页的笔记列表")
    parser.add_argument("--profile-url", help="小红书用户主页 URL")
    parser.add_argument("--user-id", help="小红书用户 ID，可自动拼主页链接")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多返回多少条笔记；默认 0 表示尽量抓全",
    )
    parser.add_argument(
        "--max-scroll-rounds",
        type=int,
        default=DEFAULT_MAX_SCROLL_ROUNDS,
        help=f"最多滚动轮数；默认 {DEFAULT_MAX_SCROLL_ROUNDS}",
    )
    parser.add_argument(
        "--max-idle-scroll-rounds",
        type=int,
        default=DEFAULT_MAX_IDLE_SCROLL_ROUNDS,
        help=f"连续无新增时提前结束阈值；默认 {DEFAULT_MAX_IDLE_SCROLL_ROUNDS}",
    )
    parser.add_argument(
        "--output",
        help="可选输出文件路径；若传入则把 JSON 结果写到该文件",
    )
    add_delay_argument(parser)
    args = parser.parse_args()
    if not args.profile_url and not args.user_id:
        parser.error("必须提供 --profile-url 或 --user-id 其中之一")

    delay_seconds = resolve_delay_seconds(args.delay_seconds)
    result = list_profile_notes(
        profile_url=args.profile_url,
        user_id=args.user_id,
        limit=args.limit,
        max_scroll_rounds=args.max_scroll_rounds,
        max_idle_scroll_rounds=args.max_idle_scroll_rounds,
        delay_seconds=delay_seconds,
    )
    result = _write_output(result, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
