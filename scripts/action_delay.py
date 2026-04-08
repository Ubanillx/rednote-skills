import os
import random
import time


DEFAULT_ACTION_DELAY_SECONDS = 0.0
DEFAULT_RANDOM_DELAY_MIN_SECONDS = 0.8
DEFAULT_RANDOM_DELAY_MAX_SECONDS = 2.2


def add_delay_argument(parser):
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=None,
        help=(
            "敏感操作前的固定延迟秒数。"
            "如果不传，会读取 REDNOTE_ACTION_DELAY_SECONDS。"
        ),
    )


def _read_float_env(name, default):
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    return float(raw_value)


def resolve_delay_seconds(delay_seconds=None):
    value = (
        delay_seconds
        if delay_seconds is not None
        else _read_float_env("REDNOTE_ACTION_DELAY_SECONDS", DEFAULT_ACTION_DELAY_SECONDS)
    )
    if value < 0:
        raise ValueError("delay_seconds must be greater than or equal to 0")
    return value


def resolve_random_delay_range():
    min_seconds = _read_float_env(
        "REDNOTE_RANDOM_DELAY_MIN_SECONDS",
        DEFAULT_RANDOM_DELAY_MIN_SECONDS,
    )
    max_seconds = _read_float_env(
        "REDNOTE_RANDOM_DELAY_MAX_SECONDS",
        DEFAULT_RANDOM_DELAY_MAX_SECONDS,
    )
    if min_seconds < 0 or max_seconds < 0:
        raise ValueError("Random delay range must be greater than or equal to 0")
    if min_seconds > max_seconds:
        raise ValueError("Random delay min seconds cannot be greater than max seconds")
    return min_seconds, max_seconds


def resolve_seconds_range(min_seconds, max_seconds, *, label="delay range"):
    resolved_min = float(min_seconds)
    resolved_max = float(max_seconds)
    if resolved_min < 0 or resolved_max < 0:
        raise ValueError(f"{label} must be greater than or equal to 0")
    if resolved_min > resolved_max:
        raise ValueError(f"{label} min seconds cannot be greater than max seconds")
    return resolved_min, resolved_max


def sleep_random_cooldown(action_name, min_seconds, max_seconds):
    resolved_min, resolved_max = resolve_seconds_range(
        min_seconds,
        max_seconds,
        label=f"{action_name} cooldown range",
    )
    cooldown = random.uniform(resolved_min, resolved_max)
    print(f"🧊 {action_name} {cooldown:.2f}s")
    if cooldown > 0:
        time.sleep(cooldown)
    return cooldown


def random_scroll_page(page, action_name):
    scroll_count = random.randint(2, 3)
    print(f"🌀 {action_name} 前随机滑动 {scroll_count} 次")
    for _ in range(scroll_count):
        distance = random.randint(120, 420)
        direction = random.choice((-1, 1))
        page.mouse.wheel(0, direction * distance)
        page.wait_for_timeout(random.randint(180, 420))


def find_blank_points(page):
    return page.evaluate(
        """
        () => {
            const width = window.innerWidth || document.documentElement.clientWidth || 0;
            const height = window.innerHeight || document.documentElement.clientHeight || 0;
            const xs = [0.12, 0.2, 0.5, 0.8, 0.88];
            const ys = [0.16, 0.28, 0.45, 0.62, 0.78, 0.88];

            const isInteractive = (element) => {
                if (!element || !(element instanceof Element)) return false;
                const interactiveSelector = [
                    'a',
                    'button',
                    'input',
                    'textarea',
                    'select',
                    '[role="button"]',
                    '[role="link"]',
                    '[role="textbox"]',
                    '[contenteditable="true"]',
                    '[tabindex]:not([tabindex="-1"])',
                    '[onclick]',
                ].join(',');
                if (element.closest(interactiveSelector)) return true;

                const style = window.getComputedStyle(element);
                if (!style) return false;
                if (style.cursor === 'pointer') return true;
                return false;
            };

            const points = [];
            for (const xRatio of xs) {
                for (const yRatio of ys) {
                    const x = Math.round(width * xRatio);
                    const y = Math.round(height * yRatio);
                    const stack = document.elementsFromPoint(x, y) || [];
                    const top = stack[0];
                    if (!top) continue;
                    if (stack.some(isInteractive)) continue;
                    const rect = top.getBoundingClientRect();
                    const area = rect.width * rect.height;
                    if (area < 1500) continue;
                    points.push({ x, y });
                }
            }
            return points;
        }
        """
    )


def click_random_blank_position(page, action_name):
    points = find_blank_points(page)
    if not points:
        print(f"⚪️ {action_name} 前未找到可靠空白区域，跳过空白点击")
        return False

    point = random.choice(points)
    print(f'⚪️ {action_name} 前点击空白位置 ({point["x"]}, {point["y"]})')
    page.mouse.move(point["x"], point["y"], steps=random.randint(4, 10))
    page.wait_for_timeout(random.randint(120, 280))
    page.mouse.click(point["x"], point["y"], delay=random.randint(40, 120))
    page.wait_for_timeout(random.randint(120, 280))
    return True


def humanize_before_sensitive_action(
    page,
    action_name,
    *,
    do_scroll=True,
    do_blank_click=True,
):
    try:
        if do_scroll:
            random_scroll_page(page, action_name)
        if do_blank_click:
            click_random_blank_position(page, action_name)
    except Exception as exc:
        print(f"⚠️ {action_name} 前的人类化操作失败，继续执行原动作: {exc}")


def wait_before_sensitive_action(
    page,
    action_name,
    delay_seconds=None,
    *,
    do_scroll=True,
    do_blank_click=True,
):
    humanize_before_sensitive_action(
        page,
        action_name,
        do_scroll=do_scroll,
        do_blank_click=do_blank_click,
    )
    fixed_delay_seconds = resolve_delay_seconds(delay_seconds)
    if fixed_delay_seconds > 0:
        print(f"⏳ {action_name} 前固定等待 {fixed_delay_seconds:.2f} 秒")
        page.wait_for_timeout(int(fixed_delay_seconds * 1000))

    random_min_seconds, random_max_seconds = resolve_random_delay_range()
    random_delay_seconds = random.uniform(random_min_seconds, random_max_seconds)
    print(f"🎲 {action_name} 前随机等待 {random_delay_seconds:.2f} 秒")
    page.wait_for_timeout(int(random_delay_seconds * 1000))
    return fixed_delay_seconds, random_delay_seconds
