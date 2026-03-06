"""
tufup 기반 자동 업데이트 모듈.
GitHub Pages(메타데이터) + GitHub Releases(타겟 아카이브)를 사용한 보안 업데이트.
tufup 메타데이터가 아직 없으면 GitHub Releases API로 폴백.
"""
import os
import sys
import shutil
import platform
import subprocess
import zipfile
from pathlib import Path

import requests

from insta_service.config import BASE_DIR, DATA_DIR
from insta_service.utils.logger import log

GITHUB_OWNER = "hankimis"
GITHUB_REPO = "instagram-dm-pro"

APP_NAME = "InstagramDMPro"

# tufup 메타데이터: GitHub Pages
METADATA_BASE_URL = f"https://{GITHUB_OWNER}.github.io/{GITHUB_REPO}/metadata/"
# tufup 타겟(아카이브/패치): GitHub Releases 고정 태그
TARGET_BASE_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
    f"/releases/download/tufup-targets/"
)

# 로컬 캐시
METADATA_DIR = DATA_DIR / "tuf_metadata"
TARGET_DIR = DATA_DIR / "tuf_targets"
UPDATE_DIR = DATA_DIR / "updates"


def get_current_version() -> str:
    from insta_service.license.validator import APP_VERSION
    return APP_VERSION


def _ensure_dirs():
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    TARGET_DIR.mkdir(parents=True, exist_ok=True)


def _bootstrap_root():
    """번들된 root.json을 메타데이터 캐시에 복사 (최초 1회)."""
    dst = METADATA_DIR / "root.json"
    if dst.exists():
        return True

    if getattr(sys, "frozen", False):
        candidates = [
            Path(sys._MEIPASS) / "root.json",
            Path(sys.executable).parent / "root.json",
            Path(sys._MEIPASS) / "assets" / "root.json",
        ]
    else:
        project_root = Path(__file__).resolve().parent.parent.parent
        candidates = [
            project_root / "assets" / "root.json",
            project_root / "root.json",
        ]

    for src in candidates:
        if src.exists():
            shutil.copy(src, dst)
            log.debug(f"root.json 복사: {src} -> {dst}")
            return True

    log.debug("root.json을 찾을 수 없음 - tufup 비활성")
    return False


# ------------------------------------------------------------------
# tufup 업데이트 확인
# ------------------------------------------------------------------

def _check_tufup() -> dict | None:
    """tufup 클라이언트로 업데이트를 확인한다."""
    try:
        from tufup.client import Client

        _ensure_dirs()
        if not _bootstrap_root():
            return None

        client = Client(
            app_name=APP_NAME,
            app_install_dir=BASE_DIR,
            current_version=get_current_version(),
            metadata_dir=METADATA_DIR,
            metadata_base_url=METADATA_BASE_URL,
            target_dir=TARGET_DIR,
            target_base_url=TARGET_BASE_URL,
            refresh_required=False,
        )

        new_update = client.check_for_updates(pre=None)
        if not new_update:
            return None

        info = {
            "version": str(new_update.version),
            "changes": [],
            "size": 0,
            "_client": client,
        }
        if new_update.custom:
            info["changes"] = new_update.custom.get("changes", [])
        log.info(f"tufup 새 버전 발견: v{info['version']}")
        return info

    except Exception as e:
        log.debug(f"tufup 확인 실패: {e}")
        return None


# ------------------------------------------------------------------
# GitHub Releases API 폴백
# ------------------------------------------------------------------

def _check_github_fallback() -> dict | None:
    """GitHub Releases API로 업데이트를 확인한다 (tufup 폴백)."""
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest",
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        latest_tag = data.get("tag_name", "")
        latest_version = latest_tag.lstrip("v")
        current = get_current_version()

        from packaging.version import Version
        if Version(latest_version) <= Version(current):
            return None

        asset = _find_github_asset(data.get("assets", []))
        if not asset:
            return None

        return {
            "version": latest_version,
            "download_url": asset["browser_download_url"],
            "size": asset.get("size", 0),
            "name": asset["name"],
            "release_notes": data.get("body", ""),
            "changes": [],
            "_fallback": True,
        }
    except Exception as e:
        log.debug(f"GitHub API 폴백 확인 실패: {e}")
        return None


