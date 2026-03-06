import asyncio
import os
import re as _re
import threading
from datetime import datetime

from nicegui import ui, app

from insta_service.db import repository as repo
from insta_service.db.models import init_db
from insta_service.core.browser import (
    create_chrome_driver, check_login, check_login_safe,
    wait_for_manual_login, navigate_to_instagram, close_driver,
    is_driver_alive, rearrange_windows,
)
from insta_service.core.crawler import HashtagCrawler
from insta_service.core.analyzer import UserAnalyzer
from insta_service.core.dm_sender import DmSender
from insta_service.core.proxy_manager import proxy_manager, load_proxies_from_file
from insta_service.core.account_manager import register_account, get_accounts, get_profile_path
from insta_service.license.validator import license_validator, APP_VERSION
from insta_service.config import cfg as _cfg_ref, save_config, CONFIG_PATH
from insta_service.utils.logger import log, get_log_buffer, LOG_DIR
from insta_service.utils.export import export_users_excel, export_users_csv
from insta_service.utils.backup import backup_database

# ── 전역 상태 (스레드 안전) ──
_state_lock = threading.Lock()
_state = {
    "drivers": {},       # account_id -> driver
    "crawlers": {},      # account_id -> HashtagCrawler
    "login_status": {},  # account_id -> bool | "checking"
    "licensed": False,
    "license_info": None,
    "_session_checked": set(),  # 이번 실행에서 세션 확인 완료된 account_id
}


def _get_state(key, sub_key=None, default=None):
    """스레드 안전하게 _state 값을 읽는다."""
    with _state_lock:
        val = _state.get(key, default)
        if sub_key is not None and isinstance(val, dict):
            return val.get(sub_key, default)
        return val


def _set_state(key, value=None, sub_key=None):
    """스레드 안전하게 _state 값을 설정한다."""
    with _state_lock:
        if sub_key is not None:
            if key not in _state:
                _state[key] = {}
            _state[key][sub_key] = value
        else:
            _state[key] = value


def _pop_state(key, sub_key=None, default=None):
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


def _get_plan_limits() -> dict:
    lic = _get_state("license_info") or {}
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


# =====================================================================
#  라이선스 인증 페이지
# =====================================================================

@ui.page("/")
def index_page():
    result = license_validator.verify()
    if result.get("ok"):
        _set_state("licensed", True)
        _set_state("license_info", result)
        license_validator.start_heartbeat()
        ui.navigate.to("/dashboard")
    else:
        ui.navigate.to("/activate")


@ui.page("/activate")
def activate_page():
    ui.colors(primary=PRIMARY)
    with ui.column().classes("w-full items-center justify-center min-h-screen"):
        with ui.card().classes("w-[420px] p-10 shadow-xl rounded-2xl"):
            with ui.column().classes("w-full items-center gap-1 mb-8"):
                ui.icon("camera_alt", size="48px").classes("text-indigo-500")
                ui.label("Instagram Service").classes("text-2xl font-bold text-gray-800")
                ui.label("라이선스를 활성화하세요").classes("text-sm text-gray-400")

            key_input = ui.input(
                "라이선스 키",
                placeholder="XXXX-XXXX-XXXX-XXXX",
            ).classes("w-full").props('outlined dense')
            status_label = ui.label("").classes("text-sm w-full text-center mt-2")

            async def do_activate():
                key = key_input.value.strip()
                if not key:
                    status_label.text = "라이선스 키를 입력해주세요."
                    status_label.classes(replace="text-red-500 text-sm w-full text-center mt-2")
                    return
                status_label.text = "인증 중..."
                status_label.classes(replace="text-blue-500 text-sm w-full text-center mt-2")
                result = license_validator.activate(key)
                if result.get("ok"):
                    plan = result.get("plan", "basic").upper()
                    status_label.text = f"활성화 완료! ({result.get('company_name', '')} - {plan})"
                    status_label.classes(replace="text-green-600 text-sm w-full text-center mt-2")
                    _set_state("licensed", True)
                    _set_state("license_info", result)
                    await asyncio.sleep(1)
                    ui.navigate.to("/dashboard")
                else:
                    status_label.text = result.get("error", "인증 실패")
                    status_label.classes(replace="text-red-500 text-sm w-full text-center mt-2")

            ui.button("활성화", on_click=do_activate).classes("w-full mt-4").props("unelevated size=lg")


# =====================================================================
#  레이아웃: 사이드바 + 컨텐츠
# =====================================================================

def _layout(current: str = "dashboard"):
    """공통 사이드바 레이아웃을 구성한다."""
    ui.colors(primary=PRIMARY)

    # CSS 오버라이드
    ui.add_head_html(f"""
    <style>
        body {{ background: {PAGE_BG}; }}
        .q-drawer {{ background: {SIDEBAR_BG} !important; }}
        .q-drawer__content {{
            display: flex !important;
            flex-direction: column !important;
            height: 100% !important;
        }}
        .q-drawer .q-icon {{ color: {SIDEBAR_TEXT} !important; }}
        .nicegui-content {{ padding: 0 !important; }}
        /* 메인 컨텐츠가 전체 너비를 채우도록 */
        .q-page {{ width: 100%; }}
        .nicegui-content > * {{ width: 100%; max-width: 100%; }}
        .q-page-container {{ width: 100%; }}
        .sidebar-item {{
            color: {SIDEBAR_TEXT};
            border-radius: 8px;
            margin: 2px 8px;
            transition: all 0.15s;
            cursor: pointer;
        }}
        .sidebar-item .q-icon {{
            color: {SIDEBAR_TEXT} !important;
        }}
        .sidebar-item:hover {{
            background: rgba(255,255,255,0.08);
        }}
        .sidebar-item.active {{
            background: rgba(99,102,241,0.3);
            color: #fff;
            font-weight: 600;
        }}
        .sidebar-item.active .q-icon {{
            color: #fff !important;
        }}
        .stat-card {{
            background: #fff;
            border-radius: 12px;
            padding: 20px 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            transition: box-shadow 0.2s;
            flex: 1 1 0%;
            min-width: 0;
        }}
        .stat-card:hover {{
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        .content-card {{
            background: #fff;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            width: 100%;
            min-width: 0;
        }}
        .content-card.flex-1 {{
            flex: 1 1 0%;
            min-width: 0;
        }}
        /* 테이블 전체 너비 */
        .q-table {{ width: 100% !important; }}
        .q-table__container {{ width: 100% !important; }}
        .q-table .q-table__top, .q-table .q-table__bottom {{
            width: 100%;
        }}
        /* Quasar 텍스트 영역 전체 너비 */
        .q-textarea {{ width: 100% !important; }}
        .q-field__control {{ width: 100% !important; }}
        /* 모달/다이얼로그 항상 뷰포트 기준 중앙 정렬 (사이드바 무시) */
        .q-dialog {{
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            right: 0 !important;
            bottom: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            z-index: 6000 !important;
            margin: 0 !important;
            padding: 0 !important;
        }}
        .q-dialog__inner {{
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            right: 0 !important;
            bottom: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            max-width: 100vw !important;
            max-height: 100vh !important;
            margin: 0 !important;
            padding: 24px !important;
        }}
        .q-dialog__inner > .q-card,
        .q-dialog__inner > .nicegui-card {{
            margin: 0 auto !important;
            max-width: 90vw !important;
            max-height: 90vh !important;
            overflow: auto !important;
            position: relative !important;
        }}
        /* 다이얼로그 백드롭도 뷰포트 전체 커버 */
        .q-dialog__backdrop {{
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
        }}
    </style>
    """)

    lic = _get_state("license_info") or {}
    limits = _get_plan_limits()
    plan_name = limits["plan"].upper()

    menu_items = [
        ("dashboard", "space_dashboard", "대시보드"),
        ("accounts", "manage_accounts", "계정 관리"),
        ("crawl", "tag", "크롤링"),
        ("users", "group", "유저 관리"),
        ("dm", "send", "DM 발송"),
        ("settings", "settings", "설정"),
    ]

    with ui.left_drawer(value=True, fixed=True).classes("p-0 flex flex-col").props("width=240 bordered=false").style("display:flex;flex-direction:column"):
        # 로고 영역
        with ui.column().classes("w-full items-center pt-6 pb-4 gap-1"):
            ui.icon("camera_alt", size="32px").classes("text-indigo-300")
            ui.label("Instagram Service").classes("text-white text-base font-bold")
            ui.label(f"v{APP_VERSION}").classes("text-indigo-400 text-xs")

        ui.separator().classes("bg-white/10 mx-4")

        # 메뉴
        with ui.column().classes("w-full mt-2 gap-0"):
            for route, icon, label in menu_items:
                is_active = route == current
                cls = "sidebar-item active" if is_active else "sidebar-item"
                with ui.element("div").classes(cls).on(
                    "click", lambda _, r=route: ui.navigate.to(f"/{r}")
                ):
                    with ui.row().classes("items-center gap-3 py-2.5 px-4"):
                        ui.icon(icon, size="20px")
                        ui.label(label).classes("text-sm")

        # 스페이서 (메뉴와 하단 사이 빈 공간)
        ui.space()

        # 하단 플랜 정보
        with ui.column().classes("w-full p-4 mt-auto"):
            ui.separator().classes("bg-white/10 mb-3")
            if lic.get("company_name"):
                ui.label(lic["company_name"]).classes("text-white text-xs font-semibold truncate")
            with ui.row().classes("items-center gap-2"):
                plan_colors = {"BASIC": "bg-blue-500", "PRO": "bg-purple-500", "ENTERPRISE": "bg-amber-500"}
                badge_cls = plan_colors.get(plan_name, "bg-gray-500")
                ui.label(plan_name).classes(f"text-[10px] text-white px-2 py-0.5 rounded-full {badge_cls}")
                if lic.get("expires_at"):
                    try:
                        expires = datetime.fromisoformat(lic["expires_at"])
                        days_left = (expires - datetime.utcnow()).days
                        color = "text-red-400" if days_left <= 30 else "text-indigo-400"
                        ui.label(f"D-{days_left}").classes(f"text-xs {color}")
                    except Exception:
                        pass

    # 상단 헤더바
    with ui.header().classes("bg-white shadow-sm h-14 px-6").props("elevated=false"):
        title = next((label for route, icon, label in menu_items if route == current), "")
        ui.label(title).classes("text-gray-800 text-lg font-semibold")
        ui.space()


# =====================================================================
#  대시보드
# =====================================================================

@ui.page("/dashboard")
def dashboard_page():
    if not _check_license():
        return
    _layout("dashboard")
    limits = _get_plan_limits()
    lic = _get_state("license_info") or {}

    with ui.column().style("width:100%;padding:24px;gap:24px"):
        # 버전 알림
        update_info = license_validator.check_update()
        if update_info:
            with ui.element("div").classes(
                "w-full bg-amber-50 border border-amber-200 rounded-xl px-5 py-3 flex items-center gap-3"
            ):
                ui.icon("info", size="20px").classes("text-amber-600")
                ui.label(update_info.get("message", "")).classes("text-amber-800 text-sm")

        # 통계 카드
        with ui.row().style("width:100%;gap:16px;flex-wrap:wrap"):
            user_count = repo.get_user_count()
            _stat_card("수집된 유저", user_count, "group", "#6366f1")

            hashtag_stats = repo.get_hashtag_stats()
            _stat_card("해시태그", len(hashtag_stats), "tag", "#10b981")

            dm_stats = repo.get_dm_stats()
            _stat_card("DM 발송", dm_stats["sent"], "send", "#8b5cf6")

            accounts = get_accounts()
            active = sum(1 for a in accounts if a["is_active"])
            _stat_card("활성 계정", active, "account_circle", "#f59e0b")

        # 플랜 요약
        with ui.element("div").classes("content-card"):
            with ui.row().classes("items-center gap-3 mb-3"):
                ui.label("플랜 정보").classes("text-base font-semibold text-gray-700")
                plan_colors = {"basic": "bg-blue-100 text-blue-700", "pro": "bg-purple-100 text-purple-700", "enterprise": "bg-amber-100 text-amber-700"}
                pcls = plan_colors.get(limits["plan"], "bg-gray-100 text-gray-700")
                ui.label(limits["plan"].upper()).classes(f"text-xs px-2.5 py-0.5 rounded-full font-bold {pcls}")

            with ui.row().classes("gap-6 text-sm text-gray-500"):
                ui.label(f"크롤링 계정 {limits['max_crawl_accounts']}개")
                ui.label(f"DM 계정 {limits['max_dm_accounts']}개")
                dm_txt = "무제한" if limits["max_daily_dm"] >= 9999 else f"{limits['max_daily_dm']}건"
                ui.label(f"일일 DM {dm_txt}")
                ht_txt = "무제한" if limits["max_hashtags"] >= 9999 else f"{limits['max_hashtags']}개"
                ui.label(f"해시태그 {ht_txt}")

            with ui.row().classes("mt-2 gap-2"):
                for feat, enabled in [("분석", limits["can_analyze"]), ("내보내기", limits["can_export"]), ("스케줄", limits["can_schedule"])]:
                    if enabled:
                        ui.label(feat).classes("text-xs bg-green-50 text-green-600 px-2 py-0.5 rounded-full")
                    else:
                        ui.label(feat).classes("text-xs bg-gray-100 text-gray-400 px-2 py-0.5 rounded-full line-through")

        # 최근 크롤링 / 해시태그 통계 (2열)
        with ui.row().style("width:100%;gap:16px;flex-wrap:wrap"):
            with ui.element("div").classes("content-card flex-1"):
                ui.label("최근 크롤링").classes("text-base font-semibold text-gray-700 mb-3")
                jobs = repo.get_crawl_jobs(limit=8)
                if jobs:
                    columns = [
                        {"name": "hashtag", "label": "해시태그", "field": "hashtag", "align": "left"},
                        {"name": "target", "label": "목표", "field": "target_count", "align": "center"},
                        {"name": "collected", "label": "수집", "field": "collected_count", "align": "center"},
                        {"name": "status", "label": "상태", "field": "status", "align": "center"},
                    ]
                    ui.table(columns=columns, rows=jobs).classes("w-full").props("flat dense")
                else:
                    ui.label("아직 크롤링 작업이 없습니다.").classes("text-gray-400 text-sm")

            with ui.element("div").classes("content-card flex-1"):
                ui.label("해시태그별 수집").classes("text-base font-semibold text-gray-700 mb-3")
                if hashtag_stats:
                    columns = [
                        {"name": "hashtag", "label": "해시태그", "field": "hashtag", "align": "left"},
                        {"name": "count", "label": "수집 수", "field": "count", "align": "center"},
                    ]
                    ui.table(columns=columns, rows=hashtag_stats[:10]).classes("w-full").props("flat dense")
                else:
                    ui.label("데이터 없음").classes("text-gray-400 text-sm")

        # 실시간 로그
        with ui.element("div").classes("content-card"):
            ui.label("실시간 로그").classes("text-base font-semibold text-gray-700 mb-3")
            log_area = ui.textarea().classes(
                "font-mono text-xs rounded-lg"
            ).style(
                "width:100%;background:#f9fafb;color:#374151;border:1px solid #e5e7eb"
            ).props("readonly rows=8")

            def refresh_log():
                logs = get_log_buffer()
                log_area.value = "\n".join(logs[-50:])

            ui.timer(2.0, refresh_log)


