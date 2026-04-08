import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_USER_DATA_DIR = os.path.expanduser("~/Library/Application Support/Google/Chrome")
DEFAULT_PROFILE_DIRECTORY = "Profile 2"
DEFAULT_DEBUG_PORT = 9223
LOGIN_MARKERS = ("登录", "扫码登录", "手机号登录")
COMMON_CHROME_APP_BUNDLES = (
    "/Applications/Google Chrome.app",
    "~/Applications/Google Chrome.app",
    "/Applications/Google Chrome Beta.app",
    "~/Applications/Google Chrome Beta.app",
    "/Applications/Google Chrome Canary.app",
    "~/Applications/Google Chrome Canary.app",
)
CHROME_BUNDLE_IDS = (
    "com.google.Chrome",
    "com.google.Chrome.beta",
    "com.google.Chrome.canary",
)
CHROME_BINARIES = (
    "google-chrome",
    "google-chrome-stable",
    "google-chrome-beta",
    "google-chrome-canary",
)
CACHE_EXCLUDES = (
    "Cache",
    "Code Cache",
    "GPUCache",
    "GrShaderCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "ShaderCache",
    "GraphiteDawnCache",
)


def _expand_path(path):
    return os.path.expanduser(path)


def _executable_exists(path):
    return Path(path).is_file() and os.access(path, os.X_OK)


def _bundle_executable_path(app_bundle):
    bundle_path = Path(_expand_path(app_bundle))
    return str(bundle_path / "Contents" / "MacOS" / bundle_path.stem)


