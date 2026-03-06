"""업데이트 확인 배너 컴포넌트."""

import os
import threading

from nicegui import ui

from insta_service.utils.logger import log


def show_update_banner():
    """업데이트를 확인하고 배너를 표시한다 (tufup 우선, GitHub API 폴백)."""
    from insta_service.core.updater import check_for_update, download_and_apply
    import platform as _plat

    update_info = check_for_update()
    if not update_info:
        return

    with ui.element("div").classes(
        "w-full bg-blue-50 border border-blue-200 rounded-xl px-5 py-4"
    ):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.row().classes("items-center gap-3"):
                ui.icon("system_update", size="24px").classes("text-blue-600")
                with ui.column().classes("gap-0.5"):
                    ui.label(f"새 버전 v{update_info['version']} 사용 가능").classes(
                        "text-blue-900 text-sm font-semibold"
                    )
                    size_mb = update_info.get("size", 0) / 1024 / 1024
                    if size_mb > 0:
                        ui.label(f"파일 크기: {size_mb:.1f} MB").classes("text-blue-600 text-xs")

            btn_container = ui.element("div")

        progress_container = ui.element("div").classes("w-full mt-3").style("display:none")
        with progress_container:
            progress_label = ui.label("다운로드 중...").classes("text-blue-700 text-xs mb-1")
            progress_bar = ui.linear_progress(value=0).classes("w-full")

        def start_update():
            btn_container.clear()
            with btn_container:
                ui.label("업데이트 중...").classes("text-blue-600 text-sm")
            progress_container.style("display:block")

            def do_download():
                try:
                    def on_progress(downloaded, total):
                        if total > 0:
                            pct = downloaded / total
                            progress_bar.set_value(pct)
                            mb_done = downloaded / 1024 / 1024
                            mb_total = total / 1024 / 1024
                            progress_label.set_text(
                                f"다운로드 중... {mb_done:.1f} / {mb_total:.1f} MB ({pct*100:.0f}%)"
                            )

                    success = download_and_apply(update_info, progress_callback=on_progress)

                    if success:
                        progress_label.set_text("업데이트 완료!")
                        progress_bar.set_value(1.0)
                        btn_container.clear()

                        if _plat.system() == "Windows":
                            with btn_container:
                                ui.label("앱을 재시작합니다...").classes(
                                    "text-blue-600 text-sm"
                                )
                            import time
                            time.sleep(2)
                            os._exit(0)
                        else:
                            with btn_container:
                                ui.label(
                                    "DMG 파일이 열렸습니다. 앱을 교체해주세요."
                                ).classes("text-blue-600 text-sm")
                    else:
                        progress_label.set_text("업데이트 실패")
                        btn_container.clear()
                        with btn_container:
                            ui.button("다시 시도", on_click=lambda: start_update(), icon="refresh").props(
                                "outline dense size=sm color=blue"
                            )

                except Exception as e:
                    log.error(f"업데이트 실패: {e}")
                    progress_label.set_text(f"실패: {e}")
                    btn_container.clear()
                    with btn_container:
                        ui.button("다시 시도", on_click=lambda: start_update(), icon="refresh").props(
                            "outline dense size=sm color=blue"
                        )

            threading.Thread(target=do_download, daemon=True).start()

        with btn_container:
            ui.button("지금 업데이트", on_click=start_update, icon="download").props(
                "dense color=blue"
            )
