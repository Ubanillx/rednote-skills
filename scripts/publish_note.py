import argparse
import re
from pathlib import Path

from _bootstrap_env import ensure_local_venv

ensure_local_venv()

from action_delay import add_delay_argument, resolve_delay_seconds, wait_before_sensitive_action
from browser_profile import close_profile_context, launch_profile_context


CREATOR_HOME_URL = "https://creator.xiaohongshu.com/creator/home"
PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?from=menu&target=article"
DRAFT_BUTTON_TEXTS = ["暂存离开", "保存草稿", "存草稿", "保存到草稿"]
LEAVE_BUTTON_TEXTS = ["离开", "关闭", "返回"]
STASH_BUTTON_TEXTS = ["暂存离开", "保存草稿并离开", "保存并离开", "离开并保存"]
PUBLISH_ENTRY_TEXTS = ["发布笔记", "去发布"]
LONG_FORM_ENTRY_TEXTS = ["写长文"]
NEW_DRAFT_TEXTS = ["新的创作"]
IMAGE_PLACEHOLDER_RE = re.compile(r"\[\[image:(.+?)\]\]")


def wait_for_title_editor(page, timeout=15000):
    locator = page.locator('textarea[placeholder*="输入标题"]').first
    try:
        return locator if locator.is_visible(timeout=timeout) else None
    except Exception:
        return None


def first_visible(page, selectors):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=1500):
                return locator
        except Exception:
            continue
    return None


def click_by_text(page, texts, delay_seconds=None, action_name=None):
    for text in texts:
        candidates = [
            page.get_by_role("button", name=text),
            page.get_by_text(text, exact=True),
            page.locator(f'text="{text}"'),
            page.locator(f'[aria-label="{text}"]'),
        ]
        for locator in candidates:
            try:
                target = locator.first
                if target.is_visible(timeout=1200):
                    if action_name:
                        wait_before_sensitive_action(page, action_name, delay_seconds)
                    target.click(timeout=3000)
                    return text
            except Exception:
                continue
    return None


def click_creator_tab(page, text, delay_seconds=None, action_name=None):
    locator = page.locator(".creator-tab").filter(
        has=page.locator(".title", has_text=text)
    ).last
    try:
        if locator.is_visible(timeout=1500):
            if action_name:
                wait_before_sensitive_action(page, action_name, delay_seconds)
            locator.click(timeout=3000)
            return text
    except Exception:
        return None
    return None


def dismiss_popups(page):
    for text in ["知道了", "我知道了", "以后再说", "暂不", "关闭"]:
        click_by_text(page, [text])


def focus_body_end(page):
    focused = page.evaluate("""
        () => {
            const editor = document.querySelector('[contenteditable="true"]');
            if (!editor) return false;
            editor.focus();
            const range = document.createRange();
            range.selectNodeContents(editor);
            range.collapse(false);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return true;
        }
    """)
    if not focused:
        raise RuntimeError("Could not focus the long-form editor")


def find_toolbar_button_by_tooltip(page, tooltip_text):
    buttons = page.locator("button.menu-item")
    for index in range(buttons.count()):
        button = buttons.nth(index)
        try:
            button.hover(timeout=2000)
            tooltip = page.locator(".menu-tooltip").filter(has_text=tooltip_text).last
            if tooltip.is_visible(timeout=1000):
                return button
        except Exception:
            continue
    raise RuntimeError(f'Could not find toolbar button for "{tooltip_text}"')


def resolve_image_path(raw_path):
    image_path = Path(raw_path.strip()).expanduser()
    if not image_path.is_absolute():
        image_path = (Path.cwd() / image_path).resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"Image file not found: {image_path}")
    return str(image_path)


def parse_body_tokens(body):
    tokens = []
    cursor = 0
    for match in IMAGE_PLACEHOLDER_RE.finditer(body):
        if match.start() > cursor:
            tokens.append(("text", body[cursor:match.start()]))
        tokens.append(("image", resolve_image_path(match.group(1))))
        cursor = match.end()
    if cursor < len(body):
        tokens.append(("text", body[cursor:]))
    return tokens