def _spotlight_chrome_paths():
    if sys.platform != "darwin":
        return []

    discovered = []
    for bundle_id in CHROME_BUNDLE_IDS:
        try:
            result = subprocess.run(
                ["mdfind", f'kMDItemCFBundleIdentifier == "{bundle_id}"'],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return discovered

        for line in result.stdout.splitlines():
            app_bundle = line.strip()
            if app_bundle.endswith(".app"):
                discovered.append(_bundle_executable_path(app_bundle))

    return discovered


def detect_chrome_path():
    override = os.getenv("REDNOTE_CHROME_PATH")
    if override:
        chrome_path = _expand_path(override)
        if _executable_exists(chrome_path):
            return chrome_path
        raise FileNotFoundError(
            f"REDNOTE_CHROME_PATH does not point to an executable file: {chrome_path}"
        )

    candidates = []
    candidates.extend(_bundle_executable_path(bundle) for bundle in COMMON_CHROME_APP_BUNDLES)
    candidates.extend(_spotlight_chrome_paths())
    candidates.extend(filter(None, (shutil.which(binary) for binary in CHROME_BINARIES)))

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if _executable_exists(candidate):
            return candidate

    raise FileNotFoundError(
        "Could not auto-detect Google Chrome. Install Google Chrome or set "
        "REDNOTE_CHROME_PATH to the Chrome executable."
    )


def default_runtime_user_data_dir():
    workspace_dir = Path(__file__).resolve().parents[3]
    return str(workspace_dir / "tmp" / "rednote" / "chrome-user-data")


def _is_default_chrome_user_data_dir(path):
    try:
        return Path(path).resolve() == Path(DEFAULT_USER_DATA_DIR).resolve()
    except FileNotFoundError:
        return os.path.abspath(path) == os.path.abspath(DEFAULT_USER_DATA_DIR)


def _copy_if_exists(source, target):
    source_path = Path(source)
    if source_path.exists():
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


def _rsync_profile(source_root, target_root, profile_directory, delete=False):
    source_root_path = Path(source_root)
    target_root_path = Path(target_root)
    source_profile = source_root_path / profile_directory
    target_profile = target_root_path / profile_directory

    if not source_profile.exists():
        raise FileNotFoundError(
            f"Chrome profile directory was not found: {source_profile}"
        )

    target_root_path.mkdir(parents=True, exist_ok=True)
    _copy_if_exists(source_root_path / "Local State", target_root_path / "Local State")
    _copy_if_exists(source_root_path / "First Run", target_root_path / "First Run")

    cmd = ["rsync", "-a"]
    if delete:
        cmd.append("--delete")
    for pattern in CACHE_EXCLUDES:
        cmd.extend(["--exclude", pattern])
        cmd.extend(["--exclude", f"*/{pattern}"])
    cmd.extend(
        [
            "--exclude",
            "Singleton*",
            "--exclude",
            "DevToolsActivePort",
            f"{source_profile}/",
            str(target_profile),
        ]
    )
    subprocess.run(cmd, check=True)


def _cleanup_runtime_lock_files(runtime_user_data_dir):
    runtime_root = Path(runtime_user_data_dir)
    for pattern in ("Singleton*", "DevToolsActivePort"):
        for path in runtime_root.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def resolve_user_data_dirs(profile_directory):
    source_user_data_dir = os.path.expanduser(
        os.getenv("REDNOTE_CHROME_USER_DATA_DIR", DEFAULT_USER_DATA_DIR)
    )

    runtime_override = os.getenv("REDNOTE_CHROME_RUNTIME_USER_DATA_DIR")
    if runtime_override:
        runtime_user_data_dir = os.path.expanduser(runtime_override)
    elif _is_default_chrome_user_data_dir(source_user_data_dir):
        runtime_user_data_dir = default_runtime_user_data_dir()
    else:
        runtime_user_data_dir = source_user_data_dir

    if runtime_user_data_dir != source_user_data_dir:
        _rsync_profile(
            source_user_data_dir,
            runtime_user_data_dir,
            profile_directory,
        )
        _cleanup_runtime_lock_files(runtime_user_data_dir)
    else:
        runtime_profile_dir = Path(runtime_user_data_dir) / profile_directory
        if not runtime_profile_dir.exists():
            raise FileNotFoundError(
                f"Chrome profile directory was not found: {runtime_profile_dir}"
            )

    return source_user_data_dir, runtime_user_data_dir


def chrome_settings():
    chrome_path = detect_chrome_path()
    profile_directory = os.getenv(
        "REDNOTE_CHROME_PROFILE_DIRECTORY", DEFAULT_PROFILE_DIRECTORY
    )
    source_user_data_dir, runtime_user_data_dir = resolve_user_data_dirs(profile_directory)
    debug_port = int(os.getenv("REDNOTE_CHROME_DEBUG_PORT", str(DEFAULT_DEBUG_PORT)))
    return {
        "chrome_path": chrome_path,
        "source_user_data_dir": source_user_data_dir,
        "user_data_dir": runtime_user_data_dir,
        "profile_directory": profile_directory,
        "debug_port": debug_port,
    }


def _port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _cdp_ready(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def page_requires_login(page, login_markers=LOGIN_MARKERS):
    try:
        page_text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return any(marker in page_text for marker in login_markers)


def persist_runtime_profile(settings):
    source_user_data_dir = settings.get("source_user_data_dir")
    runtime_user_data_dir = settings.get("user_data_dir")
    profile_directory = settings.get("profile_directory")
    if not source_user_data_dir or not runtime_user_data_dir or not profile_directory:
        return
    if source_user_data_dir == runtime_user_data_dir:
        return
    _rsync_profile(
        runtime_user_data_dir,
        source_user_data_dir,
        profile_directory,
    )


def launch_profile_context(headless=False, startup_url=None):
    if headless:
        raise ValueError("Chrome profile mode must run headed")

    from patchright.sync_api import sync_playwright

    settings = chrome_settings()
    Path(settings["user_data_dir"]).mkdir(parents=True, exist_ok=True)

    chrome_process = None
    if not _cdp_ready(settings["debug_port"]):
        cmd = [
            settings["chrome_path"],
            f'--user-data-dir={settings["user_data_dir"]}',
            f'--profile-directory={settings["profile_directory"]}',
            f'--remote-debugging-port={settings["debug_port"]}',
            '--no-first-run',
            '--no-default-browser-check',
        ]
        if startup_url:
            cmd.append(startup_url)
        chrome_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    for _ in range(40):
        if _cdp_ready(settings["debug_port"]):
            break
        time.sleep(0.5)
    else:
        raise RuntimeError("Chrome remote debugging port did not become available")

    driver = sync_playwright().start()
    browser = driver.chromium.connect_over_cdp(
        f'http://127.0.0.1:{settings["debug_port"]}'
    )

    context = browser.contexts[0] if browser.contexts else browser.new_context()
    # Always use a fresh tab so we do not hijack whatever the user already has open.
    page = context.new_page()
    if startup_url:
        page.goto(startup_url, wait_until="domcontentloaded")

    return driver, browser, context, page, settings, chrome_process


def close_profile_context(
    driver,
    browser,
    page=None,
    settings=None,
    chrome_process=None,
    keep_browser_open=False,
):
    try:
        if page and not keep_browser_open:
            page.close()
    except Exception:
        pass

    # When connected over CDP to a real Chrome profile, stopping Patchright is safer
    # than closing the whole browser, which can shut down the user's session.
    driver.stop()

    if chrome_process and not keep_browser_open:
        try:
            chrome_process.terminate()
            chrome_process.wait(timeout=10)
        except Exception:
            try:
                chrome_process.kill()
            except Exception:
                pass

    if not keep_browser_open and settings:
        try:
            persist_runtime_profile(settings)
        except Exception:
            pass