# =====================================================================
#  계정 관리 (수동 로그인 워크플로우)
# =====================================================================

@ui.page("/accounts")
def accounts_page():
    if not _check_license():
        return
    _layout("accounts")
    limits = _get_plan_limits()

    with ui.column().style("width:100%;padding:24px;gap:24px"):
        # 계정 등록
        with ui.element("div").classes("content-card"):
            ui.label("계정 등록").classes("text-base font-semibold text-gray-700 mb-4")

            crawl_accounts = get_accounts("crawl")
            dm_accounts_list = get_accounts("dm")
            with ui.row().classes("gap-4 text-sm text-gray-500 mb-4"):
                ui.label(f"크롤링 계정: {len(crawl_accounts)} / {limits['max_crawl_accounts']}개")
                ui.label(f"DM 계정: {len(dm_accounts_list)} / {limits['max_dm_accounts']}개")

            with ui.row().classes("w-full gap-3 items-end"):
                acc_user = ui.input("인스타 아이디").props("outlined dense").classes("flex-1")
                acc_pass = ui.input("비밀번호 (선택)", password=True).props("outlined dense").classes("flex-1")
                acc_type = ui.select(
                    {"crawl": "크롤링용", "dm": "DM발송용", "both": "크롤링+DM"},
                    value="crawl", label="용도"
                ).props("outlined dense").classes("w-40")
                proxies = proxy_manager.get_all()
                proxy_options = {0: "프록시 없음"} | {p["id"]: f"{p['ip']}:{p['port']}" for p in proxies}
                acc_proxy = ui.select(proxy_options, value=0, label="프록시").props("outlined dense").classes("w-44")

                def add_account():
                    if not acc_user.value:
                        ui.notify("아이디를 입력해주세요.", type="warning")
                        return
                    selected_type = acc_type.value
                    # 한도 체크: both는 crawl + dm 양쪽 모두 체크
                    if selected_type in ("crawl", "both"):
                        if len(get_accounts("crawl")) >= limits["max_crawl_accounts"]:
                            ui.notify(f"크롤링 계정 한도 초과! (최대 {limits['max_crawl_accounts']}개)", type="negative")
                            return
                    if selected_type in ("dm", "both"):
                        if len(get_accounts("dm")) >= limits["max_dm_accounts"]:
                            ui.notify(f"DM 계정 한도 초과! (최대 {limits['max_dm_accounts']}개)", type="negative")
                            return
                    try:
                        password = acc_pass.value or "manual_login"
                        proxy_id = acc_proxy.value if acc_proxy.value else None
                        register_account(acc_user.value, password, selected_type, proxy_id)
                        ui.notify(f"@{acc_user.value} 등록 완료!", type="positive")
                        acc_user.value = ""
                        acc_pass.value = ""
                        load_accounts()
                    except Exception as e:
                        ui.notify(f"등록 실패: {e}", type="negative")

                ui.button("추가", on_click=add_account, icon="add").props("unelevated dense")

        # 등록된 계정 목록 + 로그인 관리
        with ui.element("div").classes("content-card"):
            with ui.row().classes("items-center gap-3 mb-4"):
                ui.label("등록된 계정").classes("text-base font-semibold text-gray-700")
                ui.label("세션은 자동 저장됩니다. 프로그램 시작 시 저장된 세션을 자동으로 확인합니다.").classes(
                    "text-xs text-gray-400"
                )

            # 선택 상태
            selected_ids: set[int] = set()
            select_all_cb = {"ref": None}

            # 일괄 작업 툴바
            bulk_toolbar = ui.row().classes("w-full items-center gap-3 mb-3")

            def _update_toolbar():
                bulk_toolbar.clear()
                with bulk_toolbar:
                    cb = ui.checkbox("전체 선택", on_change=_toggle_select_all).props("dense")
                    accs = get_accounts()
                    all_ids = {a["id"] for a in accs}
                    cb.value = bool(all_ids) and all_ids == selected_ids
                    select_all_cb["ref"] = cb

                    cnt = len(selected_ids)
                    # 창 정렬 버튼 (항상 표시)
                    ui.button(
                        "창 정렬", icon="grid_view",
                        on_click=lambda: rearrange_windows(_get_state("drivers") or {}),
                    ).props("flat dense color=grey-7 size=sm").tooltip("열린 Chrome 창을 격자로 정렬")

                    if cnt > 0:
                        ui.label(f"{cnt}개 선택").classes("text-sm text-indigo-600 font-semibold")
                        ui.button(
                            "용도 변경", icon="swap_horiz",
                            on_click=lambda: _open_bulk_type_modal(),
                        ).props("flat dense color=primary size=sm")
                        ui.button(
                            "선택 삭제", icon="delete",
                            on_click=lambda: _confirm_bulk_delete(),
                        ).props("flat dense color=red size=sm")

            def _toggle_select_all(e):
                accs = get_accounts()
                if e.value:
                    selected_ids.update(a["id"] for a in accs)
                else:
                    selected_ids.clear()
                load_accounts()

            def _toggle_account(aid: int, checked: bool):
                if checked:
                    selected_ids.add(aid)
                else:
                    selected_ids.discard(aid)
                _update_toolbar()

            # ── 일괄 용도 변경 모달 ──
            def _open_bulk_type_modal():
                dialog = ui.dialog().props("persistent")
                with dialog, ui.card().classes("w-80"):
                    ui.label("일괄 용도 변경").classes("text-base font-semibold text-gray-700 mb-2")
                    ui.label(f"{len(selected_ids)}개 계정의 용도를 변경합니다.").classes("text-sm text-gray-500 mb-3")
                    new_type = ui.select(
                        {"crawl": "크롤링용", "dm": "DM발송용", "both": "크롤링+DM"},
                        value="crawl", label="새 용도"
                    ).props("outlined dense").classes("w-full")

                    with ui.row().classes("w-full justify-end gap-2 mt-4"):
                        ui.button("취소", on_click=dialog.close).props("flat dense")

                        def apply_bulk_type():
                            for aid in list(selected_ids):
                                repo.update_account(aid, account_type=new_type.value)
                            ui.notify(f"{len(selected_ids)}개 계정 용도 변경 완료!", type="positive")
                            dialog.close()
                            load_accounts()

                        ui.button("변경", on_click=apply_bulk_type, icon="check").props("unelevated dense color=primary")
                dialog.open()

            # ── 일괄 삭제 확인 ──
            def _confirm_bulk_delete():
                dialog = ui.dialog().props("persistent")
                with dialog, ui.card().classes("w-80"):
                    ui.label("계정 삭제").classes("text-base font-semibold text-red-600 mb-2")
                    ui.label(f"{len(selected_ids)}개 계정을 삭제하시겠습니까?").classes("text-sm text-gray-600 mb-1")
                    ui.label("삭제된 계정은 복구할 수 없습니다.").classes("text-xs text-red-400 mb-3")

                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button("취소", on_click=dialog.close).props("flat dense")

                        def do_delete():
                            import shutil
                            from insta_service.config import CHROME_PROFILES_DIR
                            ids = list(selected_ids)
                            # 삭제 대상 계정 username 수집 (Chrome 프로필 정리용)
                            accs_to_del = [a for a in get_accounts() if a["id"] in set(ids)]
                            # 실행 중인 드라이버 종료
                            for aid in ids:
                                driver = _pop_state("drivers", sub_key=aid)
                                if driver:
                                    try:
                                        close_driver(driver)
                                    except Exception:
                                        pass
                                _pop_state("login_status", sub_key=aid)
                                _pop_state("crawlers", sub_key=aid)
                                with _state_lock:
                                    _state["_session_checked"].discard(aid)
                            repo.delete_accounts(ids)
                            # Chrome 프로필 디렉터리 정리
                            for acc in accs_to_del:
                                profile_dir = CHROME_PROFILES_DIR / acc["username"]
                                if profile_dir.exists():
                                    try:
                                        shutil.rmtree(profile_dir)
                                        log.info(f"Chrome 프로필 삭제: {acc['username']}")
                                    except Exception as e:
                                        log.warning(f"Chrome 프로필 삭제 실패 ({acc['username']}): {e}")
                            selected_ids.clear()
                            ui.notify(f"{len(ids)}개 계정 삭제 완료!", type="positive")
                            dialog.close()
                            load_accounts()

                        ui.button("삭제", on_click=do_delete, icon="delete").props("unelevated dense color=red")
                dialog.open()

            # ── 개별 수정 모달 ──
            def _open_edit_modal(acc: dict):
                proxies_list = proxy_manager.get_all()
                p_options = {0: "프록시 없음"} | {p["id"]: f"{p['ip']}:{p['port']}" for p in proxies_list}

                dialog = ui.dialog().props("persistent")
                with dialog, ui.card().classes("w-96"):
                    ui.label(f"@{acc['username']} 수정").classes("text-base font-semibold text-gray-700 mb-4")

                    edit_type = ui.select(
                        {"crawl": "크롤링용", "dm": "DM발송용", "both": "크롤링+DM"},
                        value=acc["account_type"], label="용도"
                    ).props("outlined dense").classes("w-full mb-3")

                    edit_proxy = ui.select(
                        p_options, value=acc.get("proxy_id") or 0, label="프록시"
                    ).props("outlined dense").classes("w-full mb-3")

                    edit_dm_limit = ui.number(
                        "일일 DM 한도", value=acc.get("daily_dm_limit", 30), min=1, max=500
                    ).props("outlined dense").classes("w-full mb-3")

                    edit_active = ui.switch("활성 상태", value=acc.get("is_active", True))

                    with ui.row().classes("w-full justify-end gap-2 mt-4"):
                        ui.button("취소", on_click=dialog.close).props("flat dense")

                        def save_edit():
                            proxy_val = edit_proxy.value if edit_proxy.value else None
                            repo.update_account(
                                acc["id"],
                                account_type=edit_type.value,
                                proxy_id=proxy_val,
                                daily_dm_limit=int(edit_dm_limit.value),
                                is_active=edit_active.value,
                            )
                            ui.notify(f"@{acc['username']} 수정 완료!", type="positive")
                            dialog.close()
                            load_accounts()

                        ui.button("저장", on_click=save_edit, icon="save").props("unelevated dense color=primary")
                dialog.open()

            accounts_container = ui.column().style("width:100%;gap:12px")

            def load_accounts():
                _update_toolbar()
                accounts_container.clear()
                with accounts_container:
                    accs = get_accounts()
                    if not accs:
                        ui.label("등록된 계정이 없습니다.").classes("text-gray-400 text-sm py-4 text-center")
                        return

                    for acc in accs:
                        aid = acc["id"]
                        is_logged_in = _get_state("login_status", sub_key=aid) is True
                        driver_running = _get_state("drivers", sub_key=aid) is not None

                        with ui.element("div").classes(
                            "w-full border rounded-xl p-4 flex items-center gap-4 "
                            + ("border-green-200 bg-green-50/50" if is_logged_in else "border-gray-200")
                        ):
                            # 체크박스
                            ui.checkbox(
                                "", value=aid in selected_ids,
                                on_change=lambda e, a=aid: _toggle_account(a, e.value),
                            ).props("dense")

                            # 아바타
                            ui.icon("account_circle", size="36px").classes(
                                "text-green-500" if is_logged_in else "text-gray-300"
                            )
                            # 계정 정보
                            with ui.column().classes("flex-1 gap-0"):
                                with ui.row().classes("items-center gap-2"):
                                    ui.label(f"@{acc['username']}").classes("font-semibold text-gray-800")
                                    type_colors = {
                                        "crawl": "bg-blue-50 text-blue-600",
                                        "dm": "bg-purple-50 text-purple-600",
                                        "both": "bg-indigo-50 text-indigo-600",
                                    }
                                    type_labels = {"crawl": "CRAWL", "dm": "DM", "both": "CRAWL+DM"}
                                    type_cls = type_colors.get(acc["account_type"], "bg-gray-50 text-gray-600")
                                    type_lbl = type_labels.get(acc["account_type"], acc["account_type"].upper())
                                    ui.label(type_lbl).classes(f"text-[10px] px-2 py-0.5 rounded-full {type_cls}")
                                    if not acc.get("is_active", True):
                                        ui.label("비활성").classes("text-[10px] px-2 py-0.5 rounded-full bg-red-50 text-red-500")
                                with ui.row().classes("gap-3 text-xs text-gray-400"):
                                    login_val = _get_state("login_status", sub_key=aid)
                                    if login_val is True:
                                        ui.label("로그인됨").classes("text-green-600 font-semibold")
                                    elif login_val == "checking":
                                        with ui.row().classes("items-center gap-1"):
                                            ui.spinner("dots", size="14px").classes("text-blue-500")
                                            ui.label("세션 확인 중...").classes("text-blue-500")
                                    elif driver_running:
                                        ui.label("Chrome 실행 중 - 로그인 대기").classes("text-amber-600")
                                    else:
                                        ui.label("로그인 필요").classes("text-gray-400")
                                    if acc.get("proxy_id"):
                                        ui.label(f"프록시: #{acc['proxy_id']}").classes("text-gray-400")
                                    ui.label(f"DM한도: {acc.get('daily_dm_limit', 30)}건").classes("text-gray-400")

                            # 액션 버튼
                            login_val = _get_state("login_status", sub_key=aid)
                            with ui.row().classes("gap-2"):
                                # 수정 버튼
                                ui.button(
                                    "", icon="edit",
                                    on_click=lambda a=acc: _open_edit_modal(a),
                                ).props("flat dense color=grey size=sm").tooltip("수정")

                                if login_val == "checking":
                                    ui.button(
                                        "확인 중...",
                                        icon="hourglass_empty",
                                    ).props("flat dense color=grey size=sm disable")
                                elif not driver_running:
                                    ui.button(
                                        "로그인",
                                        on_click=lambda a=acc: _start_manual_login(a, load_accounts),
                                        icon="login",
                                    ).props("unelevated dense color=primary size=sm")
                                else:
                                    if not is_logged_in:
                                        ui.button(
                                            "로그인 확인",
                                            on_click=lambda a=acc: _verify_login(a, load_accounts),
                                            icon="check_circle",
                                        ).props("unelevated dense color=green size=sm")
                                    else:
                                        ui.button(
                                            "확인됨",
                                            icon="check",
                                        ).props("flat dense color=green size=sm disable")

                                    ui.button(
                                        "",
                                        on_click=lambda a=acc: _close_chrome(a, load_accounts),
                                        icon="close",
                                    ).props("flat dense color=red size=sm").tooltip("Chrome 종료")

            load_accounts()

            # 세션 확인 상태 표시
            session_status_row = ui.row().classes("w-full items-center gap-3 mb-2")
            with session_status_row:
                session_status_label = ui.label("").classes("text-xs text-gray-400")

            def _on_session_check_update():
                """세션 확인 진행 상태를 업데이트한다."""
                accs = get_accounts()
                checking = sum(1 for a in accs if _get_state("login_status", sub_key=a["id"]) == "checking")
                if checking > 0:
                    session_status_label.text = f"세션 확인 중... ({checking}개 계정)"
                else:
                    logged = sum(1 for a in accs if _get_state("login_status", sub_key=a["id"]) is True)
                    session_status_label.text = f"로그인: {logged}/{len(accs)}개 계정"

            ui.timer(1.5, _on_session_check_update)

            def _recheck_all_sessions():
                with _state_lock:
                    _state["_session_checked"].clear()
                _auto_check_sessions(load_accounts)
                ui.notify("전체 세션 재확인을 시작합니다.", type="info")

            with session_status_row:
                ui.button("전체 세션 확인", on_click=_recheck_all_sessions, icon="sync").props("outline dense size=sm")

            # 프로그램 시작 후 첫 접근 시 모든 계정 세션 자동 확인
            _auto_check_sessions(load_accounts)

            # 로그인 상태 변경 자동 감지 (2초마다)
            _prev_status = {}

            def _auto_refresh():
                changed = False
                with _state_lock:
                    login_snapshot = dict(_state["login_status"])
                    driver_keys = set(_state["drivers"].keys())
                for aid, logged in login_snapshot.items():
                    if _prev_status.get(aid) != logged:
                        changed = True
                        _prev_status[aid] = logged
                # 드라이버 추가/삭제도 감지
                prev_keys = set(_prev_status.get("_drivers", set()))
                if driver_keys != prev_keys:
                    changed = True
                    _prev_status["_drivers"] = driver_keys
                if changed:
                    load_accounts()

            ui.timer(2.0, _auto_refresh)

            # Chrome 크래시 감지 (10초마다)
            def _check_driver_health():
                dead_aids = []
                with _state_lock:
                    for aid, driver in list(_state["drivers"].items()):
                        if not is_driver_alive(driver):
                            dead_aids.append(aid)
                if dead_aids:
                    for aid in dead_aids:
                        _pop_state("drivers", sub_key=aid)
                        _set_state("login_status", False, sub_key=aid)
                        _pop_state("crawlers", sub_key=aid)
                    accs_map = {a["id"]: a["username"] for a in get_accounts()}
                    names = ", ".join(f"@{accs_map.get(a, a)}" for a in dead_aids)
                    ui.notify(f"Chrome 크래시 감지: {names} - 다시 로그인해주세요.", type="warning")
                    load_accounts()

            ui.timer(10.0, _check_driver_health)


