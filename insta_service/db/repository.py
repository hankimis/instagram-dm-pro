from datetime import datetime
from contextlib import contextmanager

from sqlalchemy import func

from insta_service.db.models import (
    SessionLocal, User, UserHashtag, UserProfile,
    InstagramAccount, Proxy, CrawlJob, DmTemplate, DmHistory, LicenseInfo,
    Blacklist,
)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Users ──

def add_user(username: str, hashtag: str) -> bool:
    """유저를 추가한다. 이미 존재하면 해시태그 매핑만 추가. 새 유저면 True 반환."""
    with get_session() as s:
        user = s.query(User).filter_by(username=username).first()
        if user:
            existing = s.query(UserHashtag).filter_by(user_id=user.id, hashtag=hashtag).first()
            if not existing:
                s.add(UserHashtag(user_id=user.id, hashtag=hashtag))
            return False
        user = User(username=username, first_seen_hashtag=hashtag)
        s.add(user)
        s.flush()
        s.add(UserHashtag(user_id=user.id, hashtag=hashtag))
        return True


def get_all_usernames() -> set[str]:
    with get_session() as s:
        rows = s.query(User.username).all()
        return {r[0] for r in rows}


def get_users(offset: int = 0, limit: int = 100, hashtag: str | None = None,
              analyzed: bool | None = None, dm_sent: bool | None = None,
              sort_by: str = "crawled_at", sort_desc: bool = True,
              search: str | None = None) -> list[dict]:
    with get_session() as s:
        q = s.query(User)
        if hashtag:
            q = q.join(UserHashtag).filter(UserHashtag.hashtag == hashtag)
        if analyzed is not None:
            q = q.filter(User.is_analyzed == analyzed)
        if dm_sent is not None:
            q = q.filter(User.is_dm_sent == dm_sent)
        if search:
            q = q.filter(User.username.ilike(f"%{search}%"))
        col = getattr(User, sort_by, User.crawled_at)
        q = q.order_by(col.desc() if sort_desc else col.asc())
        users = q.offset(offset).limit(limit).all()
        results = []
        for u in users:
            profile = s.query(UserProfile).filter_by(user_id=u.id).first()
            results.append({
                "id": u.id, "username": u.username, "first_seen_hashtag": u.first_seen_hashtag,
                "crawled_at": u.crawled_at.isoformat() if u.crawled_at else None,
                "is_analyzed": u.is_analyzed, "is_dm_sent": u.is_dm_sent,
                "display_name": profile.display_name if profile else None,
            })
        return results


def mark_users_dm_sent(user_ids: list[int], sent: bool = True):
    """유저들의 DM 발송 상태를 업데이트한다."""
    with get_session() as s:
        s.query(User).filter(User.id.in_(user_ids)).update(
            {User.is_dm_sent: sent}, synchronize_session="fetch"
        )


def delete_users(user_ids: list[int]) -> int:
    """유저 및 관련 데이터(프로필, 해시태그, DM 이력)를 삭제한다."""
    with get_session() as s:
        s.query(UserProfile).filter(UserProfile.user_id.in_(user_ids)).delete(synchronize_session="fetch")
        s.query(UserHashtag).filter(UserHashtag.user_id.in_(user_ids)).delete(synchronize_session="fetch")
        s.query(DmHistory).filter(DmHistory.user_id.in_(user_ids)).delete(synchronize_session="fetch")
        count = s.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session="fetch")
        return count


def get_user_count(hashtag: str | None = None, dm_sent: bool | None = None,
                   search: str | None = None) -> int:
    with get_session() as s:
        q = s.query(func.count(User.id))
        if hashtag:
            q = q.join(UserHashtag).filter(UserHashtag.hashtag == hashtag)
        if dm_sent is not None:
            q = q.filter(User.is_dm_sent == dm_sent)
        if search:
            q = q.filter(User.username.ilike(f"%{search}%"))
        return q.scalar() or 0


