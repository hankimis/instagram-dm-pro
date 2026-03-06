"""설정 페이지."""

import os

from nicegui import ui

from insta_service.db import repository as repo
from insta_service.core.proxy_manager import proxy_manager, load_proxies_from_file
from insta_service.license.validator import APP_VERSION
from insta_service.config import cfg as _cfg_ref, save_config
from insta_service.ui.layout import layout, check_license
from insta_service.ui.state import get_state, get_plan_limits
from insta_service.utils.logger import LOG_DIR
from insta_service.utils.backup import backup_database


@ui.page("/settings")
def settings_page():
    if not check_license():
        return
    layout("settings")
    limits = get_plan_limits()

    with ui.column().style("width:100%;padding:24px;gap:24px"):
        # 라이선스 정보
        with ui.element("div").classes("content-card"):
            ui.label("라이선스 정보").classes("text-base font-semibold text-gray-700 mb-4")
            lic = get_state("license_info") or repo.get_license() or {}

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
                def _do_backup():
                    result = backup_database()
                    if result:
                        ui.notify(f"백업 완료: {result.name}", type="positive")
                    else:
                        ui.notify("백업 실패", type="negative")

                ui.button("DB 백업", on_click=_do_backup, icon="backup").props("outline")

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
