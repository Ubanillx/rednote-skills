import argparse
import os
import random

from action_delay import add_delay_argument, resolve_delay_seconds, wait_before_sensitive_action
from browser_profile import (
    close_profile_context,
    launch_profile_context,
    page_requires_login,
)
from interact_helpers import (
    LIKE_BUTTON_SELECTOR,
    check_rate_limit,
    click_interact_action,
    get_note_interact_state,
)


MAX_COMMENT_LENGTH = 280
TYPING_DELAY_MIN_MS = 30
TYPING_DELAY_MAX_MS = 80
PRE_SUBMIT_DELAY_MIN_SECONDS = 1.5
PRE_SUBMIT_DELAY_MAX_SECONDS = 3.0
POST_SUBMIT_COOLDOWN_MIN_SECONDS = 8.0
POST_SUBMIT_COOLDOWN_MAX_SECONDS = 15.0
RETRY_WAIT_MIN_SECONDS = 2.0
RETRY_WAIT_MAX_SECONDS = 4.0
MAX_SUBMIT_RETRIES = 1
DEFAULT_AUTO_LIKE_PROBABILITY = 0.35

COMMENT_REGION_SELECTORS = [
    ".comments-wrap",
    ".comment-wrapper",
]
COMMENT_TRIGGER_SELECTOR = "div.input-box div.content-edit span"
COMMENT_EDITOR_SELECTOR = "div.input-box div.content-edit p.content-input"
COMMENT_SUBMIT_SELECTOR = "div.bottom button.submit"


def validate_comment(content):
    normalized = (content or "").strip()
    if not normalized:
        return "评论内容不能为空"
    if len(normalized) > MAX_COMMENT_LENGTH:
        return f"评论内容超长（{len(normalized)}/{MAX_COMMENT_LENGTH}）"
    return None


def resolve_auto_like_probability(like_probability=None):
    if like_probability is None:
        raw_value = os.getenv("REDNOTE_COMMENT_AUTO_LIKE_PROBABILITY")
        like_probability = (
            DEFAULT_AUTO_LIKE_PROBABILITY
            if raw_value in (None, "")
            else float(raw_value)
        )

    if not 0 <= like_probability <= 1:
        raise ValueError("like_probability must be between 0 and 1")

    return like_probability