def _auto_check_sessions(reload_fn):
    """프로그램 시작 후 등록된 모든 계정의 세션을 백그라운드에서 자동 확인한다."""
    accs = get_accounts()
    for acc in accs:
        aid = acc["id"]
        # 이미 확인했거나 드라이버가 실행 중이면 스킵
        with _state_lock:
            if aid in _state["_session_checked"] or aid in _state["drivers"]:
                continue
            _state["_session_checked"].add(aid)
            _state["login_status"][aid] = "checking"

        def check_session(account=acc):
            account_id = account["id"]
            try:
                proxy_data = None
                if account.get("proxy_id"):
                    proxy_data = proxy_manager.get_by_id(account["proxy_id"])

                driver = create_chrome_driver(
                    profile_name=account["username"],
                    proxy=proxy_data,
                    headless=True,
                )

                navigate_to_instagram(driver)
                logged_in = check_login_safe(driver)

                if logged_in:
                    _set_state("login_status", True, sub_key=account_id)
                    close_driver(driver)
                    log.info(f"@{account['username']} 세션 유효 (자동 확인)")
                else:
                    _set_state("login_status", False, sub_key=account_id)
                    close_driver(driver)
                    log.info(f"@{account['username']} 세션 만료 - 로그인 필요")
            except Exception as e:
                log.debug(f"@{account['username']} 세션 확인 실패: {e}")
                _set_state("login_status", False, sub_key=account_id)

        threading.Thread(target=check_session, daemon=True).start()


def _start_manual_login(acc: dict, reload_fn):
    """Chrome을 실행하고, 자동 로그인(세션 캐시) 시도 후 실패 시 수동 로그인을 안내한다."""
    aid = acc["id"]
    ui.notify(f"@{acc['username']} Chrome 실행 중... 로그인 상태를 확인합니다.", type="info")

    def run():
        try:
            # 기존 드라이버가 있으면 종료
            old_driver = _pop_state("drivers", sub_key=aid)
            if old_driver:
                try:
                    close_driver(old_driver)
                except Exception:
                    pass
                import time as _time
                _time.sleep(2)  # 포트 해제 대기

            proxy_data = None
            if acc.get("proxy_id"):
                proxy_data = proxy_manager.get_by_id(acc["proxy_id"])

            driver = create_chrome_driver(profile_name=acc["username"], proxy=proxy_data)
            _set_state("drivers", driver, sub_key=aid)
            _set_state("login_status", False, sub_key=aid)

            # ── Step 1: 인스타그램으로 이동하여 기존 세션(쿠키)으로 자동 로그인 시도 ──
            log.info(f"@{acc['username']} 기존 세션으로 자동 로그인 시도 중...")
            navigate_to_instagram(driver)

            if check_login_safe(driver):
                _set_state("login_status", True, sub_key=aid)
                log.info(f"@{acc['username']} 자동 로그인 성공! (저장된 세션 사용)")
                return

            # ── Step 2: 자동 로그인 실패 → 로그인 페이지로 이동 + 수동 로그인 안내 ──
            log.info(
                f"@{acc['username']} 자동 로그인 실패. "
                f"Chrome 창에서 직접 인스타그램에 로그인해주세요. (5분 내 로그인 필요)"
            )
            # 로그인 페이지로 명시적 이동
            driver.get("https://www.instagram.com/accounts/login/")
            import time
            time.sleep(2)

            # ── Step 3: 백그라운드에서 로그인 완료 감지 (3초 간격, 5분 타임아웃) ──
            logged_in = wait_for_manual_login(driver, check_interval=3.0, timeout=300.0)
            _set_state("login_status", logged_in, sub_key=aid)

            if logged_in:
                log.info(f"@{acc['username']} 수동 로그인 성공! 세션이 저장되었습니다. 다음부터는 자동 로그인됩니다.")
            else:
                log.warning(f"@{acc['username']} 로그인 시간 초과. 다시 시도해주세요.")

        except Exception as e:
            log.error(f"Chrome 실행 오류: {e}")
            _set_state("login_status", False, sub_key=aid)

    threading.Thread(target=run, daemon=True).start()


def _verify_login(acc: dict, reload_fn):
    """현재 로그인 상태를 확인한다."""
    aid = acc["id"]
    driver = _get_state("drivers", sub_key=aid)
    if not driver:
        ui.notify("Chrome이 실행되지 않았습니다.", type="warning")
        return
    try:
        logged_in = check_login(driver)
        _set_state("login_status", logged_in, sub_key=aid)
        if logged_in:
            ui.notify(f"@{acc['username']} 로그인 확인됨!", type="positive")
        else:
            ui.notify(f"@{acc['username']} 아직 로그인되지 않았습니다.", type="warning")
        reload_fn()
    except Exception as e:
        ui.notify(f"확인 실패: {e}", type="negative")


def _close_chrome(acc: dict, reload_fn):
    """Chrome 드라이버를 종료한다."""
    aid = acc["id"]
    driver = _pop_state("drivers", sub_key=aid)
    if driver:
        try:
            close_driver(driver)
        except Exception:
            pass
    _pop_state("login_status", sub_key=aid)
    _pop_state("crawlers", sub_key=aid)
    ui.notify(f"@{acc['username']} Chrome 종료됨", type="info")
    reload_fn()


# =====================================================================
#  크롤링 페이지
# =====================================================================

