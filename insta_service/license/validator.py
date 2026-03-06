import hashlib
import json
import threading
import time
from datetime import datetime

import requests

from insta_service.db import repository as repo
from insta_service.utils.logger import log


def _load_admin_url() -> str:
    """config.yml에서 어드민 서버 URL을 읽는다."""
    try:
        from insta_service.config import cfg
        return cfg.get("admin_server_url", "https://insta-service-admin-production.up.railway.app/api")
    except Exception:
        return "http://localhost:9090/api"


ADMIN_SERVER_URL = _load_admin_url()

# 프로그램 버전
APP_VERSION = "1.0.0"


class LicenseValidator:
    """프로그램 시작 시 라이선스를 검증한다."""

    def __init__(self, server_url: str | None = None):
        self.server_url = server_url or ADMIN_SERVER_URL
        self._heartbeat_thread = None

    def activate(self, license_key: str) -> dict:
        """어드민 서버에 라이선스 키를 보내서 활성화한다."""
        try:
            resp = requests.post(
                f"{self.server_url}/license/activate",
                json={
                    "license_key": license_key,
                    "machine_id": self._get_machine_id(),
                },
                timeout=10,
            )
            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError):
                log.error(f"어드민 서버 응답이 JSON이 아닙니다 (status={resp.status_code}). URL: {self.server_url}")
                return {"ok": False, "error": f"어드민 서버 연결 실패. URL을 확인해주세요: {self.server_url}"}
            if resp.status_code == 200 and data.get("ok"):
                repo.save_license(
                    license_key=license_key,
                    company_name=data["company_name"],
                    expires_at=datetime.fromisoformat(data["expires_at"]),
                    plan=data.get("plan", "basic"),
                    max_crawl_accounts=data.get("max_crawl_accounts", 1),
                    max_dm_accounts=data.get("max_dm_accounts", 1),
                    max_daily_dm=data.get("max_daily_dm", 50),
                    max_hashtags=data.get("max_hashtags", 5),
                    can_schedule=data.get("can_schedule", False),
                    can_analyze=data.get("can_analyze", False),
                    can_export=data.get("can_export", False),
                )
                log.info(f"라이선스 활성화 완료: {data['company_name']} ({data.get('plan', 'basic')})")
                self.start_heartbeat()
                return {**data, "ok": True}
            else:
                return {"ok": False, "error": data.get("error", "라이선스 인증 실패")}
        except requests.ConnectionError:
            return self._check_local_cache(license_key)
        except Exception as e:
            log.error(f"라이선스 활성화 오류: {e}")
            return {"ok": False, "error": str(e)}

    def verify(self) -> dict:
        """저장된 라이선스가 유효한지 확인한다."""
        lic = repo.get_license()
        if not lic:
            return {"ok": False, "error": "라이선스가 등록되지 않았습니다."}

        # 만료일 확인
        if lic["expires_at"]:
            expires = datetime.fromisoformat(lic["expires_at"])
            if expires < datetime.utcnow():
                return {"ok": False, "error": "라이선스가 만료되었습니다.", "expired": True}

            days_left = (expires - datetime.utcnow()).days
            if days_left <= 30:
                log.warning(f"라이선스 만료 {days_left}일 전")

        # 온라인이면 서버에서 재검증 + 플랜 정보 동기화
        try:
            resp = requests.post(
                f"{self.server_url}/license/verify",
                json={
                    "license_key": lic["license_key"],
                    "machine_id": self._get_machine_id(),
                },
                timeout=5,
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except (json.JSONDecodeError, ValueError):
                    log.warning("어드민 서버 응답 파싱 실패 - 로컬 캐시로 진행")
                    return {"ok": True, **lic}
                if not data.get("ok"):
                    return {"ok": False, "error": data.get("error", "라이선스 검증 실패")}
                # 서버에서 받은 최신 플랜 정보로 로컬 업데이트
                repo.save_license(
                    license_key=lic["license_key"],
                    company_name=lic["company_name"],
                    expires_at=datetime.fromisoformat(lic["expires_at"]),
                    plan=data.get("plan", lic.get("plan", "basic")),
                    max_crawl_accounts=data.get("max_crawl_accounts", lic.get("max_crawl_accounts", 1)),
                    max_dm_accounts=data.get("max_dm_accounts", lic.get("max_dm_accounts", 1)),
                    max_daily_dm=data.get("max_daily_dm", lic.get("max_daily_dm", 50)),
                    max_hashtags=data.get("max_hashtags", lic.get("max_hashtags", 5)),
                    can_schedule=data.get("can_schedule", lic.get("can_schedule", False)),
                    can_analyze=data.get("can_analyze", lic.get("can_analyze", False)),
                    can_export=data.get("can_export", lic.get("can_export", False)),
                )
                # 최신 플랜으로 갱신된 데이터 반환
                lic = repo.get_license()
        except requests.ConnectionError:
            log.info("오프라인 상태 - 로컬 캐시로 라이선스 검증")

        return {"ok": True, **lic}

    def check_update(self) -> dict | None:
        """어드민 서버에서 최신 버전 확인. 업데이트 있으면 정보 반환."""
        try:
            resp = requests.get(
                f"{self.server_url}/version",
                params={"current": APP_VERSION},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("update_available"):
                    log.info(f"새 버전 {data['latest_version']} 사용 가능")
                    return data
        except Exception:
            pass
        return None

    def start_heartbeat(self):
        """백그라운드에서 하루 1회 하트비트 전송."""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        def _heartbeat_loop():
            while True:
                try:
                    lic = repo.get_license()
                    if not lic:
                        break
                    requests.post(
                        f"{self.server_url}/heartbeat",
                        json={
                            "license_key": lic["license_key"],
                            "machine_id": self._get_machine_id(),
                            "version": APP_VERSION,
                        },
                        timeout=10,
                    )
                    repo.update_heartbeat()
                    log.debug("하트비트 전송 완료")
                except Exception:
                    pass
                time.sleep(86400)  # 24시간

        self._heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _check_local_cache(self, license_key: str) -> dict:
        """오프라인 시 로컬 DB에 저장된 라이선스로 검증한다."""
        lic = repo.get_license()
        if lic and lic["license_key"] == license_key:
            if lic["expires_at"]:
                expires = datetime.fromisoformat(lic["expires_at"])
                if expires > datetime.utcnow():
                    return {"ok": True, **lic}
            return {"ok": False, "error": "라이선스가 만료되었습니다."}
        return {"ok": False, "error": "오프라인 상태에서 새 라이선스를 활성화할 수 없습니다."}

    @staticmethod
    def _get_machine_id() -> str:
        """하드웨어 기반 고유 ID를 생성한다."""
        import uuid
        mac = uuid.getnode()
        return hashlib.sha256(str(mac).encode()).hexdigest()[:32]


license_validator = LicenseValidator()
