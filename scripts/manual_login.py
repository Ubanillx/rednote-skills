from _bootstrap_env import ensure_local_venv

ensure_local_venv()

from browser_profile import close_profile_context, launch_profile_context


LOGIN_URL = "https://www.xiaohongshu.com/explore"


driver, browser, context, page, settings, chrome_process = launch_profile_context(
    headless=False,
    startup_url=LOGIN_URL,
)
try:
    print("Chrome profile opened for manual login.")
    print(
        f'Profile: {settings["profile_directory"]} @ {settings["source_user_data_dir"]}'
    )
    print(f'Chrome executable: {settings["chrome_path"]}')
    print(f'Chrome runtime dir: {settings["user_data_dir"]}')
    input("Log in in the opened Chrome window, then press Enter here to finish... ")
finally:
    close_profile_context(
        driver,
        browser,
        page=page,
        settings=settings,
        chrome_process=chrome_process,
    )
