import json
import random
import re

from action_delay import click_random_blank_position
from official_risk_guard import raise_if_official_risk

WHITESPACE_RE = re.compile(r"\s+")
COMMENT_REGION_SELECTORS = [
    ".comments-wrap",
    ".comment-wrapper",
]

SHORT_READ_RANDOM_DELAY_MIN_MS = 180
SHORT_READ_RANDOM_DELAY_MAX_MS = 650
SHORT_READ_SCROLL_DISTANCE_MIN = 80
SHORT_READ_SCROLL_DISTANCE_MAX = 260
SHORT_READ_FIXED_DELAY_CAP_SECONDS = 0.8


def clean_text(value):
    if not value:
        return ""
    value = WHITESPACE_RE.sub(" ", str(value)).strip()
    return value


def extract_note_data(page):
    note_data = page.evaluate(
        """
        () => {
            const extractFromState = (state) => {
                const noteDetailMap = state?.note?.noteDetailMap;
                if (!noteDetailMap) return null;

                let map = noteDetailMap;
                if (noteDetailMap.value !== undefined) {
                    map = noteDetailMap.value;
                } else if (noteDetailMap._value !== undefined) {
                    map = noteDetailMap._value;
                }
                if (!map) return null;

                const firstKey = Object.keys(map)[0];
                const note = map[firstKey]?.note;
                return note ? JSON.stringify(note) : null;
            };

            const runtimeStateResult = extractFromState(window.__INITIAL_STATE__);
            if (runtimeStateResult) return runtimeStateResult;

            const script = Array.from(document.scripts).find((item) =>
                (item.textContent || "").includes("window.__INITIAL_STATE__=")
            );
            if (!script) return null;

            const text = script.textContent || "";
            const marker = "window.__INITIAL_STATE__=";
            const start = text.indexOf(marker);
            if (start === -1) return null;

            const after = text.slice(start + marker.length);
            const endMarker = "window.__serverRendered";
            const end = after.indexOf(endMarker);
            const expression = (
                end === -1 ? after : after.slice(0, end)
            ).trim().replace(/;\\s*$/, "");
            if (!expression) return null;

            try {
                const parsedState = Function(
                    '"use strict"; return (' + expression + ');'
                )();
                return extractFromState(parsedState);
            } catch (error) {
                return null;
            }
        }
        """
    )
    if not note_data:
        raise RuntimeError("未能在页面中提取到笔记数据")
    return json.loads(note_data)


def _scroll_to_comment_region(page):
    selector = page.evaluate(
        """selectors => {
            for (const selector of selectors) {
                const target = document.querySelector(selector);
                if (target) {
                    target.scrollIntoView({ block: 'center', behavior: 'auto' });
                    return selector;
                }
            }
            return null;
        }""",
        COMMENT_REGION_SELECTORS,
    )
    return selector


def humanize_note_page_before_extract(page, action_name: str, delay_seconds: float = 0.0):
    raise_if_official_risk(page, context=f"{action_name}前页面检查")
    clipped_delay_seconds = max(0.0, min(float(delay_seconds or 0.0), SHORT_READ_FIXED_DELAY_CAP_SECONDS))
    if clipped_delay_seconds > 0:
        print(f"⏳ {action_name} 前轻量固定等待 {clipped_delay_seconds:.2f} 秒")
        page.wait_for_timeout(int(clipped_delay_seconds * 1000))

    warmup_delay_ms = random.randint(
        SHORT_READ_RANDOM_DELAY_MIN_MS,
        SHORT_READ_RANDOM_DELAY_MAX_MS,
    )
    print(f"👀 {action_name} 前轻量停留 {warmup_delay_ms}ms")
    page.wait_for_timeout(warmup_delay_ms)

    scroll_count = random.randint(1, 2)
    print(f"🌀 {action_name} 前轻量滑动 {scroll_count} 次")
    for _ in range(scroll_count):
        distance = random.randint(
            SHORT_READ_SCROLL_DISTANCE_MIN,
            SHORT_READ_SCROLL_DISTANCE_MAX,
        )
        direction = random.choice((-1, 1))
        page.mouse.wheel(0, direction * distance)
        page.wait_for_timeout(random.randint(120, 260))

    click_random_blank_position(page, action_name)

    if random.random() < 0.7:
        selector = _scroll_to_comment_region(page)
        if selector:
            print(f"🗨️ {action_name} 前扫一眼评论区：{selector}")
            page.wait_for_timeout(random.randint(220, 520))
            page.mouse.wheel(0, -random.randint(120, 260))
            page.wait_for_timeout(random.randint(120, 260))

    raise_if_official_risk(page, context=f"{action_name}后页面检查")


def summarize_note_for_comment(note_data):
    title = clean_text(note_data.get("title", ""))
    desc = clean_text(note_data.get("desc", ""))
    tags = [
        clean_text(tag.get("name", ""))
        for tag in note_data.get("tagList", [])
        if clean_text(tag.get("name", ""))
    ]
    nickname = clean_text(note_data.get("user", {}).get("nickname", ""))
    return {
        "title": title,
        "desc": desc,
        "tags": tags,
        "nickname": nickname,
    }


def note_brief_for_print(note_data):
    summary = summarize_note_for_comment(note_data)
    tag_text = " ".join(f"#{tag}" for tag in summary["tags"][:5]) or "无"
    return (
        f'标题：{summary["title"] or "无标题"}\n'
        f'作者：{summary["nickname"] or "未知作者"}\n'
        f'标签：{tag_text}\n'
        f'正文摘要：{truncate_text(summary["desc"], 120) or "无正文"}'
    )


def truncate_text(text, limit):
    text = clean_text(text)
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip("，。；,; ") + "…"
