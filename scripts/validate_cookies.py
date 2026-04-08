from _bootstrap_env import ensure_local_venv

ensure_local_venv()

from browser_profile import close_profile_context, launch_profile_context


TARGET_URL = "https://creator.xiaohongshu.com/creator/home"
LOGIN_MARKERS = ["登录", "扫码登录", "手机号登录"]
AUTH_MARKERS = ["创作服务", "数据中心", "创作者中心", "发布笔记"]


driver, browser, context, page, settings, chrome_process = launch_profile_context(
    headless=False,
    startup_url=TARGET_URL,
)
try:
    page.wait_for_timeout(3000)
    page_text = page.locator("body").inner_text(timeout=5000)
    logged_in = any(marker in page_text for marker in AUTH_MARKERS) and not any(
        marker in page_text for marker in LOGIN_MARKERS
    )
    print(logged_in)
    print(
        f'Using Chrome profile: {settings["profile_directory"]} @ {settings["source_user_data_dir"]}'
    )
    print(f'Chrome executable: {settings["chrome_path"]}')
    print(f'Chrome runtime dir: {settings["user_data_dir"]}')
finally:
    close_profile_context(
        driver,
        browser,
        page=page,
        settings=settings,
        chrome_process=chrome_process,
    )
