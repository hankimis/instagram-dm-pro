"""
Instagram Service 시작 스크립트
- 자동으로 가상환경(venv) 생성
- 필요한 패키지 자동 설치
- 프로그램 실행
"""
import subprocess
import sys
import os
import platform

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

VENV_DIR = os.path.join(ROOT, "venv_service")


def get_venv_python():
    """OS에 맞는 venv python 경로를 반환한다."""
    if platform.system() == "Windows":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python3")


def is_running_in_venv():
    """현재 venv 안에서 실행 중인지 확인."""
    return sys.executable == os.path.abspath(get_venv_python())


def setup_venv():
    """venv가 없으면 생성하고, 패키지를 설치한다."""
    venv_python = get_venv_python()

    # 1) venv 생성
    if not os.path.exists(venv_python):
        print("=" * 50)
        print("  최초 실행: 환경을 자동 설정합니다")
        print("  (1~2분 소요, 한 번만 실행됩니다)")
        print("=" * 50)
        print()
        print("[1/2] 가상환경 생성 중...")
        subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])
        print("      완료!")
    else:
        # venv는 있지만 패키지 확인
        try:
            subprocess.check_call(
                [venv_python, "-c", "import nicegui; import sqlalchemy; import yaml"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return  # 모든 패키지 설치됨
        except subprocess.CalledProcessError:
            pass  # 패키지 설치 필요

    # 2) 패키지 설치
    print("[2/2] 필요한 패키지 설치 중...")
    pip_cmd = [venv_python, "-m", "pip", "install", "--upgrade", "pip"]
    subprocess.check_call(pip_cmd, stdout=subprocess.DEVNULL)

    req_file = os.path.join(ROOT, "requirements_service.txt")
    subprocess.check_call([venv_python, "-m", "pip", "install", "-r", req_file])
    print()
    print("      설치 완료!")
    print("=" * 50)
    print()


def is_frozen():
    """PyInstaller 번들 안에서 실행 중인지 확인."""
    return getattr(sys, 'frozen', False)


def _fix_stdio():
    """PyInstaller --windowed 모드에서 sys.stdout/stderr가 None인 문제 수정."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")


def main():
    # PyInstaller 번들이면 venv 없이 바로 실행
    if is_frozen():
        _fix_stdio()
        sys.path.insert(0, ROOT)
        from insta_service.main import main as run
        run()
        return

    # venv 밖에서 실행된 경우 → venv 설정 후 venv python으로 재실행
    if not is_running_in_venv():
        setup_venv()

        # --setup-only: 설치 패키지 빌드 시 venv만 만들고 종료
        if "--setup-only" in sys.argv:
            print("환경 설정 완료! (setup-only 모드)")
            return

        venv_python = get_venv_python()
        print("프로그램을 시작합니다...\n")
        os.execv(venv_python, [venv_python, os.path.abspath(__file__)])
        # 여기서 현재 프로세스가 venv python으로 교체됨

    # venv 안에서 실행됨 → 프로그램 시작
    sys.path.insert(0, ROOT)
    from insta_service.main import main as run
    run()


if __name__ == "__main__":
    main()
