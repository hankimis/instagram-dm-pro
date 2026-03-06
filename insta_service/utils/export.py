import pandas as pd
from datetime import datetime

from sqlalchemy.orm import joinedload

from insta_service.db.models import User, UserHashtag
from insta_service.db.repository import get_session
from insta_service.config import DATA_DIR
from insta_service.utils.logger import log

EXPORT_DIR = DATA_DIR / "exports"
EXPORT_DIR.mkdir(exist_ok=True)


def _query_users(session, hashtag: str | None = None):
    """내보내기용 유저 쿼리 (공통)."""
    q = session.query(User).options(joinedload(User.profile), joinedload(User.hashtags))
    if hashtag:
        q = q.join(UserHashtag).filter(UserHashtag.hashtag == hashtag)
    return q.all()


def export_users_excel(hashtag: str | None = None, include_profile: bool = True) -> str:
    """수집된 유저 데이터를 Excel로 내보낸다. 파일 경로를 반환."""
    with get_session() as session:
        users = _query_users(session, hashtag)

        rows = []
        for u in users:
            row = {
                "username": u.username,
                "first_seen_hashtag": u.first_seen_hashtag,
                "crawled_at": u.crawled_at.strftime("%Y-%m-%d") if u.crawled_at else "",
                "hashtags": ", ".join(h.hashtag for h in u.hashtags),
            }
            if include_profile and u.profile:
                p = u.profile
                row.update({
                    "followers": p.followers_count,
                    "following": p.following_count,
                    "posts": p.posts_count,
                    "bio": p.bio or "",
                    "is_private": p.is_private,
                    "is_verified": p.is_verified,
                    "analyzed_at": p.analyzed_at.strftime("%Y-%m-%d") if p.analyzed_at else "",
                })
            row["dm_sent"] = u.is_dm_sent
            rows.append(row)

        df = pd.DataFrame(rows)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tag_suffix = f"_{hashtag}" if hashtag else ""
        filename = f"users{tag_suffix}_{ts}.xlsx"
        filepath = EXPORT_DIR / filename
        df.to_excel(filepath, index=False)
        log.info(f"Excel 내보내기 완료: {filename} ({len(rows)}명)")
        return str(filepath)


def export_users_csv(hashtag: str | None = None) -> str:
    """수집된 유저 데이터를 CSV로 내보낸다."""
    with get_session() as session:
        users = _query_users(session, hashtag)

        rows = [
            {
                "username": u.username,
                "hashtag": u.first_seen_hashtag,
                "crawled_at": u.crawled_at.strftime("%Y-%m-%d") if u.crawled_at else "",
            }
            for u in users
        ]

        df = pd.DataFrame(rows)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"users_{ts}.csv"
        filepath = EXPORT_DIR / filename
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        log.info(f"CSV 내보내기 완료: {filename} ({len(rows)}명)")
        return str(filepath)
