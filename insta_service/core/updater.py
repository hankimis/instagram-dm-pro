"""
앱 내 자동 업데이트 모듈.
GitHub Releases에서 최신 버전을 확인하고, 다운로드 + 교체 + 재시작.
"""
import os
import sys
import platform
import shutil
import subprocess
import zipfile
import tempfile
import threading
from pathlib import Path

import requests

from insta_service.config import BASE_DIR
from insta_service.utils.logger import log

GITHUB_REPO = "hankimis/instagram-dm-pro"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
UPDATE_DIR = BASE_DIR / "data" / "updates"


def get_current_version() -> str:
    from insta_service.license.validator import APP_VERSION
    return APP_VERSION


def check_for_update() -> dict | None:
    """GitHub Releases에서 최신 버전을 확인한다.
    업데이트가 있으면 {"version": "1.0.9", "download_url": "...", "size": 12345} 반환.
    없으면 None.
    """
    try:
        resp = requests.get(GITHUB_API_URL, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        latest_tag = data.get("tag_name", "")
        latest_version = latest_tag.lstrip("v")
        current = get_current_version()

        if not _is_newer(latest_version, current):
            return None

        # OS에 맞는 에셋 찾기
        asset = _find_asset(data.get("assets", []))
        if not asset:
            return None

        return {
            "version": latest_version,
            "tag": latest_tag,
            "download_url": asset["browser_download_url"],
            "size": asset.get("size", 0),
            "name": asset["name"],
            "release_notes": data.get("body", ""),
        }
    except Exception as e:
        log.debug(f"업데이트 확인 실패: {e}")
        return None


def _is_newer(latest: str, current: str) -> bool:
    """latest가 current보다 새 버전인지 비교."""
    try:
        from packaging.version import Version
        return Version(latest) > Version(current)
    except Exception:
        # packaging 없으면 단순 문자열 비교
        return latest != current


def _find_asset(assets: list) -> dict | None:
    """현재 OS에 맞는 릴리즈 에셋을 찾는다."""
    system = platform.system()
    for asset in assets:
        name = asset.get("name", "").lower()
        if system == "Windows" and "windows" in name and name.endswith(".zip"):
            return asset
        if system == "Darwin" and "macos" in name and name.endswith(".dmg"):
            return asset
    return None


def download_update(
    download_url: str,
    filename: str,
    progress_callback=None,
) -> Path:
    """업데이트 파일을 다운로드한다.
    progress_callback(downloaded_bytes, total_bytes) 호출.
    반환: 다운로드된 파일 경로.
    """
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPDATE_DIR / filename

    resp = requests.get(download_url, stream=True, timeout=30)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))

    downloaded = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if progress_callback:
                progress_callback(downloaded, total)

    log.info(f"업데이트 다운로드 완료: {dest} ({downloaded} bytes)")
    return dest


def apply_update_windows(zip_path: Path) -> bool:
    """Windows: zip 해제 후 배치 스크립트로 파일 교체 + 재시작."""
    try:
        extract_dir = UPDATE_DIR / "extracted"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)

        # zip 해제
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # 압축 해제된 폴더 찾기 (InstagramDMPro/)
        contents = list(extract_dir.iterdir())
        source_dir = contents[0] if len(contents) == 1 and contents[0].is_dir() else extract_dir

        app_dir = Path(sys.executable).resolve().parent
        pid = os.getpid()

        # 배치 스크립트 생성
        bat_path = UPDATE_DIR / "_updater.bat"
        bat_content = f"""@echo off
chcp 65001 >nul
echo 업데이트 적용 중...

REM 현재 프로세스 종료 대기
taskkill /PID {pid} /F >nul 2>&1
timeout /t 3 /nobreak >nul

REM data 폴더 보존하면서 기존 파일 백업
if exist "{app_dir}\\_backup" rmdir /s /q "{app_dir}\\_backup"
mkdir "{app_dir}\\_backup"

REM _internal과 exe만 백업 (data 폴더는 보존)
if exist "{app_dir}\\_internal" move "{app_dir}\\_internal" "{app_dir}\\_backup\\_internal" >nul
if exist "{app_dir}\\InstagramDMPro.exe" move "{app_dir}\\InstagramDMPro.exe" "{app_dir}\\_backup\\InstagramDMPro.exe" >nul

REM 새 파일 복사 (data 폴더 제외)
xcopy "{source_dir}\\_internal" "{app_dir}\\_internal" /E /I /Y >nul 2>&1
if exist "{source_dir}\\InstagramDMPro.exe" copy /Y "{source_dir}\\InstagramDMPro.exe" "{app_dir}\\InstagramDMPro.exe" >nul

REM 앱 재실행
echo 업데이트 완료! 앱을 재시작합니다...
start "" "{app_dir}\\InstagramDMPro.exe"

REM 정리
timeout /t 5 /nobreak >nul
if exist "{app_dir}\\_backup" rmdir /s /q "{app_dir}\\_backup"
if exist "{extract_dir}" rmdir /s /q "{extract_dir}"
if exist "{zip_path}" del /f /q "{zip_path}"
del /f /q "%~f0"
"""
        bat_path.write_text(bat_content, encoding="utf-8")

        # 배치 스크립트 실행 (독립 프로세스)
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
        log.info("업데이트 배치 스크립트 실행. 앱을 종료합니다.")
        return True

    except Exception as e:
        log.error(f"업데이트 적용 실패: {e}")
        return False


def apply_update_macos(dmg_path: Path) -> bool:
    """macOS: DMG 파일을 Finder에서 열기 (사용자가 직접 교체)."""
    try:
        subprocess.Popen(["open", str(dmg_path)])
        log.info(f"DMG 파일 열기: {dmg_path}")
        return True
    except Exception as e:
        log.error(f"DMG 열기 실패: {e}")
        return False


def apply_update(file_path: Path) -> bool:
    """OS에 맞는 업데이트 적용."""
    if platform.system() == "Windows":
        return apply_update_windows(file_path)
    elif platform.system() == "Darwin":
        return apply_update_macos(file_path)
    return False
