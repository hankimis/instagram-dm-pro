import os
import sys
import platform
import yaml
from pathlib import Path


def _get_base_dir() -> Path:
    """PyInstaller 번들 여부에 따라 올바른 기준 디렉터리를 반환한다."""
    if getattr(sys, 'frozen', False):
        # PyInstaller exe: exe가 있는 폴더를 기준으로 사용
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "insta_service.db"
CHROME_PROFILES_DIR = DATA_DIR / "chrome_profiles"
DM_IMAGES_DIR = DATA_DIR / "dm_images"
CONFIG_PATH = BASE_DIR / "config.yml"

# 디렉터리 자동 생성
DATA_DIR.mkdir(exist_ok=True)
CHROME_PROFILES_DIR.mkdir(exist_ok=True)
DM_IMAGES_DIR.mkdir(exist_ok=True)

def _detect_chrome_path() -> str:
    """OS별 Chrome 바이너리 경로를 자동 감지한다."""
    if platform.system() == "Windows":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    elif platform.system() == "Darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return "google-chrome"


_defaults = {
    "server": {
        "host": "0.0.0.0",
        "port": 8080,
    },
    "crawling": {
        "min_delay": 3.0,
        "max_delay": 8.0,
        "scroll_min_delay": 1.2,
        "scroll_max_delay": 2.5,
        "max_scroll_attempts": 50,
        "page_load_wait": 4.0,
    },
    "dm": {
        "hourly_limit": 20,
        "daily_limit_per_account": 80,
        "min_delay": 30,
        "max_delay": 90,
    },
    "chrome": {
        "binary_path": _detect_chrome_path(),
        "headless": False,
    },
    "selectors": {
        "post_link": 'a[href*="/p/"]',
        "username_primary": "a._acan._acao._acat._acaw._aj1-._ap30._a6hd",
        "username_fallback1": 'a[role="link"][tabindex="0"]._acan',
        "username_fallback2": 'article header a[href^="/"][role="link"]',
        "close_button": 'svg[aria-label="닫기"]',
    },
}


def _validate_config(cfg: dict) -> dict:
    """설정값의 타입과 범위를 검증하고, 잘못된 값은 기본값으로 대체한다."""
    # server
    srv = cfg.get("server", {})
    port = srv.get("port", _defaults["server"]["port"])
    if not isinstance(port, int) or not (1 <= port <= 65535):
        srv["port"] = _defaults["server"]["port"]
    cfg["server"] = srv

    # crawling — 양수 실수
    crawl = cfg.get("crawling", {})
    for key in ("min_delay", "max_delay", "scroll_min_delay", "scroll_max_delay", "page_load_wait"):
        val = crawl.get(key)
        if val is not None and (not isinstance(val, (int, float)) or val <= 0):
            crawl[key] = _defaults["crawling"].get(key, 3.0)
    if crawl.get("max_delay", 8) < crawl.get("min_delay", 3):
        crawl["max_delay"] = crawl["min_delay"]
    cfg["crawling"] = crawl

    # dm — 양수 정수
    dm = cfg.get("dm", {})
    for key in ("hourly_limit", "daily_limit_per_account", "min_delay", "max_delay"):
        val = dm.get(key)
        if val is not None and (not isinstance(val, (int, float)) or val < 1):
            dm[key] = _defaults["dm"].get(key, 20)
    if dm.get("max_delay", 90) < dm.get("min_delay", 30):
        dm["max_delay"] = dm["min_delay"]
    cfg["dm"] = dm

    # chrome
    chrome = cfg.get("chrome", {})
    if not isinstance(chrome.get("headless"), bool):
        chrome["headless"] = False
    cfg["chrome"] = chrome

    return cfg


def load_config() -> dict:
    """config.yml을 로드하고, 없으면 기본값으로 생성한다."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        # 기본값에 사용자 설정 머지 (1단계 깊이)
        merged = {}
        for section, defaults in _defaults.items():
            if isinstance(defaults, dict):
                merged[section] = {**defaults, **(user_cfg.get(section) or {})}
            else:
                merged[section] = user_cfg.get(section, defaults)
        # top-level 키 보존 (admin_server_url 등)
        for key, val in user_cfg.items():
            if key not in merged:
                merged[key] = val
        return _validate_config(merged)

    # config.yml이 없으면 기본값으로 생성
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(_defaults, f, allow_unicode=True, default_flow_style=False)
    return dict(_defaults)


def save_config(new_cfg: dict):
    """설정을 config.yml에 저장하고 런타임 cfg를 갱신한다."""
    global cfg
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(new_cfg, f, allow_unicode=True, default_flow_style=False)
    cfg.update(load_config())


cfg = load_config()
