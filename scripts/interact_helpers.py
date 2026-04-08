import json
import random
import time

from action_delay import wait_before_sensitive_action


LIKE_BUTTON_SELECTOR = ".left > .like-wrapper"
COLLECT_BUTTON_SELECTOR = ".left > .collect-wrapper"

INTERACT_STATE_FALLBACKS = {
    "liked": {
        "selector": LIKE_BUTTON_SELECTOR,
        "class_names": ("like-active", "liked"),
    },
    "collected": {
        "selector": COLLECT_BUTTON_SELECTOR,
        "class_names": ("collect-active", "collected", "active"),
    },
}

RATE_LIMIT_TEXTS = ("频繁", "操作太快", "稍后再试", "限制")

POST_CLICK_COOLDOWN_MIN_SECONDS = 5.0
POST_CLICK_COOLDOWN_MAX_SECONDS = 12.0
BATCH_INTERACT_THRESHOLD = 3
BATCH_COOLDOWN_MIN_SECONDS = 15.0
BATCH_COOLDOWN_MAX_SECONDS = 30.0

_INTERACTION_COUNT = 0


def _raw_interact_state(page):
    raw_state = page.evaluate(
        """
        () => {
            const noteDetailMap = window.__INITIAL_STATE__?.note?.noteDetailMap;
            if (!noteDetailMap) return null;

            let map = noteDetailMap;
            if (noteDetailMap.value !== undefined) {
                map = noteDetailMap.value;
            } else if (noteDetailMap._value !== undefined) {
                map = noteDetailMap._value;
            }

            if (!map) return null;
            const firstKey = Object.keys(map)[0];
            if (!firstKey) return null;

            const interactInfo = map[firstKey]?.note?.interactInfo;
            if (!interactInfo) return null;

            return JSON.stringify({
                liked: !!interactInfo.liked,
                collected: !!interactInfo.collected,
            });
        }
        """
    )
    if not raw_state:
        return None

    try:
        return json.loads(raw_state)
    except json.JSONDecodeError:
        return None


def _fallback_interact_state(page, state_key):
    config = INTERACT_STATE_FALLBACKS.get(state_key)
    if not config:
        return None

    locator = page.locator(config["selector"]).first
    try:
        if not locator.is_visible(timeout=1500):
            return None
    except Exception:
        return None

    class_name = locator.get_attribute("class") or ""
    class_tokens = set(class_name.split())
    return any(token in class_tokens for token in config["class_names"])


def get_note_interact_state(page):
    state = _raw_interact_state(page)
    if state is None:
        state = {}

    for key in ("liked", "collected"):
        if key not in state:
            fallback = _fallback_interact_state(page, key)
            if fallback is not None:
                state[key] = fallback

    return {
        "liked": bool(state.get("liked", False)),
        "collected": bool(state.get("collected", False)),
    }


def wait_for_interact_state(page, state_key, expected_state, timeout_ms=5000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        state = get_note_interact_state(page)
        if state.get(state_key) is expected_state:
            return True
        page.wait_for_timeout(250)
    return get_note_interact_state(page).get(state_key) is expected_state


def check_rate_limit(page):
    body_locator = page.locator("body")
    try:
        body_text = body_locator.inner_text(timeout=2000)
    except Exception:
        body_text = ""

    for text in RATE_LIMIT_TEXTS:
        if text in body_text:
            print(f"⚠️ 检测到频率限制提示：{text}")
            return True
        try:
            toast = page.locator(f'div.d-toast:has-text("{text}")').first
            if toast.is_visible(timeout=500):
                print(f"⚠️ 检测到频率限制 toast：{text}")
                return True
        except Exception:
            continue
    return False


def cooldown_after_interaction(page, action_name):
    global _INTERACTION_COUNT
    _INTERACTION_COUNT += 1

    if _INTERACTION_COUNT % BATCH_INTERACT_THRESHOLD == 0:
        cooldown = random.uniform(
            BATCH_COOLDOWN_MIN_SECONDS,
            BATCH_COOLDOWN_MAX_SECONDS,
        )
        print(
            f"🧊 {action_name} 后触发批次冷却（第 {_INTERACTION_COUNT} 次互动）"
            f" {cooldown:.2f}s"
        )
    else:
        cooldown = random.uniform(
            POST_CLICK_COOLDOWN_MIN_SECONDS,
            POST_CLICK_COOLDOWN_MAX_SECONDS,
        )
        print(f"🧊 {action_name} 后冷却 {cooldown:.2f}s")

    page.wait_for_timeout(int(cooldown * 1000))
    return cooldown


def click_interact_action(
    page,
    *,
    action_name,
    button_selector,
    state_key,
    expected_state,
    delay_seconds,
):
    button = page.locator(button_selector).first
    if not button.is_visible(timeout=4000):
        raise RuntimeError(f"未找到{action_name}按钮：{button_selector}")

    wait_before_sensitive_action(page, action_name, delay_seconds)
    button.click(timeout=3000)
    page.wait_for_timeout(1200)

    if check_rate_limit(page):
        raise RuntimeError(f"{action_name}后检测到频率限制，请稍后再试")

    if not wait_for_interact_state(page, state_key, expected_state):
        raise RuntimeError(
            f"{action_name}后未检测到目标状态：{state_key}={expected_state}"
        )

    cooldown_after_interaction(page, action_name)
    return True