@ui.page("/crawl")
def crawl_page():
    if not _check_license():
        return
    _layout("crawl")
    limits = _get_plan_limits()

    with ui.column().style("width:100%;padding:24px;gap:24px"):
        # 크롤링 설정
        with ui.element("div").classes("content-card"):
            ui.label("해시태그 크롤링").classes("text-base font-semibold text-gray-700 mb-1")

            used_hashtags = len(repo.get_hashtag_stats())
            max_ht = limits["max_hashtags"]
            ht_txt = "무제한" if max_ht >= 9999 else f"{max_ht}개"
            color = "text-red-500" if used_hashtags >= max_ht and max_ht < 9999 else "text-gray-400"
            ui.label(f"사용 중인 해시태그: {used_hashtags} / {ht_txt}").classes(f"text-xs {color} mb-4")

            with ui.row().classes("w-full gap-3 items-end"):
                hashtag_input = ui.input("해시태그", placeholder="예: 마케팅").props("outlined dense").classes("flex-1")
                count_input = ui.number("수집 수", value=50, min=1, max=1000).props("outlined dense").classes("w-28")

                # 로그인된 크롤링 계정만 표시
                crawl_accs = get_accounts("crawl")
                logged_in_options = {}
                not_logged_options = {}
                for a in crawl_accs:
                    if _get_state("login_status", sub_key=a["id"]) is True:
                        logged_in_options[a["id"]] = f"@{a['username']}"
                    else:
                        not_logged_options[a["id"]] = f"@{a['username']} (로그인 필요)"

                all_options = {**logged_in_options, **not_logged_options}
                account_select = ui.select(
                    all_options, label="크롤링 계정"
                ).props("outlined dense").classes("w-52")

            progress = ui.linear_progress(0).classes("w-full mt-4").props("rounded size=8px color=indigo-5")
            status_label = ui.label("").classes("mt-2 text-sm")

            def start_crawl():
                hashtag = hashtag_input.value.strip().lstrip("#")
                if not hashtag:
                    ui.notify("해시태그를 입력해주세요.", type="warning")
                    return
                if not account_select.value:
                    ui.notify("크롤링 계정을 선택해주세요.", type="warning")
                    return

                account_id = account_select.value

                # 로그인 상태 체크
                if _get_state("login_status", sub_key=account_id) is not True:
                    ui.notify("먼저 계정 관리에서 로그인해주세요.", type="negative")
                    return

                # 해시태그 수 제한 체크
                existing_hashtags = {h["hashtag"] for h in repo.get_hashtag_stats()}
                if hashtag not in existing_hashtags and len(existing_hashtags) >= limits["max_hashtags"] and limits["max_hashtags"] < 9999:
                    ui.notify(f"해시태그 한도 초과! (최대 {limits['max_hashtags']}개)", type="negative")
                    return

                target = int(count_input.value)
                acc = next((a for a in crawl_accs if a["id"] == account_id), None)

                status_label.text = "크롤링 준비 중..."
                progress.value = 0
                crawl_btn.disable()

                def run_in_thread():
                    try:
                        driver = _get_state("drivers", sub_key=account_id)

                        # driver가 없거나 죽었으면 자동으로 Chrome 실행
                        if not driver or not is_driver_alive(driver):
                            status_label.text = "Chrome 자동 실행 중..."
                            proxy_data = None
                            if acc.get("proxy_id"):
                                proxy_data = proxy_manager.get_by_id(acc["proxy_id"])
                            driver = create_chrome_driver(
                                profile_name=acc["username"], proxy=proxy_data
                            )
                            _set_state("drivers", driver, sub_key=account_id)
                            navigate_to_instagram(driver)
                            import time as _t
                            _t.sleep(2)

                        if not check_login(driver):
                            _set_state("login_status", False, sub_key=account_id)
                            status_label.text = "로그인이 만료되었습니다. 계정 관리에서 다시 로그인해주세요."
                            return

                        job_id = repo.create_crawl_job(hashtag, target, account_id)
                        crawler = HashtagCrawler(driver, account_id=account_id)
                        _set_state("crawlers", crawler, sub_key=account_id)

                        status_label.text = f"크롤링 진행 중... #{hashtag}"

                        def on_crawl_progress(collected, total, username):
                            progress.value = collected / total if total else 0
                            status_label.text = f"크롤링 중... #{hashtag} ({collected}/{total}) @{username}"

                        result = crawler.crawl(hashtag, target, job_id, on_progress=on_crawl_progress)

                        if crawler.blocked:
                            status_label.text = f"차단 감지! {len(result.collected)}명 수집 후 중단됨"
                            _set_state("login_status", False, sub_key=account_id)
                        else:
                            status_label.text = f"완료! {len(result.collected)}명 수집"
                        progress.value = 1.0

                    except Exception as e:
                        status_label.text = f"오류: {e}"
                        log.error(f"크롤링 오류: {e}")
                    finally:
                        crawl_btn.enable()

                threading.Thread(target=run_in_thread, daemon=True).start()

            def cancel_crawl():
                account_id = account_select.value
                crawler = _get_state("crawlers", sub_key=account_id) if account_id else None
                if crawler:
                    crawler.cancel()
                    status_label.text = "크롤링 취소 요청됨"
                    ui.notify("크롤링 취소 중...", type="info")

            with ui.row().classes("mt-4 gap-3 items-end"):
                crawl_btn = ui.button("크롤링 시작", on_click=start_crawl, icon="play_arrow").props("unelevated")
                ui.button("취소", on_click=cancel_crawl, icon="stop").props("outline color=red")

                if limits.get("can_schedule"):
                    ui.separator().props("vertical")
                    schedule_date = ui.input("예약 날짜", placeholder="YYYY-MM-DD").props("outlined dense").classes("w-36")
                    schedule_time = ui.input("시간", placeholder="HH:MM").props("outlined dense").classes("w-24")

                    def schedule_crawl_fn():
                        ht = hashtag_input.value.strip().lstrip("#")
                        if not ht or not account_select.value:
                            ui.notify("해시태그와 계정을 선택해주세요.", type="warning")
                            return
                        d = schedule_date.value.strip()
                        t = schedule_time.value.strip()
                        if not d or not t:
                            ui.notify("예약 날짜와 시간을 입력해주세요.", type="warning")
                            return
                        try:
                            run_at = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
                        except ValueError:
                            ui.notify("날짜/시간 형식: YYYY-MM-DD HH:MM", type="negative")
                            return
                        if run_at <= datetime.now():
                            ui.notify("미래 시간을 입력해주세요.", type="warning")
                            return

                        from insta_service.core.scheduler import schedule_crawl
                        target = int(count_input.value)
                        aid = account_select.value

                        def get_driver(account_id):
                            return _get_state("drivers", sub_key=account_id)

                        schedule_crawl(run_at, ht, target, aid, get_driver)
                        ui.notify(f"크롤링 예약 완료: #{ht} @ {d} {t}", type="positive")

                    ui.button("예약", on_click=schedule_crawl_fn, icon="schedule").props("outline dense")

        # 최근 작업 이력
        with ui.element("div").classes("content-card"):
            ui.label("크롤링 이력").classes("text-base font-semibold text-gray-700 mb-3")
            history_container = ui.column().style("width:100%")

            def load_history():
                history_container.clear()
                with history_container:
                    jobs = repo.get_crawl_jobs(limit=15)
                    if not jobs:
                        ui.label("작업 이력이 없습니다.").classes("text-gray-400 text-sm")
                        return

                    status_colors = {
                        "completed": "text-green-600", "failed": "text-red-500",
                        "running": "text-blue-500", "interrupted": "text-amber-600",
                        "cancelled": "text-gray-400",
                    }
                    for job in jobs:
                        with ui.row().classes("w-full items-center gap-3 py-2 border-b border-gray-100"):
                            ui.label(f"#{job['hashtag']}").classes("font-medium text-gray-700 w-32")
                            ui.label(f"{job['collected_count']}/{job['target_count']}").classes("text-sm text-gray-500 w-20 text-center")
                            sc = status_colors.get(job["status"], "text-gray-500")
                            ui.label(job["status"]).classes(f"text-xs font-semibold {sc} w-24")
                            ui.label(job.get("started_at", "-") or "-").classes("text-xs text-gray-400 flex-1")
                            if job.get("error_message"):
                                ui.icon("error_outline", size="16px").classes("text-red-400").tooltip(job["error_message"])
                            # 재개 버튼 (interrupted / failed 작업만)
                            if job["status"] in ("interrupted", "failed") and job.get("collected_count", 0) < job["target_count"]:
                                remaining = job["target_count"] - job.get("collected_count", 0)
                                ui.button(
                                    f"재개 ({remaining}명)",
                                    on_click=lambda j=job: _resume_crawl(j, crawl_accs, account_select, progress, status_label, crawl_btn, load_history),
                                    icon="replay",
                                ).props("flat dense size=sm color=primary")

            load_history()

            def _resume_crawl(job, crawl_accs_list, acct_select, prog, stat_label, c_btn, reload_fn):
                """중단된 크롤링을 재개한다."""
                account_id = job.get("account_id") or (acct_select.value if acct_select.value else None)
                if not account_id:
                    ui.notify("크롤링 계정을 선택해주세요.", type="warning")
                    return
                if _get_state("login_status", sub_key=account_id) is not True:
                    ui.notify("먼저 계정 관리에서 로그인해주세요.", type="negative")
                    return

                remaining = job["target_count"] - job.get("collected_count", 0)
                hashtag = job["hashtag"]
                stat_label.text = f"재개 중... #{hashtag} (남은: {remaining}명)"
                prog.value = 0
                c_btn.disable()

                def run():
                    try:
                        driver = _get_state("drivers", sub_key=account_id)
                        if not driver:
                            stat_label.text = "Chrome이 실행되지 않았습니다."
                            return

                        # 새 작업 생성 (원본 참조)
                        new_job_id = repo.create_crawl_job(hashtag, remaining, account_id)
                        crawler = HashtagCrawler(driver, account_id=account_id)
                        _set_state("crawlers", crawler, sub_key=account_id)

                        def on_prog(collected, total, username):
                            prog.value = collected / total if total else 0
                            stat_label.text = f"재개 중... #{hashtag} ({collected}/{total}) @{username}"

                        result = crawler.crawl(hashtag, remaining, new_job_id, on_progress=on_prog)
                        stat_label.text = f"재개 완료! {len(result.collected)}명 추가 수집"
                        prog.value = 1.0
                        reload_fn()
                    except Exception as e:
                        stat_label.text = f"오류: {e}"
                    finally:
                        c_btn.enable()

                threading.Thread(target=run, daemon=True).start()


# =====================================================================
#  유저 관리 페이지
# =====================================================================

