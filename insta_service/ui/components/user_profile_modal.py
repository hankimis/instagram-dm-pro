"""유저 프로필 미리보기 모달."""

from nicegui import ui

from insta_service.db import repository as repo


def open_user_profile_modal(user_id: int):
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
