"""
크롤링/DM 예약 스케줄러.
APScheduler BackgroundScheduler를 사용하여 예약 작업을 실행한다.
"""
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

from insta_service.db import repository as repo
from insta_service.utils.logger import log

_scheduler = None
_scheduler_lock = threading.Lock()


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = BackgroundScheduler(timezone="Asia/Seoul")
            _scheduler.start()
            log.info("APScheduler 시작")
    return _scheduler


def schedule_crawl(run_at: datetime, hashtag: str, target_count: int,
                   account_id: int, get_driver_fn, on_complete=None) -> str:
    """
    크롤링을 예약한다.
    get_driver_fn: account_id를 받아 driver를 반환하는 함수
    반환: job_id (스케줄러 내부 ID)
    """
    from insta_service.core.crawler import HashtagCrawler

    def run_scheduled_crawl():
        log.info(f"[예약] 크롤링 시작: #{hashtag} (목표: {target_count})")
        driver = get_driver_fn(account_id)
        if not driver:
            log.error(f"[예약] 드라이버 없음 (account_id={account_id})")
            return

        job_id = repo.create_crawl_job(hashtag, target_count, account_id)
        crawler = HashtagCrawler(driver, account_id=account_id)
        result = crawler.crawl(hashtag, target_count, job_id)
        log.info(f"[예약] 크롤링 완료: #{hashtag}, 수집: {len(result.collected)}명")

        if on_complete:
            try:
                on_complete(result)
            except Exception as e:
                log.debug(f"[예약] on_complete 콜백 오류: {e}")

    scheduler = get_scheduler()
    sched_job = scheduler.add_job(
        run_scheduled_crawl,
        trigger=DateTrigger(run_date=run_at),
        id=f"crawl_{hashtag}_{run_at.timestamp():.0f}",
        replace_existing=True,
    )
    log.info(f"크롤링 예약 완료: #{hashtag} @ {run_at}")
    return sched_job.id


def get_scheduled_jobs() -> list[dict]:
    """현재 예약된 작업 목록을 반환한다."""
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return jobs


def cancel_scheduled_job(job_id: str) -> bool:
    """예약 작업을 취소한다."""
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id)
        log.info(f"예약 작업 취소: {job_id}")
        return True
    except Exception:
        return False


def shutdown_scheduler():
    global _scheduler
    with _scheduler_lock:
        if _scheduler:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            log.info("APScheduler 종료")
