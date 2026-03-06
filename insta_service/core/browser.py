import os
import sys
import time
import threading
import tempfile
import undetected_chromedriver as uc
import chromedriver_autoinstaller

from insta_service.config import cfg, CHROME_PROFILES_DIR, BASE_DIR
from insta_service.core.proxy_manager import ProxyManager
from insta_service.utils.logger import log

# undetected_chromedriver는 chromedriver 바이너리를 패치하므로
# 동시에 두 개 이상 Chrome을 실행하면 경합 조건으로 크래시 발생.
# Lock으로 순차 실행을 보장한다.
_chrome_create_lock = threading.Lock()
_window_index = 0  # 창 배치 순번


def _find_chromedriver(cache_dir: str) -> str | None:
    """캐시 디렉터리에서 chromedriver 실행 파일을 찾는다."""
    import platform as _plat
    name = "chromedriver.exe" if _plat.system() == "Windows" else "chromedriver"
    for root, dirs, files in os.walk(cache_dir):
        if name in files:
            return os.path.join(root, name)
    return None


def _get_screen_size():
    """화면 해상도를 가져온다."""
    import platform as _plat
    try:
        if _plat.system() == "Windows":
            import ctypes
            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        elif _plat.system() == "Darwin":
            import subprocess
            result = subprocess.run(
                ["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(", ")
                if len(parts) == 4:
                    return int(parts[2]), int(parts[3])
    except Exception:
        pass
    return 1920, 1080


def _position_window(driver):
    """Chrome 창을 그리드 형태로 배치한다. 열리는 순서대로 타일링."""
    global _window_index
    try:
        screen_w, screen_h = _get_screen_size()
        # 2열 그리드 (계정이 4개 이상이면 2x2, 아니면 2x1)
        cols = 2
        rows = 2
        w = screen_w // cols
        h = screen_h // rows

        idx = _window_index % (cols * rows)
        col = idx % cols
        row = idx // cols

        x = col * w
        y = row * h

        driver.set_window_position(x, y)
        driver.set_window_size(w, h)
        _window_index += 1
        log.info(f"Chrome 창 배치: ({col},{row}) - {w}x{h} at ({x},{y})")
    except Exception as e:
        log.debug(f"Chrome 창 배치 실패 (무시): {e}")


def rearrange_windows(drivers: dict):
    """열려 있는 Chrome 창들을 그리드로 재배치한다. drivers: {account_id: driver}"""
    global _window_index
    _window_index = 0
    alive = [(aid, d) for aid, d in drivers.items() if d and is_driver_alive(d)]
    for _, driver in alive:
        _position_window(driver)


def create_chrome_driver(
    profile_name: str = "default",
    proxy: dict | None = None,
    headless: bool | None = None,
) -> uc.Chrome:
    """
    undetected-chromedriver 인스턴스를 생성한다.
    - profile_name: 계정별 Chrome 프로필 디렉터리 이름
    - proxy: {"ip","port","username","password"} 형태의 프록시 정보
    - headless: None이면 config.yml 설정 따름
    """
    with _chrome_create_lock:
        # PyInstaller 번들에서는 chromedriver를 exe 옆 data 폴더에 저장
        if getattr(sys, 'frozen', False):
            driver_cache_dir = str(BASE_DIR / "data" / "chromedriver")
            os.makedirs(driver_cache_dir, exist_ok=True)
            os.environ["UC_DRIVER_CACHE_DIR"] = driver_cache_dir
            try:
                chromedriver_autoinstaller.install(path=driver_cache_dir)
            except Exception as e:
                log.warning(f"chromedriver 자동설치 실패 (무시): {e}")
        else:
            chromedriver_autoinstaller.install()

        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--no-first-run")
        options.add_argument("--no-service-autorun")
        options.add_argument("--password-store=basic")

        # Chrome 바이너리
        chrome_bin = cfg["chrome"]["binary_path"]
        if os.path.exists(chrome_bin):
            options.binary_location = chrome_bin
        else:
            log.warning(f"Chrome 바이너리를 찾을 수 없습니다: {chrome_bin}")

        # 프로필 디렉터리 (영구 유지 — 세션 보존)
        profile_dir = CHROME_PROFILES_DIR / profile_name
        profile_dir.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir}")

        # 프록시 설정
        if proxy:
            proxy_str = ProxyManager.format_for_chrome(proxy)
            options.add_argument(f"--proxy-server=http://{proxy_str}")
            ext_path = ProxyManager.create_proxy_auth_extension(proxy)
            if ext_path:
                options.add_extension(ext_path)
            log.info(f"프록시 적용: {proxy['ip']}:{proxy['port']}")

        # Chrome 버전 감지
        detected_major = None
        try:
            ver = chromedriver_autoinstaller.get_chrome_version()
            detected_major = int(ver.split(".")[0]) if ver else None
            log.info(f"Chrome 버전 감지: {ver}")
        except Exception:
            pass

        use_headless = headless if headless is not None else cfg["chrome"]["headless"]

        chrome_kwargs = {
            "options": options,
            "headless": use_headless,
            "use_subprocess": True,
        }
        if detected_major:
            chrome_kwargs["version_main"] = detected_major

        # PyInstaller에서 driver_executable_path 지정
        if getattr(sys, 'frozen', False):
            chrome_kwargs["driver_executable_path"] = _find_chromedriver(driver_cache_dir)

        driver = uc.Chrome(**chrome_kwargs)

        # 창 위치/크기 자동 배치
        _position_window(driver)

        log.info(f"Chrome 브라우저 실행 완료 (프로필: {profile_name})")
        return driver


def check_login(driver: uc.Chrome) -> bool:
    """인스타그램 로그인 상태를 확인한다. sessionid 쿠키 기반으로 정확하게 판단."""
    try:
        current = driver.current_url
        # 인스타그램이 아닌 페이지면 인스타로 이동
        if "instagram.com" not in current:
            driver.get("https://www.instagram.com/")
            time.sleep(3)

        # URL에 login이 포함되면 미로그인
        current = driver.current_url
        if "login" in current or "accounts/login" in current:
            return False

        # sessionid 쿠키 확인 (가장 확실한 방법)
        cookies = driver.get_cookies()
        for cookie in cookies:
            if cookie.get("name") == "sessionid" and cookie.get("value"):
                return True

        return False
    except Exception as e:
        log.error(f"로그인 상태 확인 실패: {e}")
        return False


def check_login_safe(driver: uc.Chrome) -> bool:
    """로그인 상태를 확인한다. sessionid 쿠키가 있어야만 로그인으로 판단."""
    try:
        current = driver.current_url
        if "instagram.com" not in current:
            return False
        if "login" in current or "accounts/login" in current:
            return False
        # sessionid 쿠키가 있어야만 로그인 상태로 판단
        cookies = driver.get_cookies()
        for cookie in cookies:
            if cookie.get("name") == "sessionid" and cookie.get("value"):
                return True
        return False
    except Exception:
        return False


def navigate_to_instagram(driver: uc.Chrome):
    """인스타그램 메인 페이지로 이동한다."""
    try:
        driver.get("https://www.instagram.com/")
        time.sleep(3)
    except Exception as e:
        log.error(f"인스타그램 이동 실패: {e}")


def wait_for_manual_login(driver: uc.Chrome, check_interval: float = 3.0, timeout: float = 300.0) -> bool:
    """
    사용자가 수동으로 로그인할 때까지 대기한다.
    sessionid 쿠키가 생성되면 로그인 성공으로 판단.
    """
    elapsed = 0.0
    while elapsed < timeout:
        try:
            current_url = driver.current_url
            if "instagram.com" in current_url and "login" not in current_url and "accounts/login" not in current_url:
                cookies = driver.get_cookies()
                has_session = any(c.get("name") == "sessionid" and c.get("value") for c in cookies)
                if has_session:
                    log.info("로그인 성공! 세션이 저장되었습니다.")
                    return True
        except Exception:
            pass
        time.sleep(check_interval)
        elapsed += check_interval

    log.warning("로그인 대기 시간 초과")
    return False


def detect_action_block(driver: uc.Chrome) -> str | None:
    """
    인스타그램 차단/블록 상태를 감지한다.
    반환: "action_blocked", "challenge", "login_required", None (정상)
    """
    try:
        page_source = driver.page_source.lower()
        current_url = driver.current_url.lower()

        # Action Blocked 감지
        if "action blocked" in page_source or "try again later" in page_source:
            return "action_blocked"

        # Challenge (보안 인증) 감지 — URL에 /challenge/ 경로가 있을 때만
        if "/challenge/" in current_url:
            return "challenge"

        # 로그인 리다이렉트 감지
        if "accounts/login" in current_url:
            return "login_required"

        return None
    except Exception:
        return None


def is_driver_alive(driver: uc.Chrome) -> bool:
    """Chrome 드라이버가 살아있는지 확인한다."""
    try:
        _ = driver.title
        return True
    except Exception:
        return False


def close_driver(driver: uc.Chrome):
    """Chrome 드라이버를 안전하게 종료한다."""
    try:
        driver.quit()
        log.info("Chrome 브라우저 종료")
    except Exception as e:
        log.debug(f"Chrome 종료 중 오류 (무시): {e}")