def get_user_detail(user_id: int) -> dict | None:
    """유저 상세 정보 (프로필 포함)를 반환한다."""
    with get_session() as s:
        user = s.query(User).get(user_id)
        if not user:
            return None
        data = {
            "id": user.id, "username": user.username,
            "first_seen_hashtag": user.first_seen_hashtag,
            "crawled_at": user.crawled_at.isoformat() if user.crawled_at else None,
            "is_analyzed": user.is_analyzed, "is_dm_sent": user.is_dm_sent,
        }
        profile = s.query(UserProfile).filter_by(user_id=user.id).first()
        if profile:
            data.update({
                "followers_count": profile.followers_count,
                "following_count": profile.following_count,
                "posts_count": profile.posts_count,
                "bio": profile.bio,
                "is_private": profile.is_private,
                "is_verified": profile.is_verified,
                "analyzed_at": profile.analyzed_at.isoformat() if profile.analyzed_at else None,
            })
        # 해시태그 목록
        hashtags = s.query(UserHashtag.hashtag).filter_by(user_id=user.id).all()
        data["hashtags"] = [h[0] for h in hashtags]
        return data


def get_hashtag_stats() -> list[dict]:
    with get_session() as s:
        rows = (
            s.query(UserHashtag.hashtag, func.count(UserHashtag.id))
            .group_by(UserHashtag.hashtag)
            .order_by(func.count(UserHashtag.id).desc())
            .all()
        )
        return [{"hashtag": r[0], "count": r[1]} for r in rows]


# ── Proxies ──

def get_all_proxies() -> list[dict]:
    with get_session() as s:
        proxies = s.query(Proxy).filter_by(is_active=True).all()
        return [
            {"id": p.id, "ip": p.ip, "port": p.port,
             "username": p.username, "password": p.password,
             "is_active": p.is_active, "response_time_ms": p.response_time_ms}
            for p in proxies
        ]


def upsert_proxy(ip: str, port: int, username: str = None, password: str = None) -> int:
    with get_session() as s:
        p = s.query(Proxy).filter_by(ip=ip, port=port).first()
        if p:
            p.username = username
            p.password = password
            return p.id
        p = Proxy(ip=ip, port=port, username=username, password=password)
        s.add(p)
        s.flush()
        return p.id


# ── Instagram Accounts ──

def add_account(username: str, password_encrypted: str, account_type: str = "crawl",
                proxy_id: int | None = None) -> int:
    with get_session() as s:
        acc = InstagramAccount(
            username=username, password_encrypted=password_encrypted,
            account_type=account_type, proxy_id=proxy_id,
        )
        s.add(acc)
        s.flush()
        return acc.id


def get_accounts(account_type: str | None = None) -> list[dict]:
    with get_session() as s:
        q = s.query(InstagramAccount)
        if account_type:
            # "both" 타입 계정도 crawl/dm 요청에 포함
            from sqlalchemy import or_
            q = q.filter(or_(
                InstagramAccount.account_type == account_type,
                InstagramAccount.account_type == "both",
            ))
        accs = q.all()
        return [
            {"id": a.id, "username": a.username, "account_type": a.account_type,
             "proxy_id": a.proxy_id, "is_active": a.is_active, "status": a.status,
             "daily_dm_limit": a.daily_dm_limit, "dm_sent_today": a.dm_sent_today,
             "chrome_profile_path": a.chrome_profile_path}
            for a in accs
        ]


def update_account_status(account_id: int, status: str):
    with get_session() as s:
        acc = s.query(InstagramAccount).get(account_id)
        if acc:
            acc.status = status


def update_account(account_id: int, **kwargs):
    """계정 정보를 업데이트한다. (account_type, proxy_id, is_active, daily_dm_limit 등)"""
    with get_session() as s:
        acc = s.query(InstagramAccount).get(account_id)
        if acc:
            for k, v in kwargs.items():
                setattr(acc, k, v)


def delete_accounts(account_ids: list[int]):
    """계정들을 삭제한다."""
    with get_session() as s:
        s.query(InstagramAccount).filter(InstagramAccount.id.in_(account_ids)).delete(
            synchronize_session="fetch"
        )


# ── Crawl Jobs ──

def create_crawl_job(hashtag: str, target_count: int, account_id: int | None = None) -> int:
    with get_session() as s:
        job = CrawlJob(hashtag=hashtag, target_count=target_count, account_id=account_id)
        s.add(job)
        s.flush()
        return job.id


def update_crawl_job(job_id: int, **kwargs):
    with get_session() as s:
        job = s.query(CrawlJob).get(job_id)
        if job:
            for k, v in kwargs.items():
                setattr(job, k, v)


