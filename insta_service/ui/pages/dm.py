"""DM 발송 페이지."""

import os
import re as _re
import threading

from nicegui import ui

from insta_service.db import repository as repo
from insta_service.core.browser import (
    create_chrome_driver, check_login, navigate_to_instagram, is_driver_alive,
)
from insta_service.core.dm_sender import DmSender
from insta_service.core.proxy_manager import proxy_manager
from insta_service.core.account_manager import get_accounts
from insta_service.ui.layout import layout, check_license, stat_card
from insta_service.ui.state import get_state, set_state, get_plan_limits
from insta_service.ui.components.user_profile_modal import open_user_profile_modal
from insta_service.utils.logger import log


@ui.page("/dm")
def dm_page():
    if not check_license():
        return
    layout("dm")
    limits = get_plan_limits()

    with ui.column().style("width:100%;padding:24px;gap:24px"):
        # DM 통계
        dm_stats = repo.get_dm_stats()
        with ui.row().style("width:100%;gap:16px;flex-wrap:wrap"):
            stat_card("총 발송", dm_stats["total"], "email", "#6366f1")
            stat_card("성공", dm_stats["sent"], "check_circle", "#10b981")
            stat_card("실패", dm_stats["failed"], "error", "#ef4444")
            dm_txt = "무제한" if limits["max_daily_dm"] >= 9999 else str(limits["max_daily_dm"])
            stat_card("일일 한도", dm_txt, "schedule", "#f59e0b")

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
                                users_found = repo.get_users(limit=1, search=uname)
                                if users_found:
                                    added_ids.append(users_found[0]["id"])

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

            _dm_selected = {"ids": set()}
            _dm_page = {"current": 1, "per_page": 100, "total": 0}

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
                                "click.prevent", lambda _, uid=u["id"]: open_user_profile_modal(uid)
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

                    ui.element("div").classes("border-x border-b rounded-b-lg h-1")

                _render_pagination(total_pages)

            def _render_pagination(total_pages):
                page_nav_container.clear()
                with page_nav_container:
                    cur = _dm_page["current"]

                    def go_page(p):
                        _dm_page["current"] = p
                        load_targets(reset_page=False)

                    ui.button(
                        "", icon="chevron_left",
                        on_click=lambda: go_page(cur - 1),
                    ).props("flat dense size=sm" + (" disable" if cur <= 1 else ""))

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

                    ui.button(
                        "", icon="chevron_right",
                        on_click=lambda: go_page(cur + 1),
                    ).props("flat dense size=sm" + (" disable" if cur >= total_pages else ""))

                    ui.label(f"{cur} / {total_pages} 페이지").classes("text-xs text-gray-400 ml-3")

            load_targets()

            for flt in [dm_filter_search, dm_filter_hashtag, dm_filter_status, dm_filter_sort]:
                flt.on_value_change(lambda _: load_targets())

        # ── DM 발송 실행 ──
        with ui.element("div").classes("content-card"):
            ui.label("DM 발송").classes("text-base font-semibold text-gray-700 mb-4")

            dm_accounts = get_accounts("dm")
            dm_options = {}
            for a in dm_accounts:
                if get_state("login_status", sub_key=a["id"]) is True:
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

            dm_multi_container = ui.column().classes("w-full mt-4 gap-2")
            dm_status = ui.label("").classes("mt-2 text-sm")

            _dm_acc_widgets = {}

            def _ensure_acc_widget(account_id, username):
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

                valid_acc_ids = []
                for aid in selected_acc_ids:
                    if get_state("login_status", sub_key=aid) is True:
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

                all_users = repo.get_users(limit=9999)
                blacklisted = repo.get_blacklisted_usernames()
                target_users = [
                    u for u in all_users
                    if u["id"] in set(selected_ids) and u["username"].lower() not in blacklisted
                ]
                if not target_users:
                    dm_status.text = "발송할 대상이 없습니다. (블랙리스트 제외 후 0명)"
                    return

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

                dm_multi_container.clear()
                _dm_acc_widgets.clear()
                dm_send_btn.disable()

                _dm_totals = {"sent": 0, "failed": 0, "done_count": 0, "total_accounts": num_accounts}
                _dm_totals_lock = threading.Lock()

                def run_dm_for_account(account_id, chunk):
                    acc_info = next((a for a in get_accounts() if a["id"] == account_id), None)
                    acc_username = acc_info["username"] if acc_info else str(account_id)
                    widgets = _ensure_acc_widget(account_id, acc_username)

                    try:
                        driver = get_state("drivers", sub_key=account_id)

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
                            set_state("drivers", driver, sub_key=account_id)
                            navigate_to_instagram(driver)
                            import time as _t
                            _t.sleep(2)

                        if not check_login(driver):
                            set_state("login_status", False, sub_key=account_id)
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
                            set_state("login_status", False, sub_key=account_id)
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
                    bl = repo.get_blacklisted_usernames()
                    failed_targets = [t for t in failed_targets if t["username"].lower() not in bl]
                    if not failed_targets:
                        ui.notify("블랙리스트 제외 후 재시도 대상이 없습니다.", type="info")
                        return
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

    _modal_state = {
        "image_path": existing_tpl.get("image_path") if is_edit else None,
    }

    with ui.dialog().props("persistent") as dialog, \
         ui.card().style("width:600px;max-width:90vw;padding:0"):

        with ui.element("div").classes("px-6 pt-5 pb-3 border-b"):
            with ui.row().classes("items-center w-full"):
                ui.icon("description", size="24px").classes("text-indigo-500")
                ui.label(modal_title).classes("text-lg font-bold text-gray-800 ml-2")
                ui.space()
                ui.button("", icon="close", on_click=dialog.close).props("flat dense round size=sm")

        with ui.column().classes("px-6 py-4 gap-4"):
            ui.label("템플릿 이름").classes("text-sm font-semibold text-gray-700 -mb-2")
            tpl_name = ui.input(
                placeholder="예: 협업 제안, 이벤트 안내, 팔로업 메시지...",
                value=existing_tpl["name"] if is_edit else "",
            ).props("outlined dense").classes("w-full").style(
                "font-size: 16px; font-weight: 600;"
            )

            ui.label("메시지 내용").classes("text-sm font-semibold text-gray-700 -mb-2")

            tpl_body = ui.textarea(
                placeholder="안녕하세요! {username}님, #{hashtag} 관련 협업 제안드립니다...",
                value=existing_tpl["message_body"] if is_edit else "",
            ).props("outlined rows=6").classes("w-full")

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
                    import uuid as _uuid
                    # 경로 탐색 방지: basename으로 디렉터리 제거 + UUID 접두사
                    safe_name = os.path.basename(e.file.name or "upload")
                    safe_name = f"{_uuid.uuid4().hex[:8]}_{safe_name}"
                    save_path = DM_IMAGES_DIR / safe_name
                    # 최종 경로가 DM_IMAGES_DIR 내부인지 검증
                    if not save_path.resolve().is_relative_to(DM_IMAGES_DIR.resolve()):
                        ui.notify("잘못된 파일명입니다.", type="negative")
                        return
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
