"""스플래시 화면 및 라이선스 활성화 페이지."""

import asyncio
import os
import sys
import threading

from nicegui import ui

from insta_service.ui.state import set_state, PRIMARY
from insta_service.license.validator import license_validator, APP_VERSION
from insta_service.utils.logger import log


@ui.page("/")
async def index_page():
    """스플래시 화면: 업데이트 확인 → 라이선스 확인 → 이동."""
    ui.query("body").style("background: #1e1b4b")

    with ui.column().classes("w-full items-center justify-center min-h-screen"):
        with ui.card().classes("w-[380px] p-10 shadow-2xl rounded-3xl").style(
            "background: rgba(255,255,255,0.97)"
        ):
            with ui.column().classes("w-full items-center gap-1 mb-6"):
                ui.icon("camera_alt", size="48px").classes("text-indigo-500")
                ui.label("Instagram DM Pro").classes("text-2xl font-bold text-gray-800")
                ui.label(f"v{APP_VERSION}").classes("text-xs text-gray-400")

            status = ui.label("시작 중...").classes("text-sm text-gray-500 text-center w-full")
            spinner = ui.spinner("dots", size="lg", color="indigo").classes("mx-auto")

            prog_box = ui.column().classes("w-full gap-1 mt-2")
            with prog_box:
                prog_detail = ui.label("").classes("text-xs text-gray-400 text-center")
                prog_bar = ui.linear_progress(value=0).props("color=indigo rounded")
            prog_box.set_visibility(False)

    async def _run():
        try:
            await asyncio.sleep(0.5)

            # Phase 1: 업데이트 확인 (frozen 빌드에서만)
            if getattr(sys, "frozen", False):
                status.text = "업데이트 확인 중..."
                try:
                    import platform as _plat
                    from insta_service.core.updater import check_for_update, download_and_apply
                except ImportError as ie:
                    log.warning(f"업데이트 모듈 로드 실패 (건너뜀): {ie}")
                    check_for_update = None

                if check_for_update:
                    loop = asyncio.get_event_loop()
                    try:
                        update_info = await asyncio.wait_for(
                            loop.run_in_executor(None, check_for_update),
                            timeout=10.0,
                        )
                    except Exception:
                        update_info = None

                    # Phase 2: 다운로드
                    if update_info:
                        version = update_info.get("version", "?")
                        status.text = f"v{version} 다운로드 중..."
                        spinner.set_visibility(False)
                        prog_box.set_visibility(True)

                        done_event = asyncio.Event()
                        dl_result = {"ok": False}

                        def on_progress(downloaded, total):
                            if total > 0:
                                pct = downloaded / total
                                prog_bar.set_value(pct)
                                mb_d = downloaded / 1024 / 1024
                                mb_t = total / 1024 / 1024
                                prog_detail.set_text(f"{mb_d:.1f} / {mb_t:.1f} MB ({pct*100:.0f}%)")

                        def do_download():
                            try:
                                dl_result["ok"] = download_and_apply(update_info, progress_callback=on_progress)
                            except Exception as e:
                                log.error(f"자동 업데이트 실패: {e}")
                            finally:
                                loop.call_soon_threadsafe(done_event.set)

                        threading.Thread(target=do_download, daemon=True).start()
                        await done_event.wait()

                        if dl_result["ok"] and _plat.system() == "Windows":
                            status.text = "업데이트 적용 중... 앱이 재시작됩니다."
                            prog_bar.set_value(1.0)
                            await asyncio.sleep(2)
                            os._exit(0)
                        elif dl_result["ok"]:
                            status.text = "DMG가 열렸습니다. 앱을 교체 후 재시작하세요."
                            await asyncio.sleep(3)

            # Phase 3: 라이선스 확인
            status.text = "인증 확인 중..."
            spinner.set_visibility(True)
            prog_box.set_visibility(False)
            await asyncio.sleep(0.3)

            loop = asyncio.get_event_loop()
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, license_validator.verify),
                    timeout=15.0,
                )
            except Exception:
                result = {"ok": False}

            if result.get("ok"):
                set_state("licensed", True)
                set_state("license_info", result)
                license_validator.start_heartbeat()
                ui.navigate.to("/dashboard")
            else:
                ui.navigate.to("/activate")

        except Exception as e:
            log.error(f"스플래시 시작 오류: {e}")
            import traceback
            log.error(traceback.format_exc())
            # 에러 발생해도 라이선스 확인으로 진행
            try:
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, license_validator.verify),
                    timeout=15.0,
                )
                if result.get("ok"):
                    set_state("licensed", True)
                    set_state("license_info", result)
                    ui.navigate.to("/dashboard")
                else:
                    ui.navigate.to("/activate")
            except Exception:
                ui.navigate.to("/activate")

    asyncio.ensure_future(_run())


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
                    set_state("licensed", True)
                    set_state("license_info", result)
                    await asyncio.sleep(1)
                    ui.navigate.to("/dashboard")
                else:
                    status_label.text = result.get("error", "인증 실패")
                    status_label.classes(replace="text-red-500 text-sm w-full text-center mt-2")

            ui.button("활성화", on_click=do_activate).classes("w-full mt-4").props("unelevated size=lg")

            # 버전 표시
            ui.label(f"v{APP_VERSION}").classes("text-xs text-gray-300 mt-6 text-center w-full")
