"""공통 레이아웃 (사이드바 + 헤더) 및 공용 UI 헬퍼."""

from datetime import datetime

from nicegui import ui

from insta_service.ui.state import (
    get_state, set_state, get_plan_limits,
    PRIMARY, PRIMARY_DARK, SIDEBAR_BG, SIDEBAR_TEXT, PAGE_BG,
)
from insta_service.license.validator import license_validator, APP_VERSION


def layout(current: str = "dashboard"):
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
        /* 사이드바 너비만큼 컨텐츠 영역 밀기 */
        .q-page-container {{
            padding-left: 240px !important;
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

    lic = get_state("license_info") or {}
    limits = get_plan_limits()
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


def check_license() -> bool:
    if not get_state("licensed"):
        result = license_validator.verify()
        if not result.get("ok"):
            ui.navigate.to("/activate")
            return False
        set_state("licensed", True)
        set_state("license_info", result)
    return True


def stat_card(title: str, value, icon: str, color: str):
    with ui.element("div").classes("stat-card flex-1"):
        with ui.row().classes("items-center gap-3"):
            ui.icon(icon, size="28px").style(f"color: {color}")
            with ui.column().classes("gap-0"):
                ui.label(str(value)).classes("text-2xl font-bold text-gray-800")
                ui.label(title).classes("text-xs text-gray-400")
