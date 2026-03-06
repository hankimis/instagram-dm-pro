"""전역 상태 관리 (스레드 안전) 및 공통 상수."""
import threading

# ── 전역 상태 (스레드 안전) ──
_state_lock = threading.Lock()
_state = {
    "drivers": {},       # account_id -> driver
    "crawlers": {},      # account_id -> HashtagCrawler
    "login_status": {},  # account_id -> bool | "checking"
    "licensed": False,
    "license_info": None,
    "_session_checked": set(),  # 이번 실행에서 세션 확인 완료된 account_id
    "_manual_login_pending": set(),  # 수동 로그인 요청 중인 account_id
}


def get_state(key, sub_key=None, default=None):
    """스레드 안전하게 _state 값을 읽는다."""
    with _state_lock:
        val = _state.get(key, default)
        if sub_key is not None and isinstance(val, dict):
            return val.get(sub_key, default)
        return val


def set_state(key, value=None, sub_key=None):
    """스레드 안전하게 _state 값을 설정한다."""
    with _state_lock:
        if sub_key is not None:
            if key not in _state:
                _state[key] = {}
            _state[key][sub_key] = value
        else:
            _state[key] = value


def pop_state(key, sub_key=None, default=None):
    """스레드 안전하게 _state에서 값을 제거하고 반환한다."""
    with _state_lock:
        if sub_key is not None:
            return _state.get(key, {}).pop(sub_key, default)
        return _state.pop(key, default)


# ── 색상 팔레트 ──
PRIMARY = "#6366f1"      # indigo-500
PRIMARY_DARK = "#4f46e5"  # indigo-600
SIDEBAR_BG = "#1e1b4b"   # indigo-950
SIDEBAR_TEXT = "#c7d2fe"  # indigo-200
PAGE_BG = "#f8fafc"       # slate-50


def get_plan_limits() -> dict:
    lic = get_state("license_info") or {}
    return {
        "plan": lic.get("plan", "basic"),
        "max_crawl_accounts": lic.get("max_crawl_accounts", 1),
        "max_dm_accounts": lic.get("max_dm_accounts", 1),
        "max_daily_dm": lic.get("max_daily_dm", 50),
        "max_hashtags": lic.get("max_hashtags", 5),
        "can_schedule": lic.get("can_schedule", False),
        "can_analyze": lic.get("can_analyze", False),
        "can_export": lic.get("can_export", False),
    }
