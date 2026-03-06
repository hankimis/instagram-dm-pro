"""
기존 instagram_users.xlsx 데이터를 SQLite DB로 마이그레이션한다.
실행: python -m insta_service.scripts.migrate_xlsx
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from insta_service.db.models import init_db
from insta_service.db import repository as repo
from insta_service.config import BASE_DIR

XLSX_PATH = BASE_DIR / "instagram_users.xlsx"


def migrate():
    init_db()

    if not XLSX_PATH.exists():
        print(f"파일을 찾을 수 없습니다: {XLSX_PATH}")
        return

    df = pd.read_excel(XLSX_PATH)
    print(f"총 {len(df)}개 레코드 발견")

    added = 0
    skipped = 0
    for _, row in df.iterrows():
        username = str(row.get("username", "")).strip()
        hashtag = str(row.get("hashtag", "")).strip()
        if not username or username == "nan":
            skipped += 1
            continue

        is_new = repo.add_user(username, hashtag)
        if is_new:
            added += 1
        else:
            skipped += 1

    print(f"마이그레이션 완료: {added}명 추가, {skipped}명 스킵 (중복)")


if __name__ == "__main__":
    migrate()
