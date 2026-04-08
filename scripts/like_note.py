import argparse
from action_delay import add_delay_argument, resolve_delay_seconds
from browser_profile import (
    close_profile_context,
    launch_profile_context,
    page_requires_login,
)
from interact_helpers import (
    LIKE_BUTTON_SELECTOR,
    click_interact_action,
    get_note_interact_state,
)

def like_note(note_url: str, delay_seconds: float = 0.0) -> str:
    """
    点赞小红书笔记
    :param note_url: 笔记URL
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

        state = get_note_interact_state(page)
        if state.get("liked"):
            return "❤️ 当前笔记已点赞，跳过重复操作"

        click_interact_action(
            page,
            action_name="点赞笔记",
            button_selector=LIKE_BUTTON_SELECTOR,
            state_key="liked",
            expected_state=True,
            delay_seconds=delay_seconds,
        )

        return "❤️ 笔记已点赞"
    finally:
        close_profile_context(
            driver,
            browser,
            page=page,
            settings=settings,
            chrome_process=chrome_process,
        )

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description="点赞小红书笔记")
    parser.add_argument("note_url", type=str, help="小红书笔记URL")
    add_delay_argument(parser)
    args = parser.parse_args()
    note_url = args.note_url
    delay_seconds = resolve_delay_seconds(args.delay_seconds)
    
    result = like_note(note_url, delay_seconds)
    print(result)