def _find_github_asset(assets: list) -> dict | None:
    system = platform.system()
    for asset in assets:
        name = asset.get("name", "").lower()
        if system == "Windows" and "windows" in name and name.endswith(".zip"):
            return asset
        if system == "Darwin" and "macos" in name and name.endswith(".dmg"):
            return asset
    return None


# ------------------------------------------------------------------
# 통합 API
# ------------------------------------------------------------------

def check_for_update() -> dict | None:
    """업데이트를 확인한다. tufup 우선, 실패 시 GitHub API 폴백."""
    result = _check_tufup()
    if result:
        return result
    return _check_github_fallback()


def download_and_apply(update_info: dict, progress_callback=None) -> bool:
    """업데이트를 다운로드하고 적용한다."""
    if update_info.get("_fallback"):
        return _download_fallback(update_info, progress_callback)
    return _apply_tufup(update_info, progress_callback)


def _apply_tufup(update_info: dict, progress_callback=None) -> bool:
    """tufup 클라이언트로 업데이트를 적용한다."""
    client = update_info.get("_client")
    if not client:
        return False
    try:
        client.download_and_apply_update(
            skip_confirmation=True,
            progress_hook=progress_callback,
            purge_dst_dir=False,
            log_file_name="update_install.log",
        )
        log.info("tufup 업데이트 적용 완료")
        return True
    except Exception as e:
        log.error(f"tufup 업데이트 적용 실패: {e}")
        return False


# ------------------------------------------------------------------
# 폴백: GitHub Releases 직접 다운로드
# ------------------------------------------------------------------

def download_update(download_url: str, filename: str, progress_callback=None) -> Path:
    """폴백용: 파일을 직접 다운로드한다."""
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

    log.info(f"다운로드 완료: {dest} ({downloaded} bytes)")
    return dest


def _download_fallback(update_info: dict, progress_callback=None) -> bool:
    """GitHub Releases에서 직접 다운로드 + 적용."""
    try:
        file_path = download_update(
            update_info["download_url"],
            update_info["name"],
            progress_callback,
        )
        return apply_update(file_path)
    except Exception as e:
        log.error(f"폴백 업데이트 실패: {e}")
        return False


def apply_update(file_path: Path) -> bool:
    """OS에 맞는 업데이트 적용."""
    if platform.system() == "Windows":
        return _apply_windows_zip(file_path)
    elif platform.system() == "Darwin":
        return _apply_macos_dmg(file_path)
    return False


def _apply_windows_zip(zip_path: Path) -> bool:
    """Windows: zip 해제 후 배치 스크립트로 파일 교체 + 재시작."""
    try:
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        extract_dir = UPDATE_DIR / "extracted"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        contents = list(extract_dir.iterdir())
        source_dir = (
            contents[0] if len(contents) == 1 and contents[0].is_dir() else extract_dir
        )

        app_dir = Path(sys.executable).resolve().parent
        pid = os.getpid()

        bat_path = UPDATE_DIR / "_updater.bat"
        bat_content = f"""@echo off
chcp 65001 >nul
echo Updating...
taskkill /PID {pid} /F >nul 2>&1
timeout /t 3 /nobreak >nul
if exist "{app_dir}\\_internal" rmdir /s /q "{app_dir}\\_internal"
xcopy "{source_dir}\\_internal" "{app_dir}\\_internal" /E /I /Y >nul 2>&1
if exist "{source_dir}\\InstagramDMPro.exe" copy /Y "{source_dir}\\InstagramDMPro.exe" "{app_dir}\\InstagramDMPro.exe" >nul
echo Update complete. Restarting...
start "" "{app_dir}\\InstagramDMPro.exe"
timeout /t 5 /nobreak >nul
if exist "{extract_dir}" rmdir /s /q "{extract_dir}"
if exist "{zip_path}" del /f /q "{zip_path}"
del /f /q "%~f0"
"""
        bat_path.write_text(bat_content, encoding="utf-8")
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
        log.info("업데이트 배치 스크립트 실행")
        return True
    except Exception as e:
        log.error(f"Windows 업데이트 실패: {e}")
        return False


def _apply_macos_dmg(dmg_path: Path) -> bool:
    """macOS: DMG 파일을 Finder에서 열기."""
    try:
        subprocess.Popen(["open", str(dmg_path)])
        log.info(f"DMG 열기: {dmg_path}")
        return True
    except Exception as e:
        log.error(f"DMG 열기 실패: {e}")
        return False
