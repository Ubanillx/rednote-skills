import argparse
from action_delay import add_delay_argument, resolve_delay_seconds, wait_before_sensitive_action
from browser_profile import (
    close_profile_context,
    launch_profile_context,
    page_requires_login,
)

def follow_user(note_url: str, delay_seconds: float = 0.0) -> str:
    """
    关注小红书用户
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

        result = "👤 用户已关注"
        try:
            wait_before_sensitive_action(page, "关注用户", delay_seconds)
            page.get_by_role("button", name="关注").click()
        except Exception:
            result = "⚠️ 已经关注该用户或无法关注"

        return result
    finally:
        close_profile_context(
            driver,
            browser,
            page=page,
            settings=settings,
            chrome_process=chrome_process,
        )

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description="关注小红书用户")
    parser.add_argument("note_url", type=str, help="小红书笔记URL")
    add_delay_argument(parser)
    args = parser.parse_args()
    note_url = args.note_url
    delay_seconds = resolve_delay_seconds(args.delay_seconds)
    
    result = follow_user(note_url, delay_seconds)
    print(result)