def reset_running_crawl_jobs():
    """시작 시 'running' 상태 작업을 'interrupted'로 리셋한다."""
    with get_session() as s:
        count = s.query(CrawlJob).filter_by(status="running").update(
            {"status": "interrupted"}, synchronize_session="fetch"
        )
        if count:
            from insta_service.utils.logger import log
            log.info(f"{count}개 미완료 크롤링 작업을 'interrupted'로 리셋")
    return count


def get_crawl_job_by_id(job_id: int) -> dict | None:
    with get_session() as s:
        j = s.query(CrawlJob).get(job_id)
        if not j:
            return None
        return {"id": j.id, "hashtag": j.hashtag, "target_count": j.target_count,
                "collected_count": j.collected_count, "status": j.status,
                "account_id": j.account_id, "error_message": j.error_message,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None}


def get_crawl_jobs(status: str | None = None, limit: int = 20) -> list[dict]:
    with get_session() as s:
        q = s.query(CrawlJob)
        if status:
            q = q.filter_by(status=status)
        jobs = q.order_by(CrawlJob.created_at.desc()).limit(limit).all()
        return [
            {"id": j.id, "hashtag": j.hashtag, "target_count": j.target_count,
             "collected_count": j.collected_count, "status": j.status,
             "account_id": j.account_id, "error_message": j.error_message,
             "started_at": j.started_at.isoformat() if j.started_at else None,
             "completed_at": j.completed_at.isoformat() if j.completed_at else None}
            for j in jobs
        ]


# ── DM Templates ──

def add_dm_template(name: str, message_body: str, image_path: str | None = None) -> int:
    with get_session() as s:
        t = DmTemplate(name=name, message_body=message_body, image_path=image_path)
        s.add(t)
        s.flush()
        return t.id


def update_dm_template(template_id: int, **kwargs):
    with get_session() as s:
        t = s.query(DmTemplate).get(template_id)
        if t:
            for k, v in kwargs.items():
                setattr(t, k, v)


def get_dm_templates() -> list[dict]:
    with get_session() as s:
        templates = s.query(DmTemplate).all()
        return [
            {"id": t.id, "name": t.name, "message_body": t.message_body,
             "image_path": t.image_path}
            for t in templates
        ]


def delete_dm_template(template_id: int):
    with get_session() as s:
        t = s.query(DmTemplate).get(template_id)
        if t:
            s.delete(t)


# ── DM History ──

def add_dm_history(user_id: int, sender_account_id: int, message_text: str,
                   template_id: int | None = None, status: str = "sent") -> int:
    with get_session() as s:
        h = DmHistory(
            user_id=user_id, sender_account_id=sender_account_id,
            message_text=message_text, template_id=template_id, status=status,
        )
        s.add(h)
        s.flush()
        return h.id


def get_dm_history(offset: int = 0, limit: int = 50, status: str | None = None,
                   search: str | None = None) -> list[dict]:
    """DM 발송 이력을 조회한다."""
    with get_session() as s:
        q = s.query(DmHistory).join(User, DmHistory.user_id == User.id)
        if status:
            q = q.filter(DmHistory.status == status)
        if search:
            q = q.filter(User.username.ilike(f"%{search}%"))
        q = q.order_by(DmHistory.sent_at.desc())
        total = q.count()
        items = q.offset(offset).limit(limit).all()
        result = []
        for h in items:
            user = s.query(User).get(h.user_id)
            result.append({
                "id": h.id,
                "username": user.username if user else f"(ID:{h.user_id})",
                "message_preview": (h.message_text or "")[:50],
                "status": h.status,
                "sent_at": h.sent_at.isoformat() if h.sent_at else None,
                "sender_account_id": h.sender_account_id,
            })
        return result, total


def get_dm_history_count(status: str | None = None, search: str | None = None) -> int:
    with get_session() as s:
        q = s.query(func.count(DmHistory.id))
        if status:
            q = q.filter(DmHistory.status == status)
        if search:
            q = q.join(User, DmHistory.user_id == User.id).filter(User.username.ilike(f"%{search}%"))
        return q.scalar() or 0


def get_dm_count_today(account_id: int) -> int:
    """오늘 해당 계정이 발송한 DM 수를 반환한다."""
    from datetime import date
    today_start = datetime.combine(date.today(), datetime.min.time())
    with get_session() as s:
        return s.query(func.count(DmHistory.id)).filter(
            DmHistory.sender_account_id == account_id,
            DmHistory.sent_at >= today_start,
            DmHistory.status == "sent",
        ).scalar() or 0


