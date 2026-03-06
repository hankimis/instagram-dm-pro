"""
Instagram Service - 메인 진입점
실행: python -m insta_service.main
"""
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (PyInstaller 호환)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from insta_service.db.models import init_db
from insta_service.utils.logger import log


def main():
    log.info("=" * 50)
    log.info("Instagram Service 시작")
    log.info("=" * 50)

    # DB 초기화
    init_db()
    log.info("데이터베이스 초기화 완료")

    # DB 자동 백업
    from insta_service.utils.backup import backup_database
    backup_database()

    # 미완료 크롤링 작업 리셋
    from insta_service.db import repository as repo
    repo.reset_running_crawl_jobs()

    # 대시보드 실행
    from insta_service.ui.dashboard import run_dashboard
    run_dashboard()


if __name__ == "__main__":
    main()
