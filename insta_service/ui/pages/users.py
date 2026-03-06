"""유저 관리 페이지."""

from nicegui import ui

from insta_service.db import repository as repo
from insta_service.ui.layout import layout, check_license
from insta_service.ui.state import get_plan_limits
from insta_service.ui.components.user_profile_modal import open_user_profile_modal
from insta_service.utils.export import export_users_excel, export_users_csv


@ui.page("/users")
def users_page():
    if not check_license():
        return
    layout("users")
    limits = get_plan_limits()

    _user_page_state = {"current": 1, "per_page": 100, "total": 0}

    with ui.column().style("width:100%;padding:24px;gap:24px"):
        with ui.element("div").classes("content-card"):
            total_all = repo.get_user_count()
            total_label = ui.label(f"총 {total_all}명")
            with ui.row().classes("items-center gap-3 mb-4"):
                ui.label("수집된 유저").classes("text-base font-semibold text-gray-700")
                total_label.classes("text-sm text-gray-400")

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
                                    "click.prevent", lambda _, uid=u["id"]: open_user_profile_modal(uid)
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
    limits = get_plan_limits()
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