def get_failed_dm_targets() -> list[dict]:
    """실패한 DM의 대상 유저 목록 (재시도용). 중복 제거."""
    with get_session() as s:
        failed = (
            s.query(DmHistory)
            .filter_by(status="failed")
            .order_by(DmHistory.sent_at.desc())
            .all()
        )
        seen = set()
        targets = []
        for h in failed:
            if h.user_id in seen:
                continue
            seen.add(h.user_id)
            user = s.query(User).get(h.user_id)
            if user:
                targets.append({"user_id": user.id, "username": user.username})
        return targets


def get_dm_stats() -> dict:
    with get_session() as s:
        total = s.query(func.count(DmHistory.id)).scalar() or 0
        sent = s.query(func.count(DmHistory.id)).filter_by(status="sent").scalar() or 0
        failed = s.query(func.count(DmHistory.id)).filter_by(status="failed").scalar() or 0
        return {"total": total, "sent": sent, "failed": failed}


# ── Blacklist ──

def get_blacklist() -> list[dict]:
    with get_session() as s:
        items = s.query(Blacklist).order_by(Blacklist.created_at.desc()).all()
        return [{"id": b.id, "username": b.username, "reason": b.reason,
                 "created_at": b.created_at.isoformat() if b.created_at else None}
                for b in items]


def get_blacklisted_usernames() -> set[str]:
    with get_session() as s:
        rows = s.query(Blacklist.username).all()
        return {r[0].lower() for r in rows}


def add_to_blacklist(username: str, reason: str = "") -> bool:
    """블랙리스트에 추가. 이미 존재하면 False 반환."""
    username = username.strip().lstrip("@").lower()
    if not username:
        return False
    with get_session() as s:
        existing = s.query(Blacklist).filter(
            func.lower(Blacklist.username) == username
        ).first()
        if existing:
            return False
        s.add(Blacklist(username=username, reason=reason))
        return True


def add_bulk_to_blacklist(usernames: list[str], reason: str = "") -> int:
    """여러 유저를 블랙리스트에 일괄 추가. 추가된 수 반환."""
    added = 0
    with get_session() as s:
        existing = {r[0] for r in s.query(func.lower(Blacklist.username)).all()}
        for raw in usernames:
            uname = raw.strip().lstrip("@").lower()
            if uname and uname not in existing:
                s.add(Blacklist(username=uname, reason=reason))
                existing.add(uname)
                added += 1
    return added


def remove_from_blacklist(blacklist_ids: list[int]):
    with get_session() as s:
        s.query(Blacklist).filter(Blacklist.id.in_(blacklist_ids)).delete(
            synchronize_session="fetch"
        )


# ── License ──

def get_license() -> dict | None:
    with get_session() as s:
        lic = s.query(LicenseInfo).first()
        if not lic:
            return None
        return {
            "license_key": lic.license_key,
            "company_name": lic.company_name,
            "plan": lic.plan,
            "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
            "max_crawl_accounts": lic.max_crawl_accounts,
            "max_dm_accounts": lic.max_dm_accounts,
            "max_daily_dm": lic.max_daily_dm,
            "max_hashtags": lic.max_hashtags,
            "can_schedule": lic.can_schedule,
            "can_analyze": lic.can_analyze,
            "can_export": lic.can_export,
        }


def save_license(license_key: str, company_name: str, expires_at: datetime,
                 plan: str = "basic", **limits):
    with get_session() as s:
        lic = s.query(LicenseInfo).first()
        fields = {
            "license_key": license_key,
            "company_name": company_name,
            "plan": plan,
            "expires_at": expires_at,
            "max_crawl_accounts": limits.get("max_crawl_accounts", 1),
            "max_dm_accounts": limits.get("max_dm_accounts", 1),
            "max_daily_dm": limits.get("max_daily_dm", 50),
            "max_hashtags": limits.get("max_hashtags", 5),
            "can_schedule": limits.get("can_schedule", False),
            "can_analyze": limits.get("can_analyze", False),
            "can_export": limits.get("can_export", False),
        }
        if lic:
            for k, v in fields.items():
                setattr(lic, k, v)
        else:
            s.add(LicenseInfo(activated_at=datetime.utcnow(), **fields))


def update_heartbeat():
    with get_session() as s:
        lic = s.query(LicenseInfo).first()
        if lic:
            lic.last_heartbeat = datetime.utcnow()
