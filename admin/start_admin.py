"""
어드민 서버 시작 스크립트
- 자동으로 가상환경 생성 + 패키지 설치
- 더블클릭 또는 python3 admin/start_admin.py 로 실행
"""
import subprocess
import sys
import os
import platform

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

VENV_DIR = os.path.join(ROOT, "venv_admin")


def get_venv_python():
    if platform.system() == "Windows":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python3")


def is_running_in_venv():
    return sys.executable == os.path.abspath(get_venv_python())


def setup_venv():
    venv_python = get_venv_python()

    if not os.path.exists(venv_python):
        print("=" * 50)
        print("  어드민 서버: 환경을 자동 설정합니다")
        print("  (1~2분 소요, 한 번만 실행됩니다)")
        print("=" * 50)
        print()
        print("[1/2] 가상환경 생성 중...")
        subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])
        print("      완료!")
    else:
        try:
            subprocess.check_call(
                [venv_python, "-c", "import fastapi; import uvicorn"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return
        except subprocess.CalledProcessError:
            pass

    print("[2/2] 필요한 패키지 설치 중...")
    subprocess.check_call(
        [venv_python, "-m", "pip", "install", "--upgrade", "pip"],
        stdout=subprocess.DEVNULL,
    )
    req_file = os.path.join(ROOT, "requirements.txt")
    subprocess.check_call([venv_python, "-m", "pip", "install", "-r", req_file])
    print()
    print("      설치 완료!")
    print("=" * 50)
    print()


def main():
    if not is_running_in_venv():
        setup_venv()
        venv_python = get_venv_python()
        print("어드민 서버를 시작합니다...")
        print("접속: http://localhost:9090/docs")
        print("기본 계정: admin@admin.com / admin1234")
        print()
        os.execv(venv_python, [venv_python, os.path.abspath(__file__)])

    sys.path.insert(0, ROOT)
    from admin_server import app
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090)


if __name__ == "__main__":
    main()