def ensure_long_form_editor(page, delay_seconds):
    if wait_for_title_editor(page, timeout=3000):
        return

    dismiss_popups(page)
    if "/publish/" not in page.url:
        if click_by_text(
            page,
            PUBLISH_ENTRY_TEXTS,
            delay_seconds=delay_seconds,
            action_name="进入发布入口",
        ):
            page.wait_for_timeout(2000)
        else:
            page.goto(PUBLISH_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

    if "target=article" not in page.url:
        if click_creator_tab(
            page,
            LONG_FORM_ENTRY_TEXTS[0],
            delay_seconds=delay_seconds,
            action_name="切换到长文创作",
        ):
            page.wait_for_timeout(2500)
        else:
            page.goto(PUBLISH_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

    dismiss_popups(page)
    if click_by_text(
        page,
        NEW_DRAFT_TEXTS,
        delay_seconds=delay_seconds,
        action_name="新建长文草稿",
    ):
        page.wait_for_timeout(2500)

    if wait_for_title_editor(page, timeout=15000):
        return

    raise RuntimeError("Could not open the long-form draft editor")


def fill_title(page, title, delay_seconds):
    locator = first_visible(
        page,
        [
            'textarea[placeholder*="输入标题"]',
            'input[placeholder*="标题"]',
            'textarea[placeholder*="标题"]',
            'input[aria-label*="标题"]',
            'textarea[aria-label*="标题"]',
            "input",
        ],
    )
    if not locator:
        raise RuntimeError("Could not find title input")
    wait_before_sensitive_action(page, "填写标题", delay_seconds)
    locator.click()
    locator.fill(title)


def fill_body(page, body, delay_seconds):
    tokens = parse_body_tokens(body)
    if any(token_type == "image" for token_type, _ in tokens):
        wait_before_sensitive_action(page, "编辑正文", delay_seconds)
        insert_body_tokens(page, tokens, delay_seconds)
        return

    locator = first_visible(
        page,
        [
            '[contenteditable="true"]',
            'textarea[placeholder*="正文"]',
            'textarea[placeholder*="描述"]',
            'textarea[placeholder*="内容"]',
            "textarea",
        ],
    )
    if not locator:
        raise RuntimeError("Could not find body editor")
    wait_before_sensitive_action(page, "填写正文", delay_seconds)
    locator.click()
    try:
        locator.fill(body)
    except Exception:
        locator.press("Meta+A")
        locator.press("Backspace")
        locator.type(body, delay=10)


def insert_body_tokens(page, tokens, delay_seconds):
    image_button = find_toolbar_button_by_tooltip(page, "图片")
    for token_type, value in tokens:
        focus_body_end(page)
        if token_type == "text":
            if value:
                page.keyboard.type(value, delay=10)
            continue

        before_count = page.locator("img.image").count()
        image_name = Path(value).name
        wait_before_sensitive_action(page, f"插入图片 {image_name}", delay_seconds)
        with page.expect_file_chooser(timeout=5000) as chooser_info:
            image_button.click(timeout=3000)
        chooser_info.value.set_files(value)
        page.wait_for_function(
            """expectedCount => {
                return document.querySelectorAll('img.image').length > expectedCount;
            }""",
            arg=before_count,
            timeout=20000,
        )
        page.wait_for_timeout(1000)


def save_draft(page, delay_seconds):
    direct = click_by_text(
        page,
        DRAFT_BUTTON_TEXTS,
        delay_seconds=delay_seconds,
        action_name="保存草稿",
    )
    if direct:
        return direct

    leave = click_by_text(page, LEAVE_BUTTON_TEXTS)
    if leave:
        page.wait_for_timeout(800)
    else:
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)

    stash = click_by_text(
        page,
        STASH_BUTTON_TEXTS,
        delay_seconds=delay_seconds,
        action_name="离开并保存草稿",
    )
    if stash:
        return stash
    raise RuntimeError("Could not find a draft-save action")


def verify_saved(page, title):
    page.wait_for_timeout(4000)
    page_text = page.locator("body").inner_text(timeout=10000)
    if "保存成功" in page_text or title in page_text:
        return
    raise RuntimeError("Draft save action was triggered but the draft was not confirmed")


def main():
    parser = argparse.ArgumentParser(description="将笔记保存到小红书草稿箱")
    parser.add_argument(
        "title",
        nargs="?",
        default="测试｜今天先把灵感存成草稿",
        help="草稿标题",
    )
    parser.add_argument(
        "body",
        nargs="?",
        default="这是一篇测试文章，用来确认当前小红书账号可以正常创建草稿。\n\n先把想法写下来，再慢慢优化标题、封面和发布时间，通常比卡在第一步更重要。\n\n如果你现在看到这篇内容，说明这条创作链路已经能正常工作，后面就可以继续批量做选题和内容打磨。\n\n#测试文章 #草稿箱 #小红书运营",
        help="草稿正文，支持 [[image:/absolute/path/to/file]] 占位符",
    )
    add_delay_argument(parser)
    args = parser.parse_args()

    title = args.title
    body = args.body
    delay_seconds = resolve_delay_seconds(args.delay_seconds)

    driver, browser, context, page, settings, chrome_process = launch_profile_context(
        headless=False,
        startup_url=PUBLISH_URL,
    )
    try:
        page.wait_for_timeout(2500)
        ensure_long_form_editor(page, delay_seconds)
        dismiss_popups(page)
        fill_title(page, title, delay_seconds)
        fill_body(page, body, delay_seconds)
        page.wait_for_timeout(1000)
        action = save_draft(page, delay_seconds)
        verify_saved(page, title)
        print(f"Draft save flow triggered with: {action}")
        print(f"Current page: {page.url}")
        print(f"Configured fixed sensitive-action delay: {delay_seconds:.2f}s")
        print(
            f'Using Chrome profile: {settings["profile_directory"]} @ {settings["source_user_data_dir"]}'
        )
        print(f'Chrome executable: {settings["chrome_path"]}')
        print(f'Chrome runtime dir: {settings["user_data_dir"]}')
        print("Draft saved. The browser window will stay open for manual review.")
    finally:
        close_profile_context(
            driver,
            browser,
            page=page,
            settings=settings,
            chrome_process=chrome_process,
            keep_browser_open=True,
        )


if __name__ == "__main__":
    main()
