import shutil
from datetime import datetime
from pathlib import Path

from insta_service.config import DB_PATH, DATA_DIR
from insta_service.utils.logger import log

BACKUP_DIR = DATA_DIR / "backups"
MAX_BACKUPS = 7


def backup_database() -> Path | None:
    """SQLite DB를 백업한다. 최근 MAX_BACKUPS개만 유지."""
    if not DB_PATH.exists():
        log.warning("백업 대상 DB 파일이 없습니다.")
        return None

    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"insta_service_{timestamp}.db"

    shutil.copy2(DB_PATH, backup_path)
    log.info(f"DB 백업 완료: {backup_path.name}")

    # 오래된 백업 삭제 (최근 MAX_BACKUPS개만 유지)
    backups = sorted(BACKUP_DIR.glob("insta_service_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[MAX_BACKUPS:]:
        old.unlink()
        log.debug(f"오래된 백업 삭제: {old.name}")

    return backup_path
