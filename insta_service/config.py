import os
import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "insta_service.db"
CHROME_PROFILES_DIR = DATA_DIR / "chrome_profiles"
DM_IMAGES_DIR = DATA_DIR / "dm_images"
CONFIG_PATH = BASE_DIR / "config.yml"

# 디렉터리 자동 생성
DATA_DIR.mkdir(exist_ok=True)
CHROME_PROFILES_DIR.mkdir(exist_ok=True)
DM_IMAGES_DIR.mkdir(exist_ok=True)

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
        "binary_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
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


def load_config() -> dict:
    """config.yml을 로드하고, 없으면 기본값으로 생성한다."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        # 기본값에 사용자 설정 머지 (1단계 깊이)
        merged = {}
        for section, defaults in _defaults.items():
            merged[section] = {**defaults, **(user_cfg.get(section) or {})}
        # top-level 키 보존 (admin_server_url 등)
        for key, val in user_cfg.items():
            if key not in merged:
                merged[key] = val
        return merged

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
