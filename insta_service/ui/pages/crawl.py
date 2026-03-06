"""크롤링 페이지."""

import threading
from datetime import datetime

from nicegui import ui

from insta_service.db import repository as repo
from insta_service.core.browser import (
    create_chrome_driver, check_login, navigate_to_instagram, is_driver_alive,
)
from insta_service.core.crawler import HashtagCrawler
from insta_service.core.proxy_manager import proxy_manager
from insta_service.core.account_manager import get_accounts
from insta_service.ui.layout import layout, check_license
from insta_service.ui.state import get_state, set_state, get_plan_limits
from insta_service.utils.logger import log


@ui.page("/crawl")
def crawl_page():
    if not check_license():
        return
    layout("crawl")
    limits = get_plan_limits()

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

                crawl_accs = get_accounts("crawl")
                logged_in_options = {}
                not_logged_options = {}
                for a in crawl_accs:
                    if get_state("login_status", sub_key=a["id"]) is True:
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

                if get_state("login_status", sub_key=account_id) is not True:
                    ui.notify("먼저 계정 관리에서 로그인해주세요.", type="negative")
                    return

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
                        driver = get_state("drivers", sub_key=account_id)

                        if not driver or not is_driver_alive(driver):
                            status_label.text = "Chrome 자동 실행 중..."
                            proxy_data = None
                            if acc.get("proxy_id"):
                                proxy_data = proxy_manager.get_by_id(acc["proxy_id"])
                            driver = create_chrome_driver(
                                profile_name=acc["username"], proxy=proxy_data
                            )
                            set_state("drivers", driver, sub_key=account_id)
                            navigate_to_instagram(driver)
                            import time as _t
                            _t.sleep(2)

                        if not check_login(driver):
                            set_state("login_status", False, sub_key=account_id)
                            status_label.text = "로그인이 만료되었습니다. 계정 관리에서 다시 로그인해주세요."
                            return

                        job_id = repo.create_crawl_job(hashtag, target, account_id)
                        crawler = HashtagCrawler(driver, account_id=account_id)
                        set_state("crawlers", crawler, sub_key=account_id)

                        status_label.text = f"크롤링 진행 중... #{hashtag}"

                        def on_crawl_progress(collected, total, username):
                            progress.value = collected / total if total else 0
                            status_label.text = f"크롤링 중... #{hashtag} ({collected}/{total}) @{username}"

                        result = crawler.crawl(hashtag, target, job_id, on_progress=on_crawl_progress)

                        if crawler.blocked:
                            status_label.text = f"차단 감지! {len(result.collected)}명 수집 후 중단됨"
                            set_state("login_status", False, sub_key=account_id)
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
                crawler = get_state("crawlers", sub_key=account_id) if account_id else None
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
                        target_count = int(count_input.value)
                        aid = account_select.value

                        def get_driver(account_id):
                            return get_state("drivers", sub_key=account_id)

                        schedule_crawl(run_at, ht, target_count, aid, get_driver)
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
                            if job["status"] in ("interrupted", "failed") and job.get("collected_count", 0) < job["target_count"]:
                                remaining = job["target_count"] - job.get("collected_count", 0)
                                ui.button(
                                    f"재개 ({remaining}명)",
                                    on_click=lambda j=job: _resume_crawl(j, crawl_accs, account_select, progress, status_label, crawl_btn, load_history),
                                    icon="replay",
                                ).props("flat dense size=sm color=primary")

            load_history()

            def _resume_crawl(job, crawl_accs_list, acct_select, prog, stat_label, c_btn, reload_fn):
                account_id = job.get("account_id") or (acct_select.value if acct_select.value else None)
                if not account_id:
                    ui.notify("크롤링 계정을 선택해주세요.", type="warning")
                    return
                if get_state("login_status", sub_key=account_id) is not True:
                    ui.notify("먼저 계정 관리에서 로그인해주세요.", type="negative")
                    return

                remaining = job["target_count"] - job.get("collected_count", 0)
                hashtag = job["hashtag"]
                stat_label.text = f"재개 중... #{hashtag} (남은: {remaining}명)"
                prog.value = 0
                c_btn.disable()

                def run():
                    try:
                        driver = get_state("drivers", sub_key=account_id)
                        if not driver:
                            stat_label.text = "Chrome이 실행되지 않았습니다."
                            return

                        new_job_id = repo.create_crawl_job(hashtag, remaining, account_id)
                        crawler = HashtagCrawler(driver, account_id=account_id)
                        set_state("crawlers", crawler, sub_key=account_id)

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