@ui.page("/users")
def users_page():
    if not _check_license():
        return
    _layout("users")
    limits = _get_plan_limits()

    _user_page_state = {"current": 1, "per_page": 100, "total": 0}

    with ui.column().style("width:100%;padding:24px;gap:24px"):
        with ui.element("div").classes("content-card"):
            total_all = repo.get_user_count()
            total_label = ui.label(f"총 {total_all}명")
            with ui.row().classes("items-center gap-3 mb-4"):
                ui.label("수집된 유저").classes("text-base font-semibold text-gray-700")
                total_label.classes("text-sm text-gray-400")

            # 필터 + 검색 + 내보내기
            with ui.row().classes("gap-3 mb-4 items-end"):
                hashtag_stats = repo.get_hashtag_stats()
                hashtag_options = {"": "전체"} | {h["hashtag"]: f"#{h['hashtag']} ({h['count']})" for h in hashtag_stats}
                filter_hashtag = ui.select(
                    hashtag_options, value="", label="해시태그 필터"
                ).props("outlined dense").classes("w-52")

                user_search = ui.input("검색", placeholder="유저 아이디 검색...").props(
                    "outlined dense clearable"
                ).classes("w-52")

                ui.space()

                if limits["can_export"]:
                    ui.button("Excel", on_click=lambda: _do_export("excel", filter_hashtag.value), icon="table_chart").props("outline dense size=sm")
                    ui.button("CSV", on_click=lambda: _do_export("csv", filter_hashtag.value), icon="download").props("outline dense size=sm")
                else:
                    ui.button("Excel", icon="table_chart").props("outline dense size=sm disable").tooltip("Pro 이상")
                    ui.button("CSV", icon="download").props("outline dense size=sm disable").tooltip("Pro 이상")

            # 유저 테이블 + 페이지네이션
            users_container = ui.column().style("width:100%")

            def load_users(reset_page=True):
                if reset_page:
                    _user_page_state["current"] = 1

                ht = filter_hashtag.value or None
                search = user_search.value.strip() if user_search.value else None
                total = repo.get_user_count(hashtag=ht, search=search)
                _user_page_state["total"] = total
                total_label.text = f"총 {total}명"

                per_page = _user_page_state["per_page"]
                cur = _user_page_state["current"]
                offset = (cur - 1) * per_page
                total_pages = max(1, (total + per_page - 1) // per_page)

                users = repo.get_users(offset=offset, limit=per_page, hashtag=ht, search=search)

                users_container.clear()
                with users_container:
                    if users:
                        # 헤더
                        with ui.element("div").classes(
                            "w-full flex items-center gap-0 py-2 px-3 bg-gray-50 rounded-t-lg border border-b-0"
                        ):
                            ui.label("유저네임").classes("text-xs font-semibold text-gray-500").style("flex:1 1 0;min-width:0")
                            ui.label("해시태그").classes("text-xs font-semibold text-gray-500").style("flex:0 0 140px")
                            ui.label("수집일").classes("text-xs font-semibold text-gray-500").style("flex:0 0 100px")
                            ui.label("분석").classes("text-xs font-semibold text-gray-500").style("flex:0 0 60px;text-align:center")
                            ui.label("DM").classes("text-xs font-semibold text-gray-500").style("flex:0 0 60px;text-align:center")
                        for u in users:
                            with ui.element("div").classes(
                                "w-full flex items-center gap-0 border-x px-3"
                            ).style("min-height:36px"):
                                ui.link(f"@{u['username']}", target="").classes(
                                    "text-sm text-indigo-600 truncate cursor-pointer no-underline hover:underline"
                                ).style("flex:1 1 0;min-width:0").on(
                                    "click.prevent", lambda _, uid=u["id"]: _open_user_profile_modal(uid)
                                )
                                ui.label(f"#{u['first_seen_hashtag'] or '-'}").classes(
                                    "text-xs text-gray-400 truncate"
                                ).style("flex:0 0 140px")
                                ui.label(u["crawled_at"][:10] if u["crawled_at"] else "-").classes(
                                    "text-xs text-gray-400"
                                ).style("flex:0 0 100px")
                                ui.label("O" if u["is_analyzed"] else "-").classes(
                                    "text-xs text-center " + ("text-green-600" if u["is_analyzed"] else "text-gray-300")
                                ).style("flex:0 0 60px")
                                ui.label("O" if u["is_dm_sent"] else "-").classes(
                                    "text-xs text-center " + ("text-green-600" if u["is_dm_sent"] else "text-gray-300")
                                ).style("flex:0 0 60px")
                        ui.element("div").classes("border-x border-b rounded-b-lg h-1")

                        # 페이지네이션
                        if total_pages > 1:
                            with ui.row().classes("w-full justify-center items-center gap-1 mt-4"):
                                ui.button("", icon="chevron_left",
                                          on_click=lambda: go_page(cur - 1)).props(
                                    "flat dense size=sm" + (" disable" if cur <= 1 else ""))

                                if total_pages <= 7:
                                    pages = list(range(1, total_pages + 1))
                                elif cur <= 4:
                                    pages = list(range(1, 6)) + [None, total_pages]
                                elif cur >= total_pages - 3:
                                    pages = [1, None] + list(range(total_pages - 4, total_pages + 1))
                                else:
                                    pages = [1, None, cur - 1, cur, cur + 1, None, total_pages]

                                for p in pages:
                                    if p is None:
                                        ui.label("...").classes("text-gray-400 text-sm px-1")
                                    elif p == cur:
                                        ui.button(str(p)).props("unelevated dense size=sm color=primary").classes("min-w-[32px]")
                                    else:
                                        ui.button(str(p), on_click=lambda _, pg=p: go_page(pg)).props(
                                            "flat dense size=sm").classes("min-w-[32px]")

                                ui.button("", icon="chevron_right",
                                          on_click=lambda: go_page(cur + 1)).props(
                                    "flat dense size=sm" + (" disable" if cur >= total_pages else ""))

                                ui.label(f"{cur} / {total_pages} 페이지").classes("text-xs text-gray-400 ml-3")
                    else:
                        ui.label("수집된 유저가 없습니다.").classes("text-gray-400 text-sm py-4 text-center")

            def go_page(page):
                total_pages = max(1, (_user_page_state["total"] + _user_page_state["per_page"] - 1) // _user_page_state["per_page"])
                if 1 <= page <= total_pages:
                    _user_page_state["current"] = page
                    load_users(reset_page=False)

            load_users()
            filter_hashtag.on_value_change(lambda _: load_users())
            user_search.on_value_change(lambda _: load_users())


def _do_export(fmt: str, hashtag: str):
    limits = _get_plan_limits()
    if not limits["can_export"]:
        ui.notify("Pro 플랜 이상에서 사용 가능합니다.", type="warning")
        return
    try:
        ht = hashtag if hashtag else None
        if fmt == "excel":
            path = export_users_excel(ht)
        else:
            path = export_users_csv(ht)
        ui.notify(f"내보내기 완료: {path}", type="positive")
    except Exception as e:
        ui.notify(f"내보내기 오류: {e}", type="negative")


# =====================================================================
#  DM 발송 페이지
# =====================================================================

@ui.page("/dm")
def dm_page():
    if not _check_license():
        return
    _layout("dm")
    limits = _get_plan_limits()

    with ui.column().style("width:100%;padding:24px;gap:24px"):
        # DM 통계
        dm_stats = repo.get_dm_stats()
        with ui.row().style("width:100%;gap:16px;flex-wrap:wrap"):
            _stat_card("총 발송", dm_stats["total"], "email", "#6366f1")
            _stat_card("성공", dm_stats["sent"], "check_circle", "#10b981")
            _stat_card("실패", dm_stats["failed"], "error", "#ef4444")
            dm_txt = "무제한" if limits["max_daily_dm"] >= 9999 else str(limits["max_daily_dm"])
            _stat_card("일일 한도", dm_txt, "schedule", "#f59e0b")

        # 메시지 템플릿
        with ui.element("div").classes("content-card"):
            with ui.row().classes("items-center gap-3 mb-4"):
                ui.label("메시지 템플릿").classes("text-base font-semibold text-gray-700")
                ui.label("DM 발송에 사용할 메시지 템플릿을 관리합니다.").classes("text-xs text-gray-400")
                ui.space()
                ui.button("새 템플릿", on_click=lambda: _open_template_modal(None, load_templates), icon="add").props(
                    "unelevated dense"
                )

            templates_container = ui.column().style("width:100%;gap:0")

            def load_templates():
                templates_container.clear()
                with templates_container:
                    tpls = repo.get_dm_templates()
                    if not tpls:
                        ui.label("등록된 템플릿이 없습니다. 새 템플릿을 추가하세요.").classes(
                            "text-gray-400 text-sm py-4 text-center"
                        )
                        return
                    for tpl in tpls:
                        with ui.element("div").classes(
                            "w-full border rounded-lg p-4 mb-2 hover:shadow-sm transition-shadow"
                        ):
                            with ui.row().classes("items-start gap-4 w-full"):
                                # 이미지 미리보기
                                if tpl.get("image_path"):
                                    ui.image(tpl["image_path"]).classes(
                                        "w-16 h-16 rounded-lg object-cover flex-shrink-0"
                                    )
                                else:
                                    with ui.element("div").classes(
                                        "w-16 h-16 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0"
                                    ):
                                        ui.icon("image", size="24px").classes("text-gray-300")

                                with ui.column().classes("flex-1 gap-1 min-w-0"):
                                    ui.label(tpl["name"]).classes("text-sm font-bold text-gray-800")
                                    msg_preview = tpl["message_body"][:120] + ("..." if len(tpl["message_body"]) > 120 else "")
                                    ui.label(msg_preview).classes("text-xs text-gray-500 break-all")
                                    # 변수 태그 표시
                                    variables = _re.findall(r'\{(\w+)\}', tpl["message_body"])
                                    if variables:
                                        with ui.row().classes("gap-1 mt-1"):
                                            for var in set(variables):
                                                ui.label(f"{{{var}}}").classes(
                                                    "text-[10px] bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded"
                                                )

                                with ui.row().classes("gap-1 flex-shrink-0"):
                                    ui.button(
                                        "", icon="edit",
                                        on_click=lambda t=tpl: _open_template_modal(t, load_templates),
                                    ).props("flat dense size=sm color=primary")
                                    ui.button(
                                        "", icon="delete",
                                        on_click=lambda t=tpl: _delete_template(t["id"], load_templates),
                                    ).props("flat dense size=sm color=red")

            load_templates()

        # ── 발송 대상 선택 ──
        with ui.element("div").classes("content-card"):
            with ui.row().classes("items-center gap-3 mb-4"):
                ui.label("발송 대상 선택").classes("text-base font-semibold text-gray-700")
                ui.space()

                def _open_add_targets_modal():
                    dialog = ui.dialog()
                    with dialog, ui.card().style("width:500px;max-width:90vw"):
                        with ui.row().classes("w-full items-center justify-between mb-4"):
                            ui.label("대상 아이디 추가").classes("text-lg font-bold text-gray-800")
                            ui.button(icon="close", on_click=dialog.close).props("flat dense round")

                        ui.label("아이디를 입력하면 유저 DB에 등록되고 자동으로 선택됩니다.").classes("text-xs text-gray-400 mb-3")
                        ui.label("줄바꿈 또는 쉼표로 구분하여 여러 명 입력 가능").classes("text-xs text-gray-400 mb-3")

                        add_input = ui.textarea(
                            placeholder="user1\nuser2\nuser3\n또는 user1, user2, user3"
                        ).props("outlined").classes("w-full").style("min-height:120px")

                        add_tag = ui.input("해시태그 (선택)", placeholder="예: 수동추가").props("outlined dense").classes("w-full mt-2")

                        add_status = ui.label("").classes("text-sm mt-2")

                        def _do_add():
                            raw = add_input.value or ""
                            names = [n.strip().lstrip("@") for n in raw.replace(",", "\n").split("\n") if n.strip()]
                            if not names:
                                ui.notify("추가할 아이디를 입력해주세요.", type="warning")
                                return

                            tag = (add_tag.value or "수동추가").strip()
                            added = 0
                            already = 0
                            added_ids = []
                            for uname in names:
                                if not uname:
                                    continue
                                is_new = repo.add_user(uname, tag)
                                if is_new:
                                    added += 1
                                else:
                                    already += 1
                                # user id 조회해서 선택 목록에 추가
                                users_found = repo.get_users(limit=1, search=uname)
                                if users_found:
                                    added_ids.append(users_found[0]["id"])

                            # 자동 선택
                            for uid in added_ids:
                                _dm_selected["ids"].add(uid)

                            add_status.text = f"완료! 새로 추가: {added}명, 기존: {already}명 → 총 {len(added_ids)}명 선택됨"
                            add_status.classes(replace="text-sm mt-2 text-green-600")
                            ui.notify(f"{len(added_ids)}명이 발송 대상에 추가되었습니다.", type="positive")
                            load_targets(reset_page=False)

                        with ui.row().classes("w-full justify-end gap-2 mt-4"):
                            ui.button("취소", on_click=dialog.close).props("flat")
                            ui.button("추가", on_click=_do_add, icon="add").props("unelevated")

                    dialog.open()

                ui.button("대상 추가", on_click=_open_add_targets_modal, icon="person_add").props("outline dense")

                def _delete_selected_targets():
                    ids = list(_dm_selected["ids"])
                    if not ids:
                        ui.notify("삭제할 대상을 선택해주세요.", type="warning")
                        return

                    confirm_dialog = ui.dialog()
                    with confirm_dialog, ui.card().style(
                        "position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);"
                        "width:400px;max-width:90vw;z-index:9999"
                    ):
                        ui.label(f"선택한 {len(ids)}명을 삭제하시겠습니까?").classes("text-base font-semibold mb-2")
                        ui.label("유저 정보, 프로필, DM 이력이 모두 삭제됩니다.").classes("text-xs text-red-500 mb-4")

                        with ui.row().classes("w-full justify-end gap-2"):
                            ui.button("취소", on_click=confirm_dialog.close).props("flat")

                            def _do_delete():
                                count = repo.delete_users(ids)
                                _dm_selected["ids"].difference_update(set(ids))
                                confirm_dialog.close()
                                load_targets()
                                ui.notify(f"{count}명이 삭제되었습니다.", type="positive")

                            ui.button("삭제", on_click=_do_delete, icon="delete").props("unelevated color=red")

                    confirm_dialog.open()

                ui.button("선택 삭제", on_click=_delete_selected_targets, icon="delete").props("outline dense color=red")

            # 필터 행
            hashtag_stats = repo.get_hashtag_stats()
            with ui.row().classes("gap-3 items-end mb-4 flex-wrap"):
                dm_filter_search = ui.input(
                    "검색", placeholder="유저 아이디 검색..."
                ).props("outlined dense clearable").classes("w-48")
                dm_filter_hashtag = ui.select(
                    {"": "전체 해시태그"} | {h["hashtag"]: f"#{h['hashtag']} ({h['count']})" for h in hashtag_stats},
                    value="", label="해시태그"
                ).props("outlined dense").classes("w-48")
                dm_filter_status = ui.select(
                    {"all": "전체", "not_sent": "미발송", "sent": "발송완료"},
                    value="not_sent", label="발송 상태"
                ).props("outlined dense").classes("w-36")
                dm_filter_sort = ui.select(
                    {"crawled_at_desc": "수집일 (최신순)", "crawled_at_asc": "수집일 (오래된순)",
                     "username_asc": "아이디 (A-Z)", "username_desc": "아이디 (Z-A)"},
                    value="crawled_at_desc", label="정렬"
                ).props("outlined dense").classes("w-48")

            # 선택 상태 (페이지 이동해도 유지)
            _dm_selected = {"ids": set()}
            _dm_page = {"current": 1, "per_page": 100, "total": 0}

            # 대상 테이블
            target_summary = ui.label("").classes("text-sm text-gray-500 mb-2")
            target_container = ui.column().style("width:100%;gap:0")
            page_nav_container = ui.row().classes("w-full items-center justify-center gap-2 mt-3")

            def _parse_sort(val):
                if val.endswith("_desc"):
                    return val[:-5], True
                if val.endswith("_asc"):
                    return val[:-4], False
                return "crawled_at", True

            def _get_filter_params():
                ht = dm_filter_hashtag.value or None
                status_val = dm_filter_status.value
                dm_sent = None
                if status_val == "not_sent":
                    dm_sent = False
                elif status_val == "sent":
                    dm_sent = True
                sort_by, sort_desc = _parse_sort(dm_filter_sort.value)
                search = (dm_filter_search.value or "").strip() or None
                return ht, dm_sent, sort_by, sort_desc, search

            def load_targets(reset_page=True):
                if reset_page:
                    _dm_page["current"] = 1
                ht, dm_sent, sort_by, sort_desc, search = _get_filter_params()

                # 총 건수
                total = repo.get_user_count(hashtag=ht, dm_sent=dm_sent, search=search)
                _dm_page["total"] = total
                total_pages = max(1, (total + _dm_page["per_page"] - 1) // _dm_page["per_page"])
                if _dm_page["current"] > total_pages:
                    _dm_page["current"] = total_pages

                offset = (_dm_page["current"] - 1) * _dm_page["per_page"]
                users = repo.get_users(
                    offset=offset, limit=_dm_page["per_page"],
                    hashtag=ht, dm_sent=dm_sent,
                    sort_by=sort_by, sort_desc=sort_desc,
                    search=search,
                )

                _render_target_table(users, total, total_pages)

            def _render_target_table(users, total, total_pages):
                _bl_set = repo.get_blacklisted_usernames()
                sel_count = len(_dm_selected["ids"])
                not_sent_count = sum(1 for u in users if not u["is_dm_sent"])
                bl_count = sum(1 for u in users if u["username"].lower() in _bl_set)
                target_summary.text = (
                    f"전체 {total}명 | 현재 페이지 {len(users)}명 | "
                    f"선택: {sel_count}명 | 미발송: {not_sent_count}명"
                    + (f" | 블랙리스트: {bl_count}명" if bl_count else "")
                )

                target_container.clear()
                with target_container:
                    if not users:
                        ui.label("조건에 맞는 유저가 없습니다.").classes("text-gray-400 text-sm py-4 text-center")
                        _render_pagination(total_pages)
                        return

                    # 헤더 행 (전체 선택 + 컬럼명)
                    with ui.element("div").classes(
                        "w-full flex items-center gap-0 py-2 px-3 bg-gray-50 rounded-t-lg border border-b-0"
                    ):
                        page_ids = {u["id"] for u in users}
                        page_all_checked = page_ids.issubset(_dm_selected["ids"])

                        def toggle_page_all(e, ids=page_ids):
                            if e.value:
                                _dm_selected["ids"].update(ids)
                            else:
                                _dm_selected["ids"].difference_update(ids)
                            load_targets(reset_page=False)

                        ui.checkbox("", value=page_all_checked, on_change=toggle_page_all).props("dense").style("flex:0 0 40px")
                        ui.label("아이디").classes("text-xs font-semibold text-gray-500").style("flex:1 1 0;min-width:0")
                        ui.label("해시태그").classes("text-xs font-semibold text-gray-500").style("flex:0 0 140px")
                        ui.label("수집일").classes("text-xs font-semibold text-gray-500").style("flex:0 0 100px")
                        ui.label("상태").classes("text-xs font-semibold text-gray-500").style("flex:0 0 80px")

                    # 유저 행
                    for u in users:
                        is_sent = u["is_dm_sent"]
                        is_checked = u["id"] in _dm_selected["ids"]
                        is_bl = u["username"].lower() in _bl_set
                        bg = ""
                        if is_bl:
                            bg = "background:#fef2f2;"
                        elif is_sent:
                            bg = "background:#f0fdf4;"
                        elif is_checked:
                            bg = "background:#eef2ff;"

                        with ui.element("div").classes(
                            "w-full flex items-center gap-0 border-x px-3"
                        ).style(f"min-height:40px;{bg}"):
                            def toggle_user(e, uid=u["id"]):
                                if e.value:
                                    _dm_selected["ids"].add(uid)
                                else:
                                    _dm_selected["ids"].discard(uid)
                                # 카운터만 업데이트
                                sel_count = len(_dm_selected["ids"])
                                target_summary.text = _re.sub(
                                    r"선택: \d+명",
                                    f"선택: {sel_count}명",
                                    target_summary.text,
                                )

                            ui.checkbox("", value=is_checked, on_change=toggle_user).props("dense").style("flex:0 0 40px")
                            ui.link(f"@{u['username']}", target="").classes(
                                "text-sm text-indigo-600 truncate cursor-pointer no-underline hover:underline"
                            ).style("flex:1 1 0;min-width:0").on(
                                "click.prevent", lambda _, uid=u["id"]: _open_user_profile_modal(uid)
                            )
                            ui.label(f"#{u['first_seen_hashtag'] or '-'}").classes(
                                "text-xs text-gray-400 truncate"
                            ).style("flex:0 0 140px")
                            ui.label(
                                u["crawled_at"][:10] if u["crawled_at"] else "-"
                            ).classes("text-xs text-gray-400").style("flex:0 0 100px")
                            if is_bl:
                                ui.label("블랙리스트").classes(
                                    "text-[10px] bg-red-100 text-red-700 px-2 py-0.5 rounded-full"
                                ).style("flex:0 0 80px")
                            elif is_sent:
                                ui.label("발송완료").classes(
                                    "text-[10px] bg-green-100 text-green-700 px-2 py-0.5 rounded-full"
                                ).style("flex:0 0 80px")
                            else:
                                ui.label("미발송").classes(
                                    "text-[10px] bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full"
                                ).style("flex:0 0 80px")

                    # 하단 테두리
                    ui.element("div").classes("border-x border-b rounded-b-lg h-1")

                _render_pagination(total_pages)

            def _render_pagination(total_pages):
                page_nav_container.clear()
                with page_nav_container:
                    cur = _dm_page["current"]

                    def go_page(p):
                        _dm_page["current"] = p
                        load_targets(reset_page=False)

                    # 이전
                    ui.button(
                        "", icon="chevron_left",
                        on_click=lambda: go_page(cur - 1),
                    ).props("flat dense size=sm" + (" disable" if cur <= 1 else ""))

                    # 페이지 번호 (최대 7개 표시)
                    if total_pages <= 7:
                        pages = list(range(1, total_pages + 1))
                    else:
                        if cur <= 4:
                            pages = list(range(1, 6)) + [None, total_pages]
                        elif cur >= total_pages - 3:
                            pages = [1, None] + list(range(total_pages - 4, total_pages + 1))
                        else:
                            pages = [1, None, cur - 1, cur, cur + 1, None, total_pages]

                    for p in pages:
                        if p is None:
                            ui.label("...").classes("text-gray-400 text-sm px-1")
                        elif p == cur:
                            ui.button(str(p)).props("unelevated dense size=sm color=primary").classes("min-w-[32px]")
                        else:
                            ui.button(
                                str(p),
                                on_click=lambda _, pg=p: go_page(pg),
                            ).props("flat dense size=sm").classes("min-w-[32px]")

                    # 다음
                    ui.button(
                        "", icon="chevron_right",
                        on_click=lambda: go_page(cur + 1),
                    ).props("flat dense size=sm" + (" disable" if cur >= total_pages else ""))

                    # 페이지 정보
                    ui.label(f"{cur} / {total_pages} 페이지").classes("text-xs text-gray-400 ml-3")

            load_targets()

            # 필터 변경 시 자동 갱신 (페이지 리셋)
            for flt in [dm_filter_search, dm_filter_hashtag, dm_filter_status, dm_filter_sort]:
                flt.on_value_change(lambda _: load_targets())

        # ── DM 발송 실행 ──
        with ui.element("div").classes("content-card"):
            ui.label("DM 발송").classes("text-base font-semibold text-gray-700 mb-4")

            dm_accounts = get_accounts("dm")
            dm_options = {}
            for a in dm_accounts:
                if _get_state("login_status", sub_key=a["id"]) is True:
                    dm_options[a["id"]] = f"@{a['username']}"
                else:
                    dm_options[a["id"]] = f"@{a['username']} (로그인 필요)"

            templates = repo.get_dm_templates()

            with ui.row().classes("gap-3 items-end"):
                dm_account_select = ui.select(
                    dm_options, label="발송 계정 (복수 선택 가능)", multiple=True,
                ).props("outlined dense use-chips").classes("w-72")
                tpl_select = ui.select(
                    {t["id"]: t["name"] for t in templates} if templates else {},
                    label="메시지 템플릿 (복수 선택 시 랜덤)", multiple=True,
                ).props("outlined dense use-chips").classes("w-72")

            # 계정별 진행률 컨테이너
            dm_multi_container = ui.column().classes("w-full mt-4 gap-2")
            dm_status = ui.label("").classes("mt-2 text-sm")

            # 계정별 진행률 UI 위젯 (동적 생성)
            _dm_acc_widgets = {}  # account_id -> {"progress": ..., "label": ...}

            def _ensure_acc_widget(account_id, username):
                """계정별 진행률 위젯을 생성한다."""
                if account_id in _dm_acc_widgets:
                    return _dm_acc_widgets[account_id]
                with dm_multi_container:
                    with ui.card().classes("w-full p-3").style("background:#f8f9fa"):
                        lbl = ui.label(f"@{username}: 준비 중...").classes("text-sm font-medium")
                        prog = ui.linear_progress(0).props("rounded size=6px color=indigo-5")
                _dm_acc_widgets[account_id] = {"label": lbl, "progress": prog}
                return _dm_acc_widgets[account_id]

            def start_dm():
                selected_ids = list(_dm_selected["ids"])
                if not selected_ids:
                    ui.notify("발송할 대상을 선택해주세요.", type="warning")
                    return
                raw_acc = dm_account_select.value
                selected_acc_ids = raw_acc if isinstance(raw_acc, list) else ([raw_acc] if raw_acc else [])
                if not selected_acc_ids:
                    ui.notify("발송 계정을 선택해주세요.", type="warning")
                    return
                selected_tpl_ids = tpl_select.value if isinstance(tpl_select.value, list) else ([tpl_select.value] if tpl_select.value else [])
                if not selected_tpl_ids:
                    ui.notify("메시지 템플릿을 선택해주세요.", type="warning")
                    return

                # 로그인 안된 계정 필터링
                valid_acc_ids = []
                for aid in selected_acc_ids:
                    if _get_state("login_status", sub_key=aid) is True:
                        valid_acc_ids.append(aid)
                    else:
                        acc_name = dm_options.get(aid, str(aid))
                        ui.notify(f"{acc_name} 로그인 필요 — 건너뜁니다.", type="warning")
                if not valid_acc_ids:
                    ui.notify("로그인된 계정이 없습니다.", type="negative")
                    return

                if len(selected_ids) > limits["max_daily_dm"] and limits["max_daily_dm"] < 9999:
                    ui.notify(f"일일 DM 한도 초과! (최대 {limits['max_daily_dm']}건, 선택: {len(selected_ids)}건)", type="negative")
                    return

                selected_templates = [t for t in templates if t["id"] in selected_tpl_ids]
                if not selected_templates:
                    return

                # 대상 유저 조회
                all_users = repo.get_users(limit=9999)
                blacklisted = repo.get_blacklisted_usernames()
                target_users = [
                    u for u in all_users
                    if u["id"] in set(selected_ids) and u["username"].lower() not in blacklisted
                ]
                if not target_users:
                    dm_status.text = "발송할 대상이 없습니다. (블랙리스트 제외 후 0명)"
                    return

                # 대상을 계정 수로 분배 (라운드로빈)
                import math
                num_accounts = len(valid_acc_ids)
                target_list = [{"user_id": t["id"], "username": t["username"], "display_name": t.get("display_name")} for t in target_users]
                chunks = [[] for _ in range(num_accounts)]
                for idx, t in enumerate(target_list):
                    chunks[idx % num_accounts].append(t)

                tpl_names = ", ".join(t["name"] for t in selected_templates)
                random_label = " (랜덤)" if len(selected_templates) > 1 else ""
                acc_names = ", ".join(dm_options.get(aid, "").replace(" (로그인 필요)", "") for aid in valid_acc_ids)
                dm_status.text = (
                    f"DM 발송 시작! 계정 {num_accounts}개 × 대상 {len(target_list)}명 "
                    f"({acc_names}) / 템플릿: {tpl_names}{random_label}"
                )

                # 기존 위젯 초기화
                dm_multi_container.clear()
                _dm_acc_widgets.clear()
                dm_send_btn.disable()

                # 전체 집계용
                _dm_totals = {"sent": 0, "failed": 0, "done_count": 0, "total_accounts": num_accounts}
                _dm_totals_lock = threading.Lock()

                def run_dm_for_account(account_id, chunk):
                    acc_info = next((a for a in get_accounts() if a["id"] == account_id), None)
                    acc_username = acc_info["username"] if acc_info else str(account_id)
                    widgets = _ensure_acc_widget(account_id, acc_username)

                    try:
                        driver = _get_state("drivers", sub_key=account_id)

                        # driver가 없거나 죽었으면 자동으로 Chrome 실행
                        if not driver or not is_driver_alive(driver):
                            widgets["label"].text = f"@{acc_username}: Chrome 실행 중..."
                            if not acc_info:
                                widgets["label"].text = f"@{acc_username}: 계정 정보 없음"
                                return
                            proxy_data = None
                            if acc_info.get("proxy_id"):
                                proxy_data = proxy_manager.get_by_id(acc_info["proxy_id"])
                            driver = create_chrome_driver(
                                profile_name=acc_username, proxy=proxy_data
                            )
                            _set_state("drivers", driver, sub_key=account_id)
                            navigate_to_instagram(driver)
                            import time as _t
                            _t.sleep(2)

                        if not check_login(driver):
                            _set_state("login_status", False, sub_key=account_id)
                            widgets["label"].text = f"@{acc_username}: 로그인 만료"
                            return

                        sender = DmSender(driver, account_id)

                        def on_progress(sent_n, failed_n, total_n, username, success):
                            widgets["progress"].value = (sent_n + failed_n) / total_n if total_n else 0
                            mark = "O" if success else "X"
                            widgets["label"].text = (
                                f"@{acc_username}: {mark} @{username} "
                                f"({sent_n + failed_n}/{total_n})"
                            )

                        result = sender.send_batch(
                            chunk,
                            templates=selected_templates,
                            on_progress=on_progress,
                        )

                        # 발송 완료 유저 상태 업데이트
                        sent_ids = [t["user_id"] for t in chunk[:result.get("sent", 0)]]
                        if sent_ids:
                            repo.mark_users_dm_sent(sent_ids)
                            _dm_selected["ids"].difference_update(set(sent_ids))

                        widgets["progress"].value = 1.0

                        if result.get("blocked"):
                            reason = result.get("block_reason", "")
                            if reason == "challenge":
                                widgets["label"].text = f"@{acc_username}: 보안 인증 필요 (성공: {result['sent']}명)"
                            elif reason == "login_required":
                                widgets["label"].text = f"@{acc_username}: 로그인 만료"
                            else:
                                widgets["label"].text = f"@{acc_username}: 차단! 성공: {result['sent']}명"
                            _set_state("login_status", False, sub_key=account_id)
                        elif result.get("daily_limit_reached"):
                            widgets["label"].text = f"@{acc_username}: 일일 한도 도달"
                        else:
                            widgets["label"].text = f"@{acc_username}: 완료! 성공 {result['sent']}명, 실패 {result['failed']}명"

                        with _dm_totals_lock:
                            _dm_totals["sent"] += result.get("sent", 0)
                            _dm_totals["failed"] += result.get("failed", 0)

                    except Exception as e:
                        widgets["label"].text = f"@{acc_username}: 오류 - {e}"
                    finally:
                        with _dm_totals_lock:
                            _dm_totals["done_count"] += 1
                            if _dm_totals["done_count"] >= _dm_totals["total_accounts"]:
                                dm_status.text = (
                                    f"전체 완료! 성공: {_dm_totals['sent']}명, "
                                    f"실패: {_dm_totals['failed']}명 "
                                    f"(계정 {num_accounts}개 사용)"
                                )
                                dm_send_btn.enable()

                # 각 계정별 스레드 실행
                for i, aid in enumerate(valid_acc_ids):
                    if not chunks[i]:
                        continue
                    threading.Thread(
                        target=run_dm_for_account, args=(aid, chunks[i]), daemon=True
                    ).start()

            with ui.row().classes("mt-4 gap-3 items-center"):
                dm_send_btn = ui.button("DM 발송 시작", on_click=start_dm, icon="send").props("unelevated")
                ui.button("목록 새로고침", on_click=lambda: load_targets(), icon="refresh").props("outline dense")

        # ── DM 발송 이력 ──
        with ui.element("div").classes("content-card"):
            ui.label("발송 이력").classes("text-base font-semibold text-gray-700 mb-3")
            _dm_hist_page = {"current": 1, "per_page": 50}

            with ui.row().classes("gap-3 mb-3 items-end"):
                hist_search = ui.input("검색", placeholder="유저 아이디...").props("outlined dense clearable").classes("w-44")
                hist_status_filter = ui.select(
                    {"": "전체", "sent": "성공", "failed": "실패"},
                    value="", label="상태"
                ).props("outlined dense").classes("w-32")

                def _retry_failed_dms():
                    failed_targets = repo.get_failed_dm_targets()
                    if not failed_targets:
                        ui.notify("재시도할 실패 건이 없습니다.", type="info")
                        return
                    # 블랙리스트 제외
                    bl = repo.get_blacklisted_usernames()
                    failed_targets = [t for t in failed_targets if t["username"].lower() not in bl]
                    if not failed_targets:
                        ui.notify("블랙리스트 제외 후 재시도 대상이 없습니다.", type="info")
                        return
                    # 선택 목록에 추가
                    for t in failed_targets:
                        _dm_selected["ids"].add(t["user_id"])
                    ui.notify(f"실패 {len(failed_targets)}명을 DM 대상에 추가했습니다. 위에서 발송해주세요.", type="positive")
                    load_targets(reset_page=False)

                ui.button("실패 재전송 대상 추가", on_click=_retry_failed_dms, icon="replay").props("outline dense")

            hist_container = ui.column().style("width:100%")

            def load_dm_history(reset_page=True):
                if reset_page:
                    _dm_hist_page["current"] = 1
                cur = _dm_hist_page["current"]
                per = _dm_hist_page["per_page"]
                offset = (cur - 1) * per
                st = hist_status_filter.value or None
                srch = hist_search.value.strip() if hist_search.value else None

                items, total = repo.get_dm_history(offset=offset, limit=per, status=st, search=srch)
                total_pages = max(1, (total + per - 1) // per)

                hist_container.clear()
                with hist_container:
                    if not items:
                        ui.label("발송 이력이 없습니다.").classes("text-gray-400 text-sm py-2")
                        return

                    status_colors = {"sent": "text-green-600", "failed": "text-red-500", "pending": "text-gray-400"}
                    for h in items:
                        with ui.row().classes("w-full items-center gap-3 py-1.5 border-b border-gray-100"):
                            sc = status_colors.get(h["status"], "text-gray-500")
                            ui.label(h["status"]).classes(f"text-xs font-semibold {sc} w-16")
                            ui.label(f"@{h['username']}").classes("text-sm text-gray-700 w-36")
                            ui.label(h["message_preview"]).classes("text-xs text-gray-400 flex-1 truncate")
                            ui.label(h.get("sent_at", "-") or "-").classes("text-xs text-gray-400 w-36")

                    # 페이지네이션
                    if total_pages > 1:
                        with ui.row().classes("w-full justify-center items-center gap-1 mt-3"):
                            ui.button("", icon="chevron_left",
                                      on_click=lambda: _go_hist_page(cur - 1)).props(
                                "flat dense size=sm" + (" disable" if cur <= 1 else ""))
                            ui.label(f"{cur} / {total_pages}").classes("text-xs text-gray-400 mx-2")
                            ui.button("", icon="chevron_right",
                                      on_click=lambda: _go_hist_page(cur + 1)).props(
                                "flat dense size=sm" + (" disable" if cur >= total_pages else ""))

            def _go_hist_page(page):
                st = hist_status_filter.value or None
                srch = hist_search.value.strip() if hist_search.value else None
                total = repo.get_dm_history_count(status=st, search=srch)
                per = _dm_hist_page["per_page"]
                total_pages = max(1, (total + per - 1) // per)
                if 1 <= page <= total_pages:
                    _dm_hist_page["current"] = page
                    load_dm_history(reset_page=False)

            load_dm_history()
            hist_search.on_value_change(lambda _: load_dm_history())
            hist_status_filter.on_value_change(lambda _: load_dm_history())


def _open_template_modal(existing_tpl: dict | None, reload_fn):
    """템플릿 생성/수정 모달을 연다."""
    from insta_service.config import DM_IMAGES_DIR

    is_edit = existing_tpl is not None
    modal_title = "템플릿 수정" if is_edit else "새 템플릿 만들기"

    # 모달 상태
    _modal_state = {
        "image_path": existing_tpl.get("image_path") if is_edit else None,
    }

    with ui.dialog().props("persistent") as dialog, \
         ui.card().style("width:600px;max-width:90vw;padding:0"):

        # 헤더
        with ui.element("div").classes("px-6 pt-5 pb-3 border-b"):
            with ui.row().classes("items-center w-full"):
                ui.icon("description", size="24px").classes("text-indigo-500")
                ui.label(modal_title).classes("text-lg font-bold text-gray-800 ml-2")
                ui.space()
                ui.button("", icon="close", on_click=dialog.close).props("flat dense round size=sm")

        # 본문
        with ui.column().classes("px-6 py-4 gap-4"):
            # 템플릿 이름 (강조)
            ui.label("템플릿 이름").classes("text-sm font-semibold text-gray-700 -mb-2")
            tpl_name = ui.input(
                placeholder="예: 협업 제안, 이벤트 안내, 팔로업 메시지...",
                value=existing_tpl["name"] if is_edit else "",
            ).props("outlined dense").classes("w-full").style(
                "font-size: 16px; font-weight: 600;"
            )

            # 메시지 내용
            ui.label("메시지 내용").classes("text-sm font-semibold text-gray-700 -mb-2")

            tpl_body = ui.textarea(
                placeholder="안녕하세요! {username}님, #{hashtag} 관련 협업 제안드립니다...",
                value=existing_tpl["message_body"] if is_edit else "",
            ).props("outlined rows=6").classes("w-full")

            # 변수 삽입 버튼
            ui.label("변수 삽입").classes("text-xs text-gray-500 -mb-2")
            with ui.row().classes("gap-2 flex-wrap"):
                variables = [
                    ("{username}", "유저 아이디"),
                    ("{name}", "유저 이름"),
                    ("{hashtag}", "해시태그"),
                    ("{company}", "업체명"),
                    ("{date}", "오늘 날짜"),
                ]
                for var, desc in variables:
                    def insert_var(v=var):
                        current = tpl_body.value or ""
                        tpl_body.value = current + v

                    ui.button(
                        f"{var} {desc}", on_click=insert_var,
                    ).props("outline dense size=sm no-caps").classes("text-xs")

            # 이미지 첨부
            ui.label("이미지 첨부 (선택)").classes("text-sm font-semibold text-gray-700 -mb-2")
            image_preview = ui.column().classes("w-full")

            def show_image_preview():
                image_preview.clear()
                with image_preview:
                    if _modal_state["image_path"]:
                        with ui.row().classes("items-center gap-3"):
                            ui.image(_modal_state["image_path"]).classes(
                                "w-24 h-24 rounded-lg object-cover"
                            )
                            with ui.column().classes("gap-1"):
                                fname = os.path.basename(_modal_state["image_path"])
                                ui.label(fname).classes("text-xs text-gray-600")
                                ui.button(
                                    "삭제", icon="delete",
                                    on_click=lambda: _remove_image(),
                                ).props("flat dense size=sm color=red")

            def _remove_image():
                _modal_state["image_path"] = None
                show_image_preview()

            async def handle_upload(e):
                try:
                    content = await e.file.read()
                    fname = e.file.name
                    save_path = DM_IMAGES_DIR / fname
                    # 동일 파일명 충돌 방지
                    counter = 1
                    while save_path.exists():
                        stem = save_path.stem
                        save_path = DM_IMAGES_DIR / f"{stem}_{counter}{save_path.suffix}"
                        counter += 1
                    save_path.write_bytes(content)
                    _modal_state["image_path"] = str(save_path)
                    show_image_preview()
                    ui.notify(f"이미지 첨부: {fname}", type="positive")
                except Exception as ex:
                    ui.notify(f"업로드 실패: {ex}", type="negative")

            ui.upload(
                on_upload=handle_upload,
                label="이미지를 드래그하거나 클릭하여 업로드",
                auto_upload=True,
                max_file_size=10_000_000,
            ).props('accept="image/*" flat bordered').classes("w-full").style(
                "max-height: 80px"
            )

            show_image_preview()

        # 하단 버튼
        with ui.element("div").classes("px-6 py-4 border-t bg-gray-50 rounded-b-xl"):
            with ui.row().classes("w-full justify-end gap-3"):
                ui.button("취소", on_click=dialog.close).props("flat color=grey")

                def save_template():
                    name = tpl_name.value.strip()
                    body = tpl_body.value.strip()
                    if not name:
                        ui.notify("템플릿 이름을 입력해주세요.", type="warning")
                        return
                    if not body:
                        ui.notify("메시지 내용을 입력해주세요.", type="warning")
                        return

                    if is_edit:
                        repo.update_dm_template(
                            existing_tpl["id"],
                            name=name,
                            message_body=body,
                            image_path=_modal_state["image_path"],
                        )
                        ui.notify(f"'{name}' 템플릿이 수정되었습니다.", type="positive")
                    else:
                        repo.add_dm_template(name, body, _modal_state["image_path"])
                        ui.notify(f"'{name}' 템플릿이 저장되었습니다.", type="positive")

                    dialog.close()
                    reload_fn()

                ui.button(
                    "수정" if is_edit else "저장",
                    on_click=save_template, icon="save",
                ).props("unelevated")

    dialog.open()


def _delete_template(template_id: int, reload_fn):
    """템플릿 삭제 확인 후 삭제."""
    with ui.dialog() as confirm, ui.card().classes("p-6"):
        ui.label("이 템플릿을 삭제하시겠습니까?").classes("text-sm text-gray-700")
        with ui.row().classes("mt-4 justify-end gap-3"):
            ui.button("취소", on_click=confirm.close).props("flat color=grey")

            def do_delete():
                repo.delete_dm_template(template_id)
                ui.notify("템플릿이 삭제되었습니다.", type="positive")
                confirm.close()
                reload_fn()

            ui.button("삭제", on_click=do_delete, icon="delete").props("unelevated color=red")
    confirm.open()


# =====================================================================
#  설정 페이지
# =====================================================================

@ui.page("/settings")
def settings_page():
    if not _check_license():
        return
    _layout("settings")
    limits = _get_plan_limits()

    with ui.column().style("width:100%;padding:24px;gap:24px"):
        # 라이선스 정보
        with ui.element("div").classes("content-card"):
            ui.label("라이선스 정보").classes("text-base font-semibold text-gray-700 mb-4")
            lic = _get_state("license_info") or repo.get_license() or {}

            rows = [
                ("업체명", lic.get("company_name", "-")),
                ("플랜", limits["plan"].upper()),
                ("만료일", lic.get("expires_at", "-")),
                ("크롤링 계정", f"최대 {limits['max_crawl_accounts']}개"),
                ("DM 계정", f"최대 {limits['max_dm_accounts']}개"),
                ("일일 DM", "무제한" if limits["max_daily_dm"] >= 9999 else f"{limits['max_daily_dm']}건"),
                ("해시태그", "무제한" if limits["max_hashtags"] >= 9999 else f"{limits['max_hashtags']}개"),
                ("유저 분석", "사용 가능" if limits["can_analyze"] else "Pro 이상"),
                ("데이터 내보내기", "사용 가능" if limits["can_export"] else "Pro 이상"),
                ("스케줄링", "사용 가능" if limits["can_schedule"] else "Pro 이상"),
                ("프로그램 버전", f"v{APP_VERSION}"),
            ]
            with ui.grid(columns=2).classes("gap-x-8 gap-y-2"):
                for label, value in rows:
                    ui.label(label).classes("text-sm text-gray-500")
                    ui.label(value).classes("text-sm font-medium text-gray-800")

        # 프록시 관리
        with ui.element("div").classes("content-card"):
            with ui.row().classes("items-center gap-3 mb-4"):
                ui.label("프록시 관리").classes("text-base font-semibold text-gray-700")

                def reload_proxies():
                    load_proxies_from_file()
                    ui.notify("프록시 로드 완료", type="positive")
                    ui.navigate.to("/settings")

                ui.button("proxies.txt 다시 로드", on_click=reload_proxies, icon="refresh").props("outline dense size=sm")

            proxies_list = proxy_manager.get_all()
            if proxies_list:
                columns = [
                    {"name": "ip", "label": "IP", "field": "ip", "align": "left"},
                    {"name": "port", "label": "포트", "field": "port", "align": "center"},
                    {"name": "active", "label": "활성", "field": "is_active", "align": "center"},
                ]
                ui.table(columns=columns, rows=proxies_list).classes("w-full").props("flat dense")
            else:
                ui.label("등록된 프록시가 없습니다.").classes("text-gray-400 text-sm")

        # 크롤링/DM 설정
        with ui.element("div").classes("content-card"):
            ui.label("크롤링 / DM 설정").classes("text-base font-semibold text-gray-700 mb-4")

            cur = _cfg_ref

            with ui.grid(columns=2).classes("gap-4 w-full"):
                crawl_min = ui.number("크롤링 최소 딜레이(초)", value=cur["crawling"]["min_delay"], min=1, max=60, step=0.5).classes("w-full")
                crawl_max = ui.number("크롤링 최대 딜레이(초)", value=cur["crawling"]["max_delay"], min=1, max=120, step=0.5).classes("w-full")
                dm_hourly = ui.number("시간당 DM 한도", value=cur["dm"]["hourly_limit"], min=1, max=100, step=1).classes("w-full")
                dm_daily = ui.number("일일 DM 한도 (계정당)", value=cur["dm"]["daily_limit_per_account"], min=1, max=500, step=1).classes("w-full")
                dm_min = ui.number("DM 발송 최소 딜레이(초)", value=cur["dm"]["min_delay"], min=5, max=300, step=1).classes("w-full")
                dm_max = ui.number("DM 발송 최대 딜레이(초)", value=cur["dm"]["max_delay"], min=10, max=600, step=1).classes("w-full")

            ui.label("릴스 브라우징 (봇 탐지 우회)").classes("text-sm font-semibold text-gray-600 mt-4 mb-2")
            with ui.grid(columns=3).classes("gap-4 w-full"):
                reels_min = ui.number("릴스 최소 시간(초)", value=cur["dm"].get("reels_min_time", 15), min=5, max=300, step=1).classes("w-full")
                reels_max = ui.number("릴스 최대 시간(초)", value=cur["dm"].get("reels_max_time", 40), min=10, max=600, step=1).classes("w-full")
                reels_chance = ui.number("릴스 확률(%)", value=cur["dm"].get("reels_chance", 60), min=0, max=100, step=5).classes("w-full")
            ui.label("DM 발송 사이에 릴스를 보며 대기합니다. 확률 0%로 설정하면 릴스 없이 대기만 합니다.").classes("text-xs text-gray-400 -mt-2")

            ui.label("Chrome 설정").classes("text-sm font-semibold text-gray-600 mt-4 mb-2")
            chrome_path = ui.input("Chrome 바이너리 경로", value=cur["chrome"]["binary_path"]).classes("w-full")
            chrome_headless = ui.checkbox("Headless 모드", value=cur["chrome"]["headless"])

            def _save_settings():
                new_cfg = {
                    "server": cur.get("server", {}),
                    "crawling": {
                        **cur["crawling"],
                        "min_delay": float(crawl_min.value),
                        "max_delay": float(crawl_max.value),
                    },
                    "dm": {
                        **cur["dm"],
                        "hourly_limit": int(dm_hourly.value),
                        "daily_limit_per_account": int(dm_daily.value),
                        "min_delay": int(dm_min.value),
                        "max_delay": int(dm_max.value),
                        "reels_min_time": int(reels_min.value),
                        "reels_max_time": int(reels_max.value),
                        "reels_chance": int(reels_chance.value),
                    },
                    "chrome": {
                        **cur["chrome"],
                        "binary_path": chrome_path.value,
                        "headless": chrome_headless.value,
                    },
                    "selectors": cur.get("selectors", {}),
                }
                # top-level 키 보존
                for k, v in cur.items():
                    if k not in new_cfg:
                        new_cfg[k] = v
                save_config(new_cfg)
                ui.notify("설정이 저장되었습니다. (일부 변경은 재시작 후 적용)", type="positive")

            ui.button("설정 저장", on_click=_save_settings, icon="save").props("unelevated color=primary").classes("mt-4")

        # 유틸리티
        with ui.element("div").classes("content-card"):
            ui.label("유틸리티").classes("text-base font-semibold text-gray-700 mb-4")

            with ui.row().classes("gap-3 flex-wrap"):
                # DB 백업
                def _do_backup():
                    result = backup_database()
                    if result:
                        ui.notify(f"백업 완료: {result.name}", type="positive")
                    else:
                        ui.notify("백업 실패", type="negative")

                ui.button("DB 백업", on_click=_do_backup, icon="backup").props("outline")

                # 로그 다운로드
                def _download_logs():
                    import zipfile
                    import tempfile
                    log_files = list(LOG_DIR.glob("*.log"))
                    if not log_files:
                        ui.notify("다운로드할 로그 파일이 없습니다.", type="warning")
                        return
                    zip_path = os.path.join(tempfile.gettempdir(), "insta_logs.zip")
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        for lf in log_files:
                            zf.write(lf, lf.name)
                    ui.download(zip_path, "insta_logs.zip")

                ui.button("로그 다운로드", on_click=_download_logs, icon="download").props("outline")

        # 블랙리스트 관리
        with ui.element("div").classes("content-card"):
            ui.label("DM 블랙리스트").classes("text-base font-semibold text-gray-700 mb-2")
            ui.label("블랙리스트에 등록된 아이디는 DM 발송 대상에서 자동 제외됩니다.").classes("text-xs text-gray-400 mb-4")

            bl_container = ui.column().style("width:100%")

            def _reload_blacklist():
                bl_container.clear()
                bl_items = repo.get_blacklist()
                with bl_container:
                    if bl_items:
                        with ui.element("div").classes("w-full max-h-64 overflow-y-auto border rounded-lg"):
                            for item in bl_items:
                                with ui.element("div").classes(
                                    "flex items-center justify-between px-3 py-1.5 border-b last:border-b-0 hover:bg-gray-50"
                                ):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.label(f"@{item['username']}").classes("text-sm text-gray-800")
                                        if item.get("reason"):
                                            ui.label(item["reason"]).classes("text-xs text-gray-400")
                                    def _remove(bid=item["id"]):
                                        repo.remove_from_blacklist([bid])
                                        ui.notify("블랙리스트에서 제거되었습니다.", type="info")
                                        _reload_blacklist()
                                    ui.button(icon="close", on_click=_remove).props("flat dense size=xs color=red")
                        ui.label(f"총 {len(bl_items)}개").classes("text-xs text-gray-400 mt-1")
                    else:
                        ui.label("블랙리스트가 비어 있습니다.").classes("text-gray-400 text-sm")

            _reload_blacklist()

            ui.separator().classes("my-3")

            # 단일 추가
            with ui.row().classes("gap-2 items-end"):
                bl_input = ui.input("아이디 추가", placeholder="@username").props("outlined dense").classes("w-52")
                bl_reason = ui.input("사유 (선택)", placeholder="예: 경쟁업체").props("outlined dense").classes("w-40")

                def _add_single():
                    uname = (bl_input.value or "").strip()
                    if not uname:
                        ui.notify("아이디를 입력해주세요.", type="warning")
                        return
                    ok = repo.add_to_blacklist(uname, bl_reason.value or "")
                    if ok:
                        ui.notify(f"@{uname.lstrip('@')} 블랙리스트에 추가", type="positive")
                        bl_input.value = ""
                        bl_reason.value = ""
                        _reload_blacklist()
                    else:
                        ui.notify("이미 블랙리스트에 존재합니다.", type="info")

                ui.button("추가", on_click=_add_single, icon="add").props("unelevated dense")

            # 일괄 추가 (textarea)
            ui.label("일괄 추가 (줄바꿈 또는 쉼표로 구분)").classes("text-xs text-gray-500 mt-3")
            bl_bulk = ui.textarea(placeholder="user1\nuser2\nuser3").props("outlined dense").classes("w-full").style("min-height:80px")

            def _add_bulk():
                raw = bl_bulk.value or ""
                names = [n.strip() for n in raw.replace(",", "\n").split("\n") if n.strip()]
                if not names:
                    ui.notify("추가할 아이디를 입력해주세요.", type="warning")
                    return
                added = repo.add_bulk_to_blacklist(names)
                ui.notify(f"{added}명 블랙리스트에 추가 (중복 제외)", type="positive")
                bl_bulk.value = ""
                _reload_blacklist()

            ui.button("일괄 추가", on_click=_add_bulk, icon="playlist_add").props("outline dense").classes("mt-2")


# =====================================================================
#  헬퍼 함수
# =====================================================================

def _check_license() -> bool:
    if not _get_state("licensed"):
        result = license_validator.verify()
        if not result.get("ok"):
            ui.navigate.to("/activate")
            return False
        _set_state("licensed", True)
        _set_state("license_info", result)
    return True


def _stat_card(title: str, value, icon: str, color: str):
    with ui.element("div").classes("stat-card flex-1"):
        with ui.row().classes("items-center gap-3"):
            ui.icon(icon, size="28px").style(f"color: {color}")
            with ui.column().classes("gap-0"):
                ui.label(str(value)).classes("text-2xl font-bold text-gray-800")
                ui.label(title).classes("text-xs text-gray-400")


def _open_user_profile_modal(user_id: int):
    """유저 프로필 미리보기 모달을 연다."""
    detail = repo.get_user_detail(user_id)
    if not detail:
        ui.notify("유저 정보를 찾을 수 없습니다.", type="warning")
        return

    dialog = ui.dialog()
    with dialog, ui.card().style("width:420px;max-width:90vw"):
        with ui.row().classes("w-full items-center justify-between mb-4"):
            ui.label(f"@{detail['username']}").classes("text-lg font-bold text-gray-800")
            ui.button(icon="close", on_click=dialog.close).props("flat dense round")

        # 뱃지 행
        with ui.row().classes("gap-2 mb-3"):
            if detail.get("is_private"):
                ui.label("비공개").classes("text-[10px] bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full")
            if detail.get("is_verified"):
                ui.label("인증됨").classes("text-[10px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full")
            if detail.get("is_dm_sent"):
                ui.label("DM 발송완료").classes("text-[10px] bg-green-100 text-green-700 px-2 py-0.5 rounded-full")

        if detail.get("is_analyzed"):
            with ui.grid(columns=3).classes("gap-4 mb-4"):
                for label, val in [("팔로워", detail.get("followers_count")),
                                    ("팔로잉", detail.get("following_count")),
                                    ("게시물", detail.get("posts_count"))]:
                    with ui.column().classes("items-center gap-0"):
                        ui.label(f"{val:,}" if val is not None else "-").classes("text-lg font-bold text-gray-800")
                        ui.label(label).classes("text-xs text-gray-400")

            if detail.get("bio"):
                ui.label("바이오").classes("text-xs font-semibold text-gray-500 mt-1")
                ui.label(detail["bio"]).classes("text-sm text-gray-700 mb-3")

            if detail.get("analyzed_at"):
                ui.label(f"분석일: {detail['analyzed_at'][:10]}").classes("text-xs text-gray-400")
        else:
            ui.label("아직 프로필 분석이 되지 않았습니다.").classes("text-sm text-gray-400 my-4")

        # 해시태그
        if detail.get("hashtags"):
            ui.label("수집 해시태그").classes("text-xs font-semibold text-gray-500 mt-3")
            with ui.row().classes("gap-1 flex-wrap"):
                for h in detail["hashtags"]:
                    ui.label(f"#{h}").classes("text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full")

        ui.label(f"수집일: {detail.get('crawled_at', '-') or '-'}").classes("text-xs text-gray-400 mt-3")

    dialog.open()


def _graceful_shutdown():
    """앱 종료 시 모든 리소스를 안전하게 정리한다."""
    log.info("그레이스풀 셔다운 시작...")

    # 크롤러 취소
    with _state_lock:
        for aid, crawler in list(_state.get("crawlers", {}).items()):
            try:
                crawler.cancel()
                log.info(f"크롤러 취소: account_id={aid}")
            except Exception:
                pass
        _state["crawlers"] = {}

    # Chrome 드라이버 종료
    with _state_lock:
        for aid, driver in list(_state.get("drivers", {}).items()):
            try:
                close_driver(driver)
                log.info(f"Chrome 종료: account_id={aid}")
            except Exception:
                pass
        _state["drivers"] = {}
        _state["login_status"] = {}

    # APScheduler 종료
    try:
        from insta_service.core.scheduler import shutdown_scheduler
        shutdown_scheduler()
    except Exception:
        pass

    log.info("그레이스풀 셔다운 완료")


def run_dashboard():
    """대시보드 서버를 실행한다."""
    import sys as _sys
    from insta_service.config import cfg, DM_IMAGES_DIR

    init_db()
    load_proxies_from_file()

    # 종료 훅 등록
    app.on_shutdown(_graceful_shutdown)

    # DM 이미지 정적 파일 서빙
    app.add_static_files("/dm_images", str(DM_IMAGES_DIR))

    # PyInstaller frozen 환경에서는 127.0.0.1로 바인딩 (0.0.0.0은 방화벽 문제 가능)
    host = cfg["server"]["host"]
    if getattr(_sys, 'frozen', False) and host == "0.0.0.0":
        host = "127.0.0.1"

    log.info(f"대시보드 서버 시작: http://{host}:{cfg['server']['port']}")
    try:
        ui.run(
            title="Instagram Service",
            host=host,
            port=cfg["server"]["port"],
            reload=False,
            show=True,
        )
    except Exception as e:
        log.error(f"대시보드 서버 실행 실패: {e}")
        import traceback
        log.error(traceback.format_exc())
