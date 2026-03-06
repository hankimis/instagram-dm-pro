"""대시보드 엔트리포인트.

각 페이지는 pages/ 하위 모듈에서 @ui.page 데코레이터로 등록된다.
이 파일은 모든 페이지 모듈을 임포트하여 라우트를 등록하고,
앱 종료 훅과 서버 실행 로직만 담당한다.
"""

import sys

from nicegui import ui, app

from insta_service.db.models import init_db
from insta_service.core.browser import close_driver
from insta_service.core.proxy_manager import load_proxies_from_file
from insta_service.config import cfg as _cfg_ref
from insta_service.utils.logger import log

# ── 전역 상태 ──
from insta_service.ui.state import _state, _state_lock

# ── 페이지 등록 (import 시 @ui.page 데코레이터가 실행됨) ──
import insta_service.ui.pages.splash        # noqa: F401  (/,  /activate)
import insta_service.ui.pages.dashboard_main # noqa: F401  (/dashboard)
import insta_service.ui.pages.accounts      # noqa: F401  (/accounts)
import insta_service.ui.pages.crawl         # noqa: F401  (/crawl)
import insta_service.ui.pages.users         # noqa: F401  (/users)
import insta_service.ui.pages.dm            # noqa: F401  (/dm)
import insta_service.ui.pages.settings      # noqa: F401  (/settings)


def _graceful_shutdown():
    """앱 종료 시 모든 리소스를 안전하게 정리한다."""
    log.info("그레이스풀 셔다운 시작...")

    # 크롤러 취소
    with _state_lock:
        for aid, crawler in list(_state.get("crawlers", {}).items()):
            try:
                crawler.cancel()
                log.info(f"크롤러 취소: account_id={aid}")
            except Exception as e:
                log.debug(f"크롤러 취소 실패 (account_id={aid}): {e}")
        _state["crawlers"] = {}

    # Chrome 드라이버 종료
    with _state_lock:
        for aid, driver in list(_state.get("drivers", {}).items()):
            try:
                close_driver(driver)
                log.info(f"Chrome 종료: account_id={aid}")
            except Exception as e:
                log.debug(f"Chrome 종료 실패 (account_id={aid}): {e}")
        _state["drivers"] = {}
        _state["login_status"] = {}

    # APScheduler 종료
    try:
        from insta_service.core.scheduler import shutdown_scheduler
        shutdown_scheduler()
    except Exception as e:
        log.debug(f"스케줄러 종료 실패: {e}")

    log.info("그레이스풀 셔다운 완료")


def run_dashboard():
    """대시보드 서버를 실행한다."""
    from insta_service.config import cfg, DM_IMAGES_DIR

    init_db()
    load_proxies_from_file()

    # 종료 훅 등록
    app.on_shutdown(_graceful_shutdown)

    # 정적 파일 서빙
    app.add_static_files("/dm_images", str(DM_IMAGES_DIR))
    from insta_service.config import BASE_DIR as _base
    _assets_dir = _base / "assets"
    if _assets_dir.exists():
        app.add_static_files("/assets", str(_assets_dir))

    # PyInstaller frozen 환경에서는 127.0.0.1로 바인딩
    host = cfg["server"]["host"]
    if getattr(sys, 'frozen', False) and host == "0.0.0.0":
        host = "127.0.0.1"

    # pywebview가 있으면 네이티브 윈도우, 없으면 브라우저
    try:
        import webview  # noqa: F401
        use_native = True
    except ImportError:
        use_native = False

    mode = "네이티브" if use_native else "브라우저"
    log.info(f"대시보드 서버 시작 ({mode}): http://{host}:{cfg['server']['port']}")
    try:
        ui.run(
            title="Instagram DM Pro",
            host=host,
            port=cfg["server"]["port"],
            reload=False,
            native=use_native,
            show=not use_native,
            window_size=(1280, 800),
        )
    except Exception as e:
        log.error(f"대시보드 서버 실행 실패: {e}")
        import traceback
        log.error(traceback.format_exc())
