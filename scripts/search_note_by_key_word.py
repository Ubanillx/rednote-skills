import argparse
import json
import random
import time
from urllib.parse import quote

from _bootstrap_env import ensure_local_venv

ensure_local_venv()

from action_delay import add_delay_argument, resolve_delay_seconds, wait_before_sensitive_action
from browser_profile import (
    close_profile_context,
    launch_profile_context,
    page_requires_login,
)
from official_risk_guard import OfficialRiskDetectedError, raise_if_official_risk


SEARCH_RESULT_SELECTOR = "a.cover.mask.ld"
SEARCH_RESULT_LIMIT_FOR_RANDOM_CLICK = 5
SEARCH_NOTES_API_PATH = "/api/sns/web/v1/search/notes"
FILTER_TRIGGER_SELECTOR = "div.filter"
FILTER_PANEL_SELECTOR = ".filter-panel"
MAX_SCROLL_ROUNDS = 60
MAX_IDLE_SCROLL_ROUNDS = 4
SCROLL_SETTLE_TIMEOUT_MS = 6_000

FILTER_KEY_ALIASES = {
    "sort_by": "sort_by",
    "sort": "sort_by",
    "排序方式": "sort_by",
    "note_type": "note_type",
    "笔记类型": "note_type",
    "publish_time": "publish_time",
    "发布时间": "publish_time",
    "search_scope": "search_scope",
    "搜索范围": "search_scope",
    "position_distance": "position_distance",
    "location_distance": "position_distance",
    "location": "position_distance",
    "位置距离": "position_distance",
}

FILTER_GROUPS = {
    "sort_by": {
        "title": "排序依据",
        "default": "综合",
        "choices": {
            "综合": "general",
            "最新": "time_descending",
            "最多点赞": "popularity_descending",
            "最多评论": "comment_descending",
            "最多收藏": "collect_descending",
        },
    },
    "note_type": {
        "title": "笔记类型",
        "default": "不限",
        "choices": {
            "不限": "不限",
            "视频": "视频笔记",
            "图文": "普通笔记",
        },
    },
    "publish_time": {
        "title": "发布时间",
        "default": "不限",
        "choices": {
            "不限": "不限",
            "一天内": "一天内",
            "一周内": "一周内",
            "半年内": "半年内",
        },
    },
    "search_scope": {
        "title": "搜索范围",
        "default": "不限",
        "choices": {
            "不限": "不限",
            "已看过": "已看过",
            "未看过": "未看过",
            "已关注": "已关注",
        },
    },
    "position_distance": {
        "title": "位置距离",
        "default": "不限",
        "choices": {
            "不限": "不限",
            "同城": "同城",
            "附近": "附近",
        },
        "requires_geo_choices": {"同城", "附近"},
    },
}

FILTER_GROUP_INDEXES = {
    "sort_by": 1,
    "note_type": 2,
    "publish_time": 3,
    "search_scope": 4,
    "position_distance": 5,
}


def _raise_if_search_risk(page, context: str) -> None:
    raise_if_official_risk(page, context=context)


