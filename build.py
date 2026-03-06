"""
PyInstaller 빌드 스크립트
실행: python build.py

Windows: .exe 파일 생성
macOS: .app 번들 생성
"""
import subprocess
import sys
import platform

APP_NAME = "InstaService"
MAIN_SCRIPT = "start.py"


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",              # 단일 디렉터리 모드 (--onefile보다 안정적)
        "--windowed",            # 콘솔 창 숨기기
        "--noconfirm",           # 기존 빌드 덮어쓰기
        "--add-data", "insta_service:insta_service",
        "--add-data", "config.yml:.",
        "--add-data", "proxies.txt:.",
        "--hidden-import", "nicegui",
        "--hidden-import", "sqlalchemy",
        "--hidden-import", "cryptography",
        "--hidden-import", "engineio.async_drivers.aiohttp",
        "--collect-all", "nicegui",
        MAIN_SCRIPT,
    ]

    if platform.system() == "Darwin":
        cmd.extend(["--osx-bundle-identifier", "com.instaservice.app"])

    print(f"빌드 시작: {' '.join(cmd)}")
    subprocess.check_call(cmd)
    print(f"\n빌드 완료! dist/{APP_NAME}/ 폴더를 확인하세요.")
    print(f"실행: dist/{APP_NAME}/{APP_NAME}" + (".exe" if platform.system() == "Windows" else ""))


if __name__ == "__main__":
    build()
