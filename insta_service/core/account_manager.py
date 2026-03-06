import os
import stat

from cryptography.fernet import Fernet
from pathlib import Path

from insta_service.config import CHROME_PROFILES_DIR, DATA_DIR
from insta_service.db import repository as repo
from insta_service.utils.logger import log

# 암호화 키 파일 (최초 1회 자동 생성)
_KEY_FILE = DATA_DIR / ".secret_key"


def _get_fernet() -> Fernet:
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_bytes()
    else:
        key = Fernet.generate_key()
        _KEY_FILE.write_bytes(key)
        # 소유자만 읽기/쓰기 가능하도록 권한 설정
        try:
            os.chmod(_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass
    return Fernet(key)


def encrypt_password(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode()).decode()


def register_account(username: str, password: str, account_type: str = "crawl",
                     proxy_id: int | None = None) -> int:
    """인스타 계정을 등록한다."""
    enc = encrypt_password(password)
    profile_path = str(CHROME_PROFILES_DIR / username)
    Path(profile_path).mkdir(parents=True, exist_ok=True)

    account_id = repo.add_account(
        username=username,
        password_encrypted=enc,
        account_type=account_type,
        proxy_id=proxy_id,
    )
    log.info(f"계정 등록: @{username} (타입: {account_type})")
    return account_id


def get_accounts(account_type: str | None = None) -> list[dict]:
    return repo.get_accounts(account_type)


def get_profile_path(username: str) -> str:
    """계정별 Chrome 프로필 경로를 반환한다."""
    path = CHROME_PROFILES_DIR / username
    path.mkdir(parents=True, exist_ok=True)
    return str(path)
