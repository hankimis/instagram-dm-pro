import os
import re
import string
import time
import random
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from insta_service.config import cfg, DM_IMAGES_DIR
from insta_service.db import repository as repo
from insta_service.core.browser import detect_action_block
from insta_service.utils.logger import log

_dm_cfg = cfg["dm"]

# 한글 자모 (오타용)
_NEARBY_KEYS = {
    'ㅂ': 'ㅈㅁ', 'ㅈ': 'ㅂㄷ', 'ㄷ': 'ㅈㄱ', 'ㄱ': 'ㄷㅅ', 'ㅅ': 'ㄱㅛ',
    'ㅛ': 'ㅅㅕ', 'ㅕ': 'ㅛㅑ', 'ㅑ': 'ㅕㅐ', 'ㅐ': 'ㅑㅔ', 'ㅔ': 'ㅐ',
    'ㅁ': 'ㅂㄴ', 'ㄴ': 'ㅁㅇ', 'ㅇ': 'ㄴㄹ', 'ㄹ': 'ㅇㅎ', 'ㅎ': 'ㄹㅗ',
    'ㅗ': 'ㅎㅓ', 'ㅓ': 'ㅗㅏ', 'ㅏ': 'ㅓㅣ', 'ㅣ': 'ㅏ',
    'ㅋ': 'ㅌㅊ', 'ㅌ': 'ㅋㅍ', 'ㅊ': 'ㅋㅠ', 'ㅍ': 'ㅌㅜ',
    'ㅠ': 'ㅊㅜ', 'ㅜ': 'ㅠㅡ', 'ㅡ': 'ㅜ',
    'a': 'sq', 'b': 'vn', 'c': 'xv', 'd': 'sf', 'e': 'wr', 'f': 'dg',
    'g': 'fh', 'h': 'gj', 'i': 'uo', 'j': 'hk', 'k': 'jl', 'l': 'k',
    'm': 'n', 'n': 'bm', 'o': 'ip', 'p': 'o', 'q': 'wa', 'r': 'et',
    's': 'ad', 't': 'ry', 'u': 'yi', 'v': 'cb', 'w': 'qe', 'x': 'zc',
    'y': 'tu', 'z': 'x',
}


