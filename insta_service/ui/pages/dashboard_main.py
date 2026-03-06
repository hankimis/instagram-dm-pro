"""대시보드 메인 페이지."""

from nicegui import ui

from insta_service.db import repository as repo
from insta_service.core.account_manager import get_accounts
from insta_service.ui.layout import layout, check_license, stat_card
from insta_service.ui.state import get_state, get_plan_limits
from insta_service.ui.components.update_banner import show_update_banner
from insta_service.utils.logger import get_log_buffer


@ui.page("/dashboard")
def dashboard_page():
    if not check_license():
        return
    layout("dashboard")
    limits = get_plan_limits()
    lic = get_state("license_info") or {}

    with ui.column().style("width:100%;padding:24px;gap:24px"):
        # 업데이트 확인
        show_update_banner()

        # 통계 카드
        with ui.row().style("width:100%;gap:16px;flex-wrap:wrap"):
            user_count = repo.get_user_count()
            stat_card("수집된 유저", user_count, "group", "#6366f1")

            hashtag_stats = repo.get_hashtag_stats()
            stat_card("해시태그", len(hashtag_stats), "tag", "#10b981")

            dm_stats = repo.get_dm_stats()
            stat_card("DM 발송", dm_stats["sent"], "send", "#8b5cf6")

            accounts = get_accounts()
            active = sum(1 for a in accounts if a["is_active"])
            stat_card("활성 계정", active, "account_circle", "#f59e0b")

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
