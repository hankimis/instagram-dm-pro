import json
import os
import tempfile
import zipfile
from pathlib import Path

from insta_service.config import BASE_DIR, DATA_DIR
from insta_service.db import repository as repo
from insta_service.utils.logger import log

PROXIES_FILE = BASE_DIR / "proxies.txt"


def load_proxies_from_file():
    """proxies.txt를 파싱하여 DB에 저장한다. ip:port:user:pass 형식."""
    if not PROXIES_FILE.exists():
        log.warning("proxies.txt 파일이 없습니다.")
        return

    count = 0
    for line in PROXIES_FILE.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(":")
        if len(parts) < 2:
            continue
        ip = parts[0]
        port = int(parts[1])
        username = parts[2] if len(parts) > 2 else None
        password = parts[3] if len(parts) > 3 else None
        repo.upsert_proxy(ip, port, username, password)
        count += 1

    log.info(f"proxies.txt에서 {count}개 프록시 로드 완료")


class ProxyManager:
    def __init__(self):
        self._index = 0

    def get_all(self) -> list[dict]:
        return repo.get_all_proxies()

    def get_next(self) -> dict | None:
        """라운드로빈으로 다음 프록시를 반환한다."""
        proxies = self.get_all()
        if not proxies:
            return None
        proxy = proxies[self._index % len(proxies)]
        self._index += 1
        return proxy

    def get_by_id(self, proxy_id: int) -> dict | None:
        proxies = self.get_all()
        for p in proxies:
            if p["id"] == proxy_id:
                return p
        return None

    @staticmethod
    def format_for_chrome(proxy: dict) -> str:
        """Chrome --proxy-server 인수용 문자열 반환."""
        return f"{proxy['ip']}:{proxy['port']}"

    @staticmethod
    def format_auth(proxy: dict) -> tuple[str, str] | None:
        """프록시 인증 정보를 (user, pass) 튜플로 반환."""
        if proxy.get("username") and proxy.get("password"):
            return (proxy["username"], proxy["password"])
        return None

    @staticmethod
    def create_proxy_auth_extension(proxy: dict) -> str | None:
        """프록시 인증이 필요한 경우 Chrome extension (.zip)을 생성하여 경로 반환."""
        username = proxy.get("username")
        password = proxy.get("password")
        if not username or not password:
            return None

        host = proxy["ip"]
        port = proxy["port"]

        manifest = json.dumps({
            "version": "1.0.0",
            "manifest_version": 2,
            "name": "Proxy Auth",
            "permissions": ["proxy", "tabs", "unlimitedStorage", "storage",
                            "<all_urls>", "webRequest", "webRequestBlocking"],
            "background": {"scripts": ["background.js"]},
            "minimum_chrome_version": "22.0.0"
        })

        background_js = """
var config = {
    mode: "fixed_servers",
    rules: {
        singleProxy: { scheme: "http", host: "%s", port: parseInt(%s) },
        bypassList: ["localhost"]
    }
};
chrome.proxy.settings.set({value: config, scope: "regular"}, function(){});
function callbackFn(details) {
    return { authCredentials: { username: "%s", password: "%s" } };
}
chrome.webRequest.onAuthRequired.addListener(
    callbackFn, {urls: ["<all_urls>"]}, ['blocking']
);
""" % (host, port, username, password)

        ext_dir = DATA_DIR / "proxy_extensions"
        ext_dir.mkdir(exist_ok=True)
        ext_path = ext_dir / f"proxy_auth_{host}_{port}.zip"

        with zipfile.ZipFile(str(ext_path), "w") as zf:
            zf.writestr("manifest.json", manifest)
            zf.writestr("background.js", background_js)

        log.info(f"프록시 인증 extension 생성: {ext_path}")
        return str(ext_path)


proxy_manager = ProxyManager()