def _wait_for_search_results(page, timeout_ms: int = 10_000) -> bool:
    try:
        page.locator(SEARCH_RESULT_SELECTOR).first.wait_for(
            state="attached",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


def _collect_note_links(page, limit: int | None = None) -> list[str]:
    prefix = "https://www.xiaohongshu.com"
    links = page.locator(SEARCH_RESULT_SELECTOR)
    hrefs = []
    seen = set()

    for idx in range(links.count()):
        href = links.nth(idx).get_attribute("href")
        if not href:
            continue

        full_href = href if href.startswith("http") else prefix + href
        if full_href in seen:
            continue

        seen.add(full_href)
        hrefs.append(full_href)
        if limit is not None and len(hrefs) >= limit:
            break

    return hrefs


def _extend_seen_links(seen_hrefs: list[str], current_hrefs: list[str]) -> int:
    seen_set = set(seen_hrefs)
    added = 0

    for href in current_hrefs:
        if href in seen_set:
            continue
        seen_set.add(href)
        seen_hrefs.append(href)
        added += 1

    return added


def _browse_random_note_from_search(page, delay_seconds: float) -> None:
    cards = page.locator(SEARCH_RESULT_SELECTOR)
    card_count = cards.count()
    if card_count == 0:
        print("⚪️ 当前搜索页没有可点击的笔记，跳过随机浏览")
        return

    candidate_count = min(card_count, SEARCH_RESULT_LIMIT_FOR_RANDOM_CLICK)
    random_index = random.randrange(candidate_count)
    random_card = cards.nth(random_index)
    note_href = random_card.get_attribute("href") or ""
    print(f"🎲 随机浏览第 {random_index + 1} 条搜索结果: {note_href}")

    wait_before_sensitive_action(page, "随机点击搜索结果", delay_seconds)
    random_card.click(timeout=10_000)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(random.randint(2_500, 4_200))

    dwell_scroll_count = random.randint(1, 2)
    print(f"👀 在随机笔记页停留并滑动 {dwell_scroll_count} 次")
    for _ in range(dwell_scroll_count):
        page.mouse.wheel(0, random.randint(180, 520))
        page.wait_for_timeout(random.randint(400, 900))

    page.wait_for_timeout(random.randint(1_200, 2_400))
    page.go_back(wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_timeout(random.randint(2_000, 3_200))
    _wait_for_search_results(page)


def _resolve_search_window(
    top_n: int,
    start_index: int = 1,
    end_index: int | None = None,
) -> tuple[int, int]:
    if top_n <= 0:
        raise ValueError("top_n 必须大于 0")
    if start_index <= 0:
        raise ValueError("start_index 必须大于 0")

    resolved_end_index = (
        end_index if end_index is not None else start_index + top_n - 1
    )
    if resolved_end_index < start_index:
        raise ValueError("end_index 不能小于 start_index")

    return start_index, resolved_end_index


def _resolve_scroll_config(
    max_scroll_rounds: int | None = None,
    max_idle_scroll_rounds: int | None = None,
) -> tuple[int, int]:
    resolved_max_scroll_rounds = (
        MAX_SCROLL_ROUNDS if max_scroll_rounds is None else int(max_scroll_rounds)
    )
    resolved_max_idle_scroll_rounds = (
        MAX_IDLE_SCROLL_ROUNDS
        if max_idle_scroll_rounds is None
        else int(max_idle_scroll_rounds)
    )

    if resolved_max_scroll_rounds <= 0:
        raise ValueError("max_scroll_rounds 必须大于 0")
    if resolved_max_idle_scroll_rounds <= 0:
        raise ValueError("max_idle_scroll_rounds 必须大于 0")
    if resolved_max_idle_scroll_rounds > resolved_max_scroll_rounds:
        raise ValueError("max_idle_scroll_rounds 不能大于 max_scroll_rounds")

    return resolved_max_scroll_rounds, resolved_max_idle_scroll_rounds


def _scroll_current_search_view(page, distance: int) -> None:
    page.evaluate(
        """
        ([selector, distance]) => {
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

          const anchors = Array.from(document.querySelectorAll(selector));
          for (const anchor of anchors.slice(-3)) {
            let node = anchor.parentElement;
            while (node) {
              const style = getComputedStyle(node);
              const isScrollable =
                node.clientHeight > 0 &&
                (
                  node.scrollHeight > node.clientHeight + 20 ||
                  style.overflowY === 'auto' ||
                  style.overflowY === 'scroll'
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

          if (anchors.length > 0) {
            anchors.at(-1)?.scrollIntoView({
              block: 'end',
              inline: 'nearest',
              behavior: 'instant',
            });
          }

          for (const target of targets) {
            try {
              target.scrollTop = Math.min(
                target.scrollHeight,
                (target.scrollTop || 0) + distance
              );
            } catch (error) {
              // Ignore individual target scroll failures; we try multiple candidates.
            }
          }
        }
        """,
        [SEARCH_RESULT_SELECTOR, distance],
    )


def _scroll_search_results(page, scroll_round: int) -> None:
    cards = page.locator(SEARCH_RESULT_SELECTOR)
    card_count = cards.count()
    if card_count == 0:
        print("⚪️ 当前没有可见笔记卡片，跳过本轮滚动")
        return

    wheel_times = random.randint(2, 4)
    print(f"📄 模拟分页下滑第 {scroll_round} 轮，连续滚动 {wheel_times} 次")

    try:
        cards.nth(card_count - 1).scroll_into_view_if_needed(timeout=5_000)
        page.wait_for_timeout(random.randint(250, 500))
    except Exception:
        pass

    for _ in range(wheel_times):
        distance = random.randint(900, 1600)
        _scroll_current_search_view(page, distance)

        try:
            last_card = cards.nth(cards.count() - 1)
            box = last_card.bounding_box()
            if box:
                x = box["x"] + min(box["width"] / 2, 320)
                y = box["y"] + min(box["height"] / 2, 240)
                page.mouse.move(x, y)
        except Exception:
            pass

        page.mouse.wheel(0, distance)
        page.wait_for_timeout(random.randint(260, 620))


def _wait_for_search_feed_settle(page) -> list[str]:
    deadline = time.monotonic() + SCROLL_SETTLE_TIMEOUT_MS / 1000
    last_snapshot: tuple[str, ...] | None = None
    stable_rounds = 0
    _raise_if_search_risk(page, "搜索结果页初始检查")
    latest_hrefs = _collect_note_links(page)

    while time.monotonic() < deadline:
        page.wait_for_timeout(350)
        _raise_if_search_risk(page, "搜索结果页滚动后检查")
        latest_hrefs = _collect_note_links(page)
        snapshot = tuple(latest_hrefs)
        if snapshot != last_snapshot:
            last_snapshot = snapshot
            stable_rounds = 0
            continue

        stable_rounds += 1
        if stable_rounds >= 3:
            break

    return latest_hrefs


def _load_search_window(
    page,
    *,
    target_end_index: int,
    max_scroll_rounds: int,
    max_idle_scroll_rounds: int,
) -> list[str]:
    current_hrefs = _wait_for_search_feed_settle(page)
    seen_hrefs: list[str] = []
    _extend_seen_links(seen_hrefs, current_hrefs)
    if len(seen_hrefs) >= target_end_index:
        print(f"📚 首屏已覆盖目标范围，当前累计 {len(seen_hrefs)} 条")
        return seen_hrefs

    idle_rounds = 0
    for scroll_round in range(1, max_scroll_rounds + 1):
        before_count = len(seen_hrefs)
        _scroll_search_results(page, scroll_round)
        current_hrefs = _wait_for_search_feed_settle(page)
        added_count = _extend_seen_links(seen_hrefs, current_hrefs)

        if added_count > 0:
            idle_rounds = 0
            print(
                f"🆕 第 {scroll_round} 轮新增 {added_count} 条，累计 {len(seen_hrefs)} 条"
            )
        else:
            idle_rounds += 1
            print(
                f"⚪️ 第 {scroll_round} 轮未发现新增笔记，连续无增长 {idle_rounds} 次"
            )

        if len(seen_hrefs) >= target_end_index:
            print(f"✅ 已覆盖到第 {target_end_index} 条，当前累计 {len(seen_hrefs)} 条")
            return seen_hrefs

        if idle_rounds >= max_idle_scroll_rounds:
            print("⚠️ 连续多轮下滑未发现新笔记，提前结束滚动抓取")
            break

    return seen_hrefs


def _normalize_filter_option(filter_option: dict | str | None) -> dict[str, str]:
    if filter_option is None:
        return {}

    if isinstance(filter_option, str):
        raw_value = filter_option.strip()
        if not raw_value:
            return {}
        filter_option = json.loads(raw_value)

    if not isinstance(filter_option, dict):
        raise ValueError("filter 必须是 JSON 对象或 JSON 字符串")

    normalized: dict[str, str] = {}
    valid_keys = sorted(set(FILTER_KEY_ALIASES))
    for raw_key, raw_value in filter_option.items():
        if raw_value in (None, ""):
            continue
        canonical_key = FILTER_KEY_ALIASES.get(str(raw_key))
        if not canonical_key:
            raise ValueError(
                f"未知 filter 字段: {raw_key}，支持: {valid_keys}"
            )
        normalized[canonical_key] = str(raw_value).strip()

    return normalized


def _resolve_filter_selection(filter_option: dict[str, str]) -> dict[str, str]:
    selected = {}
    for field_name, selected_value in filter_option.items():
        config = FILTER_GROUPS[field_name]
        choices = config["choices"]
        if selected_value not in choices:
            raise ValueError(
                f"{field_name} 不支持 {selected_value}，可选: {sorted(choices)}"
            )
        selected[field_name] = selected_value
    return selected


def _filter_panel_open(page) -> bool:
    panel = page.locator(FILTER_PANEL_SELECTOR)
    if panel.count() == 0:
        return False
    try:
        return panel.first.is_visible(timeout=200)
    except Exception:
        return False


def _wait_for_filter_panel(page, should_open: bool, timeout_ms: int = 5_000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if _filter_panel_open(page) == should_open:
            return
        page.wait_for_timeout(150)
    state_label = "展开" if should_open else "收起"
    raise RuntimeError(f"筛选面板未能成功{state_label}")


def _toggle_filter_panel(page, should_open: bool) -> None:
    if _filter_panel_open(page) == should_open:
        return

    trigger = page.locator(FILTER_TRIGGER_SELECTOR).first
    if should_open:
        try:
            trigger.hover(timeout=5_000)
            _wait_for_filter_panel(page, True)
            return
        except Exception:
            pass

    trigger.click(timeout=5_000)
    _wait_for_filter_panel(page, should_open)


def _active_filter_titles(page) -> dict[str, str]:
    if not _filter_panel_open(page):
        return {}
    return page.evaluate(
        """
        () => {
          const activeMap = {};
          const groups = Array.from(document.querySelectorAll('.filter-panel .filters'));
          for (const group of groups) {
            const title = group.querySelector('span')?.innerText?.trim();
            const active = group.querySelector('.tags.active span')?.innerText?.trim();
            if (title && active) {
              activeMap[title] = active;
            }
          }
          return activeMap;
        }
        """
    )


def _resolve_filter_selector(page, field_name: str, option_text: str) -> str | None:
    group_index = FILTER_GROUP_INDEXES[field_name]
    return page.evaluate(
        """
        ([groupIndex, optionText]) => {
          const groups = Array.from(document.querySelectorAll('.filter-panel .filters'));
          const group = groups[groupIndex - 1];
          if (!group) {
            return null;
          }

          const tagContainer = group.querySelector('.tag-container');
          if (!tagContainer) {
            return null;
          }

          const children = Array.from(tagContainer.children);
          const matches = [];
          for (let index = 0; index < children.length; index += 1) {
            const node = children[index];
            if (!(node instanceof HTMLElement)) {
              continue;
            }
            if (!node.classList.contains('tags')) {
              continue;
            }
            if (node.innerText.trim() !== optionText) {
              continue;
            }

            const style = getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            const opacity = Number(style.opacity || '1');
            matches.push({
              index: index + 1,
              visible:
                style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                style.pointerEvents !== 'none' &&
                opacity > 0.5 &&
                rect.width > 0 &&
                rect.height > 0,
            });
          }

          const preferred = matches.find((item) => item.visible) || matches[0];
          if (!preferred) {
            return null;
          }

          return `${'.filter-panel'} .filters:nth-child(${groupIndex}) .tag-container .tags:nth-child(${preferred.index})`;
        }
        """,
        [group_index, option_text],
    )

def _click_filter_option(page, field_name: str, option_text: str):
    selector = _resolve_filter_selector(page, field_name, option_text)
    if not selector:
        return {"ok": False, "reason": "option_not_found"}

    page.locator(selector).first.click(timeout=5_000)
    return {"ok": True}


def _wait_for_search_results_refresh(
    page,
    previous_hrefs: list[str],
    timeout_ms: int = 5_000,
) -> list[str]:
    deadline = time.monotonic() + timeout_ms / 1000
    latest_hrefs = previous_hrefs

    while time.monotonic() < deadline:
        _raise_if_search_risk(page, "筛选后等待结果刷新")
        latest_hrefs = _collect_note_links(page, limit=8)
        if latest_hrefs and latest_hrefs != previous_hrefs:
            return latest_hrefs
        page.wait_for_timeout(250)

    return latest_hrefs


def _apply_filters_via_ui(page, selected_filter: dict[str, str]) -> None:
    if not selected_filter:
        return

    previous_hrefs = _collect_note_links(page, limit=8)
    _toggle_filter_panel(page, True)
    try:
        geo_warning_printed = False

        for field_name, selected_value in selected_filter.items():
            group_title = FILTER_GROUPS[field_name]["title"]
            result = _click_filter_option(page, field_name, selected_value)
            if not result.get("ok"):
                raise RuntimeError(
                    f"筛选点击失败: {group_title}={selected_value}, reason={result.get('reason')}"
                )

            page.wait_for_timeout(random.randint(800, 1_500))
            next_hrefs = _wait_for_search_results_refresh(page, previous_hrefs)
            if next_hrefs != previous_hrefs:
                previous_hrefs = next_hrefs
            else:
                print(f"⚠️ 筛选后结果列表未观察到明显变化: {group_title}={selected_value}")
            print(f"🧰 已点击筛选 {group_title}={selected_value}")

            if (
                field_name == "position_distance"
                and selected_value
                in FILTER_GROUPS["position_distance"].get("requires_geo_choices", set())
                and not geo_warning_printed
            ):
                print("⚠️ 位置距离筛选依赖页面定位能力，如未授权定位结果可能为空")
                geo_warning_printed = True
    finally:
        _toggle_filter_panel(page, False)


def search(
    key_word: str,
    top_n: int,
    delay_seconds: float = 0.0,
    filter_option: dict | str | None = None,
    *,
    start_index: int = 1,
    end_index: int | None = None,
    max_scroll_rounds: int | None = None,
    max_idle_scroll_rounds: int | None = None,
) -> list[str]:
    """
    搜索小红书笔记
    """
    search_url = "https://www.xiaohongshu.com/search_result?keyword=" + quote(key_word)
    normalized_filter = _normalize_filter_option(filter_option)
    start_index, end_index = _resolve_search_window(top_n, start_index, end_index)
    max_scroll_rounds, max_idle_scroll_rounds = _resolve_scroll_config(
        max_scroll_rounds,
        max_idle_scroll_rounds,
    )
    selected_filter = (
        _resolve_filter_selection(normalized_filter) if normalized_filter else None
    )

    driver, browser, context, page, settings, chrome_process = launch_profile_context(
        headless=False,
        startup_url=None,
    )
    try:
        print("🌐 导航到小红书主页...")
        print(
            f"⚙️ 搜索配置: start_index={start_index}, end_index={end_index}, "
            f"max_scroll_rounds={max_scroll_rounds}, "
            f"max_idle_scroll_rounds={max_idle_scroll_rounds}"
        )

        page.goto(search_url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        _raise_if_search_risk(page, "搜索页加载后检查")
        if page_requires_login(page):
            return [
                f'❌ 当前 Chrome {settings["profile_directory"]} 未登录小红书，请先运行 '
                "python3 scripts/manual_login.py"
            ]

        if not _wait_for_search_results(page):
            _raise_if_search_risk(page, "搜索结果捕获失败前检查")
            raise RuntimeError("未能在页面上捕获搜索结果")
        if selected_filter:
            print(
                "🧰 应用原生搜索筛选: "
                + json.dumps(selected_filter, ensure_ascii=False)
            )
            _apply_filters_via_ui(page, selected_filter)
            _raise_if_search_risk(page, "筛选后检查")
            if not _wait_for_search_results(page):
                print("⚪️ 当前筛选条件下没有可见笔记结果")
                return []
        _browse_random_note_from_search(page, delay_seconds)
        hrefs = _load_search_window(
            page,
            target_end_index=end_index,
            max_scroll_rounds=max_scroll_rounds,
            max_idle_scroll_rounds=max_idle_scroll_rounds,
        )
        selected_hrefs = hrefs[start_index - 1:end_index]
        expected_count = end_index - start_index + 1

        print(
            f"🪟 抓取窗口: 第 {start_index}-{end_index} 条，实际返回 {len(selected_hrefs)} 条"
        )
        if len(selected_hrefs) < expected_count:
            print(
                f"⚠️ 当前页面最多收集到 {len(hrefs)} 条唯一笔记，未完整覆盖目标窗口"
            )

        return selected_hrefs
    finally:
        close_profile_context(
            driver,
            browser,
            page=page,
            settings=settings,
            chrome_process=chrome_process,
        )
        

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="搜索小红书笔记")
    parser.add_argument("keyword", type=str, help="搜索关键词")
    parser.add_argument("--top_n", type=int, default=5, help="返回的笔记数量")
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="1-based 起始文章序号；默认从第 1 条开始",
    )
    parser.add_argument(
        "--end-index",
        type=int,
        help="1-based 结束文章序号；不传时按 start-index + top_n - 1 计算",
    )
    parser.add_argument(
        "--max-scroll-rounds",
        type=int,
        help=f"最多下滑轮数；默认 {MAX_SCROLL_ROUNDS}",
    )
    parser.add_argument(
        "--max-idle-scroll-rounds",
        type=int,
        help=f"连续无新增时提前停止的阈值；默认 {MAX_IDLE_SCROLL_ROUNDS}",
    )
    parser.add_argument(
        "--filter",
        help=(
            "可选筛选 JSON，例如: "
            '\'{"sort_by":"最新","note_type":"图文","publish_time":"一周内"}\''
        ),
    )
    add_delay_argument(parser)
    args = parser.parse_args()
    key_word = args.keyword
    top_n = args.top_n
    delay_seconds = resolve_delay_seconds(args.delay_seconds)

    try:
        result = search(
            key_word,
            top_n,
            delay_seconds,
            args.filter,
            start_index=args.start_index,
            end_index=args.end_index,
            max_scroll_rounds=args.max_scroll_rounds,
            max_idle_scroll_rounds=args.max_idle_scroll_rounds,
        )
        print(result)
    except OfficialRiskDetectedError as exc:
        print([f"❌ {exc}"])