class DmSender:
    def __init__(self, driver, sender_account_id: int):
        self.driver = driver
        self.sender_account_id = sender_account_id
        self._cancel_requested = False
        self.blocked = False

    def cancel(self):
        self._cancel_requested = True

    def _type_with_typos(self, element, text: str):
        """
        사람처럼 오타를 내고 백스페이스로 수정하면서 타이핑한다.
        약 8~15% 확률로 오타 발생 → 잠깐 멈춤 → 백스페이스 → 올바른 글자 입력.
        """
        typo_rate = random.uniform(0.08, 0.15)
        i = 0
        while i < len(text):
            char = text[i]
            # 오타 발생 (공백, 줄바꿈, 특수문자는 제외)
            if random.random() < typo_rate and char.strip() and char not in '.,!?~@#{}':
                # 인접 키 또는 랜덤 문자로 오타
                nearby = _NEARBY_KEYS.get(char.lower(), '')
                if nearby:
                    typo_char = random.choice(nearby)
                else:
                    typo_char = random.choice(string.ascii_lowercase)

                # 오타 입력
                element.send_keys(typo_char)
                time.sleep(random.uniform(0.05, 0.15))

                # 1~3글자 더 치고 나서 알아채는 경우 (30%)
                extra_typed = 0
                if random.random() < 0.3 and i + 1 < len(text):
                    extra = random.randint(1, min(2, len(text) - i - 1))
                    for j in range(extra):
                        element.send_keys(text[i + 1 + j])
                        time.sleep(random.uniform(0.03, 0.08))
                        extra_typed += 1

                # 잠깐 멈춤 (오타 인지)
                time.sleep(random.uniform(0.3, 0.8))

                # 백스페이스로 오타 + 추가 글자 삭제
                for _ in range(1 + extra_typed):
                    element.send_keys(Keys.BACKSPACE)
                    time.sleep(random.uniform(0.03, 0.08))

                time.sleep(random.uniform(0.1, 0.3))

                # 올바른 글자 + 추가 글자 다시 입력
                element.send_keys(char)
                time.sleep(random.uniform(0.04, 0.1))
                for j in range(extra_typed):
                    element.send_keys(text[i + 1 + j])
                    time.sleep(random.uniform(0.04, 0.1))
                i += 1 + extra_typed
            else:
                element.send_keys(char)
                # 타이핑 속도 변동 (가끔 멈칫)
                if random.random() < 0.05:
                    time.sleep(random.uniform(0.3, 1.0))
                else:
                    time.sleep(random.uniform(0.03, 0.1))
                i += 1

    def _browse_reels(self, duration: float = None):
        """
        릴스 페이지에서 랜덤 시간 동안 스크롤하며 시간을 보낸다.
        봇 탐지 우회용 — 실제 사용자처럼 릴스를 보는 행동 시뮬레이션.
        """
        if duration is None:
            duration = random.uniform(
                _dm_cfg.get("reels_min_time", 15),
                _dm_cfg.get("reels_max_time", 40),
            )
        try:
            self.driver.get("https://www.instagram.com/reels/")
            time.sleep(random.uniform(3, 5))

            start = time.time()
            while time.time() - start < duration:
                if self._cancel_requested:
                    break
                # 릴스 하나 보기 (3~8초)
                watch_time = random.uniform(3, 8)
                time.sleep(watch_time)

                # 다음 릴스로 스크롤 (아래 화살표 또는 스크롤)
                ActionChains(self.driver).send_keys(Keys.ARROW_DOWN).perform()
                time.sleep(random.uniform(0.5, 1.5))

            log.info(f"릴스 브라우징 완료 ({duration:.0f}초)")
        except Exception as e:
            log.debug(f"릴스 브라우징 중 오류 (무시): {e}")

    def _extract_display_name(self, username: str) -> str | None:
        """현재 프로필 페이지에서 display name을 추출한다 (og:title 또는 title 태그)."""
        try:
            og_title = self.driver.find_element(By.CSS_SELECTOR, 'meta[property="og:title"]')
            content = og_title.get_attribute("content") or ""
            m = re.match(r"^(.+?)\s*\(@", content)
            if m:
                return m.group(1).strip()
        except Exception:
            pass
        try:
            title = self.driver.title or ""
            m = re.match(r"^(.+?)\s*\(@", title)
            if m:
                return m.group(1).strip()
        except Exception:
            pass
        return None

    def send_dm(self, username: str, message: str, user_id: int,
                template_id: int | None = None,
                image_path: str | None = None) -> bool:
        """
        유저 프로필 → '메시지 보내기' 클릭 → 채팅창에서 메시지 발송.
        /direct/new/ 방식보다 자연스럽고 차단 확률이 낮다.
        """
        try:
            # ── Step 1: 유저 프로필 페이지로 이동 ──
            self.driver.get(f"https://www.instagram.com/{username}/")
            time.sleep(random.uniform(3, 5))

            # 차단/challenge 확인
            block = detect_action_block(self.driver)
            if block:
                log.warning(f"프로필 접근 차단: {block} (@{username}, URL: {self.driver.current_url})")
                self.blocked = True
                self._block_reason = block
                repo.add_dm_history(user_id, self.sender_account_id, message,
                                    template_id, status="failed")
                return False

            # 페이지 존재 확인
            page_source = self.driver.page_source
            if "페이지를 사용할 수 없습니다" in page_source or "this page isn't available" in page_source.lower():
                log.warning(f"DM 발송 실패: @{username} 존재하지 않는 계정")
                repo.add_dm_history(user_id, self.sender_account_id, message,
                                    template_id, status="failed")
                return False

            # 프로필 페이지에서 display name 실시간 추출 → {name} 치환
            display_name = self._extract_display_name(username)
            if display_name:
                message = message.replace("{name}", display_name)
            else:
                # 폴백: {name}을 username으로 치환
                message = message.replace("{name}", username)

            # ── Step 2: "메시지 보내기" 버튼 클릭 ──
            msg_btn = None
            # 버튼 텍스트로 찾기 (한국어/영어)
            buttons = self.driver.find_elements(By.CSS_SELECTOR, 'button, div[role="button"]')
            for btn in buttons:
                text = btn.text.strip()
                if text in ("메시지 보내기", "Message", "메시지"):
                    msg_btn = btn
                    break

            if not msg_btn:
                log.warning(f"DM 발송 실패: @{username} '메시지 보내기' 버튼 없음 (비공개 계정이거나 차단됨)")
                repo.add_dm_history(user_id, self.sender_account_id, message,
                                    template_id, status="failed")
                return False

            msg_btn.click()

            # ── Step 3: 채팅창이 열릴 때까지 대기 ──
            msg_input = None
            for attempt in range(10):
                time.sleep(1)
                # 메시지 입력창 탐색 (여러 셀렉터)
                for sel in ['div[role="textbox"][contenteditable="true"]',
                            'textarea[placeholder*="메시지"]',
                            'textarea[placeholder*="Message"]',
                            'textarea[placeholder]',
                            'p[data-lexical-text]']:
                    try:
                        msg_input = self.driver.find_element(By.CSS_SELECTOR, sel)
                        break
                    except Exception:
                        continue
                if msg_input:
                    break

            if not msg_input:
                log.warning(f"DM 발송 실패: @{username} 채팅창이 열리지 않음 (URL: {self.driver.current_url})")
                repo.add_dm_history(user_id, self.sender_account_id, message,
                                    template_id, status="failed")
                return False

            # ── Step 4: 이미지 먼저 발송 (선택) ──
            if image_path:
                self._attach_image_in_chat(image_path)

            # ── Step 5: 메시지 입력 (오타 시뮬레이션 포함) ──
            msg_input.click()
            time.sleep(0.5)

            self._type_with_typos(msg_input, message)

            time.sleep(random.uniform(0.5, 1.5))
            msg_input.send_keys(Keys.RETURN)
            time.sleep(random.uniform(1, 2))

            repo.add_dm_history(user_id, self.sender_account_id, message,
                                template_id, status="sent")
            log.info(f"DM 발송 완료: @{username}" + (" (이미지 포함)" if image_path else ""))
            return True

        except Exception as e:
            log.error(f"DM 발송 오류 (@{username}): {e}")
            repo.add_dm_history(user_id, self.sender_account_id, message,
                                template_id, status="failed")
            return False

    def _attach_image_in_chat(self, image_path: str):
        """
        DM 채팅창에서 이미지를 클립보드 붙여넣기(Ctrl+V)로 발송한다.
        input[type=file]을 직접 사용하면 포스트 업로드 input이 잡히는 문제를 회피.

        흐름: 이미지를 클립보드에 복사 → 채팅 입력창에 Ctrl+V → 전송
        """
        abs_path = image_path
        if not os.path.isabs(image_path):
            abs_path = str(DM_IMAGES_DIR / image_path)
        if not os.path.exists(abs_path):
            log.warning(f"이미지 파일 없음: {abs_path}")
            return
        try:
            import subprocess
            import platform

            # ── Step 1: 이미지를 시스템 클립보드에 복사 ──
            if platform.system() == "Darwin":
                # macOS: osascript로 클립보드에 이미지 복사
                subprocess.run([
                    "osascript", "-e",
                    f'set the clipboard to (read (POSIX file "{abs_path}") as «class PNGf»)'
                ], timeout=10, check=False)
            else:
                # Linux: xclip 사용
                subprocess.run(
                    ["xclip", "-selection", "clipboard", "-t", "image/png", "-i", abs_path],
                    timeout=10, check=False
                )

            time.sleep(0.5)

            # ── Step 2: 채팅 입력창에 Ctrl+V로 붙여넣기 ──
            # 채팅 입력창 찾기
            msg_area = None
            for sel in ['div[role="textbox"][contenteditable="true"]',
                        'textarea[placeholder]', 'textarea']:
                try:
                    msg_area = self.driver.find_element(By.CSS_SELECTOR, sel)
                    break
                except Exception:
                    continue

            if not msg_area:
                log.warning("이미지 붙여넣기 실패: 채팅 입력창을 찾을 수 없음")
                return

            msg_area.click()
            time.sleep(0.5)

            # Ctrl+V (macOS: Command+V)
            if platform.system() == "Darwin":
                ActionChains(self.driver).key_down(Keys.COMMAND).send_keys('v').key_up(Keys.COMMAND).perform()
            else:
                ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()

            time.sleep(random.uniform(3, 5))

            # URL 확인 — /create/로 이동했으면 실패
            if "/create/" in self.driver.current_url:
                log.warning("포스트 업로드 페이지로 이동됨 — 이미지 첨부 취소")
                self.driver.back()
                time.sleep(2)
                return

            # ── Step 3: 전송 (엔터 키) ──
            ActionChains(self.driver).send_keys(Keys.RETURN).perform()
            time.sleep(random.uniform(2, 3))
            log.info(f"이미지 발송 완료 (붙여넣기): {os.path.basename(abs_path)}")

        except Exception as e:
            log.warning(f"이미지 첨부 실패: {e}")
            if "/create/" in self.driver.current_url:
                self.driver.back()
                time.sleep(2)

    def send_batch(self, targets: list[dict],
                   message_template: str | None = None,
                   template_id: int | None = None, on_progress=None,
                   image_path: str | None = None,
                   templates: list[dict] | None = None) -> dict:
        """
        대상 유저들에게 일괄 DM 발송.
        targets: [{"user_id": int, "username": str}, ...]
        templates: [{"id", "name", "message_body", "image_path"}, ...] — 여러 개면 랜덤 선택
        message_template / template_id / image_path: 단일 템플릿 (하위 호환)
        """
        # 단일 템플릿 → templates 리스트로 통합
        if templates is None and message_template:
            templates = [{"id": template_id, "message_body": message_template,
                          "image_path": image_path}]
        if not templates:
            return {"sent": 0, "failed": 0, "cancelled": False}

        if len(templates) > 1:
            log.info(f"랜덤 템플릿 모드: {len(templates)}개 템플릿 사용")
        sent = 0
        failed = 0
        hourly_count = 0
        hour_start = time.time()

        # 일일 한도 확인
        daily_limit = _dm_cfg.get("daily_limit_per_account", 80)
        today_sent = repo.get_dm_count_today(self.sender_account_id)
        remaining_daily = max(0, daily_limit - today_sent)
        if remaining_daily <= 0:
            log.warning(f"일일 DM 한도 초과 (오늘 {today_sent}건 발송, 한도 {daily_limit}건)")
            return {"sent": 0, "failed": 0, "cancelled": False, "daily_limit_reached": True}

        # 발송 전 challenge/block 사전 확인
        self.driver.get("https://www.instagram.com/")
        time.sleep(random.uniform(2, 4))
        pre_block = detect_action_block(self.driver)
        if pre_block:
            log.warning(f"DM 발송 사전 차단 감지: {pre_block} (URL: {self.driver.current_url})")
            self.blocked = True
            self._block_reason = pre_block
            return {"sent": 0, "failed": 0, "cancelled": False, "blocked": True,
                    "block_reason": pre_block}

        for i, target in enumerate(targets):
            if self._cancel_requested:
                break

            # 일일 한도 체크 (발송할 때마다)
            if sent >= remaining_daily:
                log.warning(f"일일 DM 한도 도달 ({daily_limit}건). 발송 중단.")
                break

            # 시간당 발송 한도 체크
            elapsed = time.time() - hour_start
            if elapsed >= 3600:
                hourly_count = 0
                hour_start = time.time()

            if hourly_count >= _dm_cfg["hourly_limit"]:
                wait_time = 3600 - elapsed
                log.info(f"시간당 한도 도달. {wait_time:.0f}초 대기...")
                time.sleep(wait_time)
                hourly_count = 0
                hour_start = time.time()

            # 템플릿 랜덤 선택
            tpl = random.choice(templates)
            message = tpl["message_body"].replace("{username}", target["username"])
            # {name}은 send_dm에서 프로필 페이지 접근 후 실시간 치환

            success = self.send_dm(
                target["username"], message, target["user_id"], tpl.get("id"),
                image_path=tpl.get("image_path"),
            )

            if success:
                sent += 1
                hourly_count += 1
            else:
                failed += 1

            if on_progress:
                try:
                    on_progress(sent, failed, len(targets), target["username"], success)
                except Exception:
                    pass

            # 차단 감지
            block_status = detect_action_block(self.driver)
            if block_status:
                log.warning(f"DM 발송 차단 감지: {block_status}")
                self.blocked = True
                self._block_reason = block_status
                repo.update_account_status(self.sender_account_id, "limited")
                break

            # 발송 간 릴스 보기 (봇 탐지 우회)
            reels_chance = _dm_cfg.get("reels_chance", 60) / 100.0
            if random.random() < reels_chance:
                reels_time = random.uniform(
                    _dm_cfg["min_delay"], _dm_cfg["max_delay"]
                )
                log.info(f"릴스 브라우징 시작 ({reels_time:.0f}초)...")
                self._browse_reels(duration=reels_time)
            else:
                time.sleep(random.uniform(_dm_cfg["min_delay"], _dm_cfg["max_delay"]))

        return {"sent": sent, "failed": failed, "cancelled": self._cancel_requested,
                "blocked": self.blocked,
                "block_reason": getattr(self, "_block_reason", None)}
