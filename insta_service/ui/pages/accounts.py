"""계정 관리 페이지 (수동 로그인 워크플로우)."""

import threading
import shutil

from nicegui import ui

from insta_service.db import repository as repo
from insta_service.core.browser import (
    create_chrome_driver, check_login, check_login_safe,
    wait_for_manual_login, navigate_to_instagram, close_driver,
    is_driver_alive, rearrange_windows,
)
from insta_service.core.proxy_manager import proxy_manager
from insta_service.core.account_manager import register_account, get_accounts
from insta_service.ui.layout import layout, check_license
from insta_service.ui.state import _state, _state_lock, get_state, set_state, pop_state, get_plan_limits
from insta_service.utils.logger import log


@ui.page("/accounts")
def accounts_page():
    if not check_license():
        return
    layout("accounts")
    limits = get_plan_limits()

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
                    ui.button(
                        "창 정렬", icon="grid_view",
                        on_click=lambda: rearrange_windows(get_state("drivers") or {}),
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

            def _confirm_bulk_delete():
                dialog = ui.dialog().props("persistent")
                with dialog, ui.card().classes("w-80"):
                    ui.label("계정 삭제").classes("text-base font-semibold text-red-600 mb-2")
                    ui.label(f"{len(selected_ids)}개 계정을 삭제하시겠습니까?").classes("text-sm text-gray-600 mb-1")
                    ui.label("삭제된 계정은 복구할 수 없습니다.").classes("text-xs text-red-400 mb-3")

                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button("취소", on_click=dialog.close).props("flat dense")

                        def do_delete():
                            from insta_service.config import CHROME_PROFILES_DIR
                            ids = list(selected_ids)
                            accs_to_del = [a for a in get_accounts() if a["id"] in set(ids)]
                            for aid in ids:
                                driver = pop_state("drivers", sub_key=aid)
                                if driver:
                                    try:
                                        close_driver(driver)
                                    except Exception:
                                        pass
                                pop_state("login_status", sub_key=aid)
                                pop_state("crawlers", sub_key=aid)
                                with _state_lock:
                                    _state["_session_checked"].discard(aid)
                            repo.delete_accounts(ids)
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
                        is_logged_in = get_state("login_status", sub_key=aid) is True
                        driver_running = get_state("drivers", sub_key=aid) is not None

                        with ui.element("div").classes(
                            "w-full border rounded-xl p-4 flex items-center gap-4 "
                            + ("border-green-200 bg-green-50/50" if is_logged_in else "border-gray-200")
                        ):
                            ui.checkbox(
                                "", value=aid in selected_ids,
                                on_change=lambda e, a=aid: _toggle_account(a, e.value),
                            ).props("dense")

                            ui.icon("account_circle", size="36px").classes(
                                "text-green-500" if is_logged_in else "text-gray-300"
                            )
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
                                    login_val = get_state("login_status", sub_key=aid)
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

                            login_val = get_state("login_status", sub_key=aid)
                            with ui.row().classes("gap-2"):
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
                accs = get_accounts()
                checking = sum(1 for a in accs if get_state("login_status", sub_key=a["id"]) == "checking")
                if checking > 0:
                    session_status_label.text = f"세션 확인 중... ({checking}개 계정)"
                else:
                    logged = sum(1 for a in accs if get_state("login_status", sub_key=a["id"]) is True)
                    session_status_label.text = f"로그인: {logged}/{len(accs)}개 계정"

            ui.timer(1.5, _on_session_check_update)

            def _recheck_all_sessions():
                with _state_lock:
                    _state["_session_checked"].clear()
                _auto_check_sessions(load_accounts)
                ui.notify("전체 세션 재확인을 시작합니다.", type="info")

            with session_status_row:
                ui.button("전체 세션 확인", on_click=_recheck_all_sessions, icon="sync").props("outline dense size=sm")

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
                prev_keys = set(_prev_status.get("_drivers", set()))
                if driver_keys != prev_keys:
                    changed = True
                    _prev_status["_drivers"] = driver_keys
                if changed:
                    load_accounts()

            ui.timer(2.0, _auto_refresh)

            def _check_driver_health():
                dead_aids = []
                with _state_lock:
                    for aid, driver in list(_state["drivers"].items()):
                        if not is_driver_alive(driver):
                            dead_aids.append(aid)
                if dead_aids:
                    for aid in dead_aids:
                        pop_state("drivers", sub_key=aid)
                        set_state("login_status", False, sub_key=aid)
                        pop_state("crawlers", sub_key=aid)
                    accs_map = {a["id"]: a["username"] for a in get_accounts()}
                    names = ", ".join(f"@{accs_map.get(a, a)}" for a in dead_aids)
                    ui.notify(f"Chrome 크래시 감지: {names} - 다시 로그인해주세요.", type="warning")
                    load_accounts()

            ui.timer(10.0, _check_driver_health)


def _auto_check_sessions(reload_fn):
    """프로그램 시작 후 등록된 모든 계정의 세션을 단일 스레드에서 순차 확인한다."""
    accs = get_accounts()
    to_check = []
    for acc in accs:
        aid = acc["id"]
        with _state_lock:
            if aid in _state["_session_checked"] or aid in _state["drivers"]:
                continue
            _state["_session_checked"].add(aid)
            _state["login_status"][aid] = "checking"
            to_check.append(acc)

    if not to_check:
        return

    def _run_checks():
        import time as _t
        for account in to_check:
            account_id = account["id"]
            if account_id in get_state("_manual_login_pending", default=set()):
                continue
            driver = None
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

                if account_id in get_state("_manual_login_pending", default=set()):
                    continue

                if logged_in:
                    set_state("login_status", True, sub_key=account_id)
                    log.info(f"@{account['username']} 세션 유효 (자동 확인)")
                else:
                    set_state("login_status", False, sub_key=account_id)
                    log.info(f"@{account['username']} 세션 만료 - 로그인 필요")
            except Exception as e:
                log.debug(f"@{account['username']} 세션 확인 실패: {e}")
                if account_id not in get_state("_manual_login_pending", default=set()):
                    set_state("login_status", False, sub_key=account_id)
            finally:
                if driver:
                    try:
                        close_driver(driver)
                    except Exception:
                        pass
                _t.sleep(1)

    threading.Thread(target=_run_checks, daemon=True).start()


def _start_manual_login(acc: dict, reload_fn):
    """Chrome을 실행하고, 자동 로그인(세션 캐시) 시도 후 실패 시 수동 로그인을 안내한다."""
    aid = acc["id"]
    with _state_lock:
        _state["_manual_login_pending"].add(aid)
    ui.notify(f"@{acc['username']} Chrome 실행 중... 잠시 기다려주세요.", type="info")

    def run():
        try:
            old_driver = pop_state("drivers", sub_key=aid)
            if old_driver:
                try:
                    close_driver(old_driver)
                except Exception:
                    pass
                import time as _time
                _time.sleep(2)

            proxy_data = None
            if acc.get("proxy_id"):
                proxy_data = proxy_manager.get_by_id(acc["proxy_id"])

            driver = create_chrome_driver(profile_name=acc["username"], proxy=proxy_data)
            set_state("drivers", driver, sub_key=aid)
            set_state("login_status", False, sub_key=aid)

            log.info(f"@{acc['username']} 기존 세션으로 자동 로그인 시도 중...")
            navigate_to_instagram(driver)

            if check_login_safe(driver):
                set_state("login_status", True, sub_key=aid)
                log.info(f"@{acc['username']} 자동 로그인 성공! (저장된 세션 사용)")
                return

            log.info(
                f"@{acc['username']} 자동 로그인 실패. "
                f"Chrome 창에서 직접 인스타그램에 로그인해주세요. (5분 내 로그인 필요)"
            )
            driver.get("https://www.instagram.com/accounts/login/")
            import time
            time.sleep(2)

            logged_in = wait_for_manual_login(driver, check_interval=3.0, timeout=300.0)
            set_state("login_status", logged_in, sub_key=aid)

            if logged_in:
                log.info(f"@{acc['username']} 수동 로그인 성공! 세션이 저장되었습니다. 다음부터는 자동 로그인됩니다.")
            else:
                log.warning(f"@{acc['username']} 로그인 시간 초과. 다시 시도해주세요.")

        except Exception as e:
            log.error(f"Chrome 실행 오류: {e}")
            import traceback
            log.error(traceback.format_exc())
            set_state("login_status", False, sub_key=aid)
            try:
                ui.notify(f"Chrome 실행 실패: {e}", type="negative")
            except Exception:
                pass
        finally:
            with _state_lock:
                _state["_manual_login_pending"].discard(aid)

    threading.Thread(target=run, daemon=True).start()


def _verify_login(acc: dict, reload_fn):
    aid = acc["id"]
    driver = get_state("drivers", sub_key=aid)
    if not driver:
        ui.notify("Chrome이 실행되지 않았습니다.", type="warning")
        return
    try:
        logged_in = check_login(driver)
        set_state("login_status", logged_in, sub_key=aid)
        if logged_in:
            ui.notify(f"@{acc['username']} 로그인 확인됨!", type="positive")
        else:
            ui.notify(f"@{acc['username']} 아직 로그인되지 않았습니다.", type="warning")
        reload_fn()
    except Exception as e:
        ui.notify(f"확인 실패: {e}", type="negative")


def _close_chrome(acc: dict, reload_fn):
    aid = acc["id"]
    driver = pop_state("drivers", sub_key=aid)
    if driver:
        try:
            close_driver(driver)
        except Exception:
            pass
    pop_state("login_status", sub_key=aid)
    pop_state("crawlers", sub_key=aid)
    ui.notify(f"@{acc['username']} Chrome 종료됨", type="info")
    reload_fn()