def scroll_to_comment_region(page):
    page.evaluate(
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
    page.wait_for_timeout(1000)


def maybe_like_note_before_comment(page, delay_seconds, like_probability):
    try:
        if like_probability <= 0:
            print("⚪️ 自动点赞概率为 0，跳过点赞")
            return False

        roll = random.random()
        print(f"🎲 评论前自动点赞概率={like_probability:.2f}，本次抽样={roll:.4f}")
        if roll >= like_probability:
            print("⚪️ 本次未命中自动点赞概率，继续评论流程")
            return False

        if get_note_interact_state(page).get("liked"):
            print("⚪️ 当前帖子已点赞，跳过自动点赞")
            return False

        click_interact_action(
            page,
            action_name="评论前随机点赞帖子",
            button_selector=LIKE_BUTTON_SELECTOR,
            state_key="liked",
            expected_state=True,
            delay_seconds=delay_seconds,
        )

        print("❤️ 评论前随机点赞成功")
        return True
    except Exception as exc:
        print(f"⚠️ 评论前随机点赞失败，跳过点赞并继续评论：{exc}")
        return False


def activate_comment_input(page):
    trigger = page.locator(COMMENT_TRIGGER_SELECTOR).first
    editor = page.locator(COMMENT_EDITOR_SELECTOR).first
    submit_button = page.locator(COMMENT_SUBMIT_SELECTOR).first

    if not trigger.is_visible(timeout=4000):
        raise RuntimeError("未找到评论占位触发器")

    print(f"🟡 点击评论占位符：{COMMENT_TRIGGER_SELECTOR}")
    trigger.click(timeout=3000)
    page.wait_for_timeout(500)

    if not editor.is_visible(timeout=3000):
        raise RuntimeError("评论输入框未成功激活")

    print(f"🟡 评论输入态已激活：{COMMENT_EDITOR_SELECTOR}")
    if submit_button.is_visible(timeout=1500):
        print(f"🟡 发送按钮已出现：{COMMENT_SUBMIT_SELECTOR}")

    return editor


def focus_and_prepare_editor(page):
    editor = page.locator(COMMENT_EDITOR_SELECTOR).first
    if not editor.is_visible(timeout=3000):
        raise RuntimeError("未找到评论输入区")

    print(f"🟡 聚焦评论输入区：{COMMENT_EDITOR_SELECTOR}")
    editor.click(timeout=3000)
    page.wait_for_timeout(300)
    editor.evaluate(
        """element => {
            element.focus();
            const selection = window.getSelection();
            if (!selection) return;
            const range = document.createRange();
            range.selectNodeContents(element);
            range.collapse(false);
            selection.removeAllRanges();
            selection.addRange(range);
        }"""
    )
    return editor


def clear_editor(editor):
    editor.evaluate(
        """element => {
            element.innerHTML = '';
            element.textContent = '';
            element.dispatchEvent(new InputEvent('input', {
                bubbles: true,
                inputType: 'deleteContentBackward',
                data: null,
            }));
            element.dispatchEvent(new Event('change', { bubbles: true }));
        }"""
    )


def type_comment_content(page, content):
    editor = focus_and_prepare_editor(page)
    clear_editor(editor)
    page.wait_for_timeout(200)

    typing_delay = random.randint(TYPING_DELAY_MIN_MS, TYPING_DELAY_MAX_MS)
    print(f"⌨️ 开始逐字输入评论，字符延迟 {typing_delay}ms")
    page.keyboard.type(content, delay=typing_delay)
    editor.evaluate(
        """element => {
            element.dispatchEvent(new Event('input', { bubbles: true }));
            element.dispatchEvent(new Event('change', { bubbles: true }));
        }"""
    )
    return typing_delay


def click_send_button(page):
    submit_button = page.locator(COMMENT_SUBMIT_SELECTOR).first
    if not submit_button.is_visible(timeout=3000):
        raise RuntimeError("未找到发送按钮 div.bottom button.submit")

    print(f"🚀 点击发送按钮：{COMMENT_SUBMIT_SELECTOR}")
    submit_button.scroll_into_view_if_needed(timeout=1500)
    submit_button.click(timeout=3000)
    page.wait_for_timeout(1500)
    return COMMENT_SUBMIT_SELECTOR


def verify_comment_sent(page, comment_text):
    page.wait_for_timeout(1800)

    input_closed = False
    try:
        editor = page.locator(COMMENT_EDITOR_SELECTOR).first
        if not editor.is_visible(timeout=800):
            input_closed = True
        else:
            current_text = editor.inner_text(timeout=1000).strip()
            if current_text == "":
                print("✅ 评论发送后输入区已清空")
                return
    except Exception:
        input_closed = True

    if input_closed:
        print("✅ 评论发送后输入区已关闭")
        return

    try:
        body_text = page.locator("body").inner_text(timeout=3000)
        if "评论成功" in body_text or comment_text in body_text:
            print("✅ 页面已出现评论成功提示或评论内容回显")
            return
    except Exception:
        pass

    send_visible = False
    try:
        send_visible = page.locator(COMMENT_SUBMIT_SELECTOR).first.is_visible(timeout=800)
    except Exception:
        pass

    raise RuntimeError(
        "发送后未确认成功：评论输入区仍存在且未清空，"
        f"发送按钮仍可见={send_visible}"
    )


def submit_comment_once(page, final_comment, delay_seconds):
    scroll_to_comment_region(page)

    wait_before_sensitive_action(page, "打开评论输入框", delay_seconds)
    activate_comment_input(page)

    wait_before_sensitive_action(page, "填写评论内容", delay_seconds)
    type_comment_content(page, final_comment)

    pre_submit_wait = random.uniform(
        PRE_SUBMIT_DELAY_MIN_SECONDS,
        PRE_SUBMIT_DELAY_MAX_SECONDS,
    )
    print(f"⏳ 提交前等待 {pre_submit_wait:.2f}s")
    page.wait_for_timeout(int(pre_submit_wait * 1000))

    wait_before_sensitive_action(
        page,
        "发送评论",
        delay_seconds,
        do_scroll=False,
        do_blank_click=False,
    )
    click_path = click_send_button(page)
    print(f"✅ 已触发发送点击：{click_path}")

    if check_rate_limit(page):
        raise RuntimeError("检测到评论频率限制，请稍后再试")

    verify_comment_sent(page, final_comment)


def submit_comment_with_retry(page, final_comment, delay_seconds):
    last_error = None
    for attempt in range(MAX_SUBMIT_RETRIES + 1):
        if attempt > 0:
            retry_wait = random.uniform(RETRY_WAIT_MIN_SECONDS, RETRY_WAIT_MAX_SECONDS)
            print(
                f"🔁 评论发送重试中（第 {attempt + 1}/{MAX_SUBMIT_RETRIES + 1} 次），"
                f"等待 {retry_wait:.2f}s"
            )
            page.wait_for_timeout(int(retry_wait * 1000))
        try:
            submit_comment_once(page, final_comment, delay_seconds)
            return
        except Exception as exc:
            last_error = exc
            print(f"⚠️ 本次评论发送失败：{exc}")

    raise RuntimeError(f"评论发送失败：{last_error}") from last_error


def comment_note(
    note_url: str,
    comment_text: str,
    delay_seconds: float = 0.0,
    like_probability: float = DEFAULT_AUTO_LIKE_PROBABILITY,
) -> str:
    """
    发送最终评论文本到小红书帖子
    :param note_url: 笔记URL
    :param comment_text: 最终待发送评论
    """
    driver, browser, context, page, settings, chrome_process = launch_profile_context(
        headless=False,
        startup_url=note_url,
    )
    try:
        print("🌐 导航到小红书笔记页面...")
        page.wait_for_timeout(1000)
        if page_requires_login(page):
            return (
                f'❌ 当前 Chrome {settings["profile_directory"]} 未登录小红书，请先运行 '
                "python3 scripts/manual_login.py"
            )

        final_comment = comment_text.strip()
        comment_error = validate_comment(final_comment)
        if comment_error:
            return f"❌ {comment_error}"

        print(f"📝 准备发送最终评论：{final_comment}")
        did_like = maybe_like_note_before_comment(page, delay_seconds, like_probability)

        submit_comment_with_retry(page, final_comment, delay_seconds)

        cooldown = random.uniform(
            POST_SUBMIT_COOLDOWN_MIN_SECONDS,
            POST_SUBMIT_COOLDOWN_MAX_SECONDS,
        )
        print(f"🧊 评论发送成功，提交后冷却 {cooldown:.2f}s")
        page.wait_for_timeout(int(cooldown * 1000))
        like_suffix = "，并已随机点赞帖子" if did_like else ""
        return f"💬 评论已发布：{final_comment}{like_suffix}"
    finally:
        close_profile_context(
            driver,
            browser,
            page=page,
            settings=settings,
            chrome_process=chrome_process,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将传入的最终评论文本发布到小红书帖子")
    parser.add_argument("note_url", type=str, help="小红书笔记URL")
    parser.add_argument(
        "comment_text",
        type=str,
        help="最终待发送评论；Python 不会再对其进行改写",
    )
    parser.add_argument(
        "--like-probability",
        type=float,
        default=None,
        help=(
            "评论前自动点赞帖子的概率，范围 0-1。"
            "如果不传，会读取 REDNOTE_COMMENT_AUTO_LIKE_PROBABILITY，默认 0.35。"
        ),
    )
    add_delay_argument(parser)
    args = parser.parse_args()

    note_url = args.note_url
    comment_text = args.comment_text
    delay_seconds = resolve_delay_seconds(args.delay_seconds)
    like_probability = resolve_auto_like_probability(args.like_probability)

    result = comment_note(note_url, comment_text, delay_seconds, like_probability)
    print(result)
