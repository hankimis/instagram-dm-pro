import logging
import logging.handlers
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque

from insta_service.config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

MAX_LOG_DAYS = 30

# 최근 로그를 메모리에 보관 (대시보드 실시간 표시용)
_log_buffer: deque = deque(maxlen=500)


def get_log_buffer() -> list[str]:
    return list(_log_buffer)


def cleanup_old_logs():
    """MAX_LOG_DAYS일보다 오래된 로그 파일을 삭제한다."""
    cutoff = datetime.now() - timedelta(days=MAX_LOG_DAYS)
    for f in LOG_DIR.glob("*.log*"):
        try:
            if f.stat().st_mtime < cutoff.timestamp():
                f.unlink()
        except Exception:
            pass


class BufferHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        _log_buffer.append(msg)


def setup_logger(name: str = "insta_service") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s - %(message)s", datefmt="%H:%M:%S")

    # 콘솔
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # 파일 (일별 로테이션, 30일 보관)
    log_file = LOG_DIR / "insta_service.log"
    fh = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=MAX_LOG_DAYS,
        encoding="utf-8",
    )
    fh.suffix = "%Y-%m-%d"
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 메모리 버퍼 (대시보드용)
    bh = BufferHandler()
    bh.setLevel(logging.INFO)
    bh.setFormatter(fmt)
    logger.addHandler(bh)

    # 시작 시 오래된 로그 정리
    cleanup_old_logs()

    return logger


log = setup_logger()
