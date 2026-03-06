import re
import time
import random
from datetime import datetime

from selenium.webdriver.common.by import By

from insta_service.config import cfg
from insta_service.db.models import SessionLocal, User, UserProfile
from insta_service.utils.logger import log

_c = cfg["crawling"]


class UserAnalyzer:
    def __init__(self, driver):
        self.driver = driver
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def analyze_user(self, username: str) -> dict | None:
        """단일 유저의 프로필 정보를 수집한다."""
        try:
            self.driver.get(f"https://www.instagram.com/{username}/")
            time.sleep(random.uniform(_c["min_delay"], _c["max_delay"]))

            data = {}

            # 메타 태그에서 기본 정보 추출
            try:
                meta = self.driver.find_element(By.CSS_SELECTOR, 'meta[property="og:description"]')
                content = meta.get_attribute("content") or ""
                # 영어 라벨 기반 파싱: "1,234 Followers, 567 Following, 89 Posts"
                nums = re.findall(r"([\d,\.]+[KMkm]?)\s+(Followers|Following|Posts)", content, re.IGNORECASE)
                if nums:
                    for val, label in nums:
                        num = self._parse_count(val)
                        if "follower" in label.lower():
                            data["followers_count"] = num
                        elif "following" in label.lower():
                            data["following_count"] = num
                        elif "post" in label.lower():
                            data["posts_count"] = num
                else:
                    # 위치 기반 폴백: 로케일 무관하게 숫자만 추출 (순서: followers, following, posts)
                    all_nums = re.findall(r"([\d,\.]+[KMkm]?)", content)
                    if len(all_nums) >= 3:
                        data["followers_count"] = self._parse_count(all_nums[0])
                        data["following_count"] = self._parse_count(all_nums[1])
                        data["posts_count"] = self._parse_count(all_nums[2])
                    elif len(all_nums) == 2:
                        data["followers_count"] = self._parse_count(all_nums[0])
                        data["following_count"] = self._parse_count(all_nums[1])
            except Exception:
                pass

            # 이름 (display name) 추출
            try:
                # 방법 1: og:title 메타 태그 — "Display Name (@username) · Instagram"
                og_title = self.driver.find_element(By.CSS_SELECTOR, 'meta[property="og:title"]')
                title_content = og_title.get_attribute("content") or ""
                # "Name (@user)" 형태에서 이름 추출
                name_match = re.match(r"^(.+?)\s*\(@", title_content)
                if name_match:
                    data["display_name"] = name_match.group(1).strip()
                else:
                    # 방법 2: <title> 태그 — "Display Name (@username) · Instagram photos and videos"
                    title_text = self.driver.title or ""
                    name_match2 = re.match(r"^(.+?)\s*\(@", title_text)
                    if name_match2:
                        data["display_name"] = name_match2.group(1).strip()
            except Exception:
                pass

            # 방법 3: 프로필 헤더의 span에서 추출 (폴백)
            if not data.get("display_name"):
                try:
                    header = self.driver.find_element(By.CSS_SELECTOR, 'header section span')
                    name_text = header.text.strip()
                    if name_text and name_text != username:
                        data["display_name"] = name_text
                except Exception:
                    pass

            # 바이오
            try:
                bio_elem = self.driver.find_element(By.CSS_SELECTOR, 'div.-vDIg span, section > div > span')
                data["bio"] = bio_elem.text
            except Exception:
                data["bio"] = ""

            # 비공개 계정 확인
            try:
                page_source = self.driver.page_source
                data["is_private"] = "이 계정은 비공개" in page_source or "This account is private" in page_source
            except Exception:
                data["is_private"] = False

            data["is_verified"] = False
            try:
                self.driver.find_element(By.CSS_SELECTOR, 'span[title="인증됨"], svg[aria-label="인증됨"]')
                data["is_verified"] = True
            except Exception:
                pass

            return data

        except Exception as e:
            log.error(f"유저 분석 오류 (@{username}): {e}")
            return None

    def analyze_batch(self, usernames: list[str]) -> dict:
        """여러 유저를 일괄 분석한다."""
        success = 0
        failed = 0

        for username in usernames:
            if self._cancel_requested:
                break

            data = self.analyze_user(username)
            if data:
                self._save_profile(username, data)
                success += 1
                log.info(f"분석 완료: @{username} (팔로워: {data.get('followers_count', '?')})")
            else:
                failed += 1

            time.sleep(random.uniform(_c["min_delay"], _c["max_delay"]))

        return {"success": success, "failed": failed}

    def _save_profile(self, username: str, data: dict):
        session = SessionLocal()
        try:
            user = session.query(User).filter_by(username=username).first()
            if not user:
                return

            profile = session.query(UserProfile).filter_by(user_id=user.id).first()
            if profile:
                for k, v in data.items():
                    setattr(profile, k, v)
                profile.analyzed_at = datetime.utcnow()
            else:
                profile = UserProfile(user_id=user.id, **data)
                session.add(profile)

            user.is_analyzed = True
            session.commit()
        except Exception as e:
            session.rollback()
            log.error(f"프로필 저장 오류 (@{username}): {e}")
        finally:
            session.close()

    @staticmethod
    def _parse_count(val: str) -> int:
        """'1,234' 또는 '12.5K' 같은 문자열을 정수로 변환한다."""
        val = val.replace(",", "").strip()
        multiplier = 1
        if val.lower().endswith("k"):
            multiplier = 1000
            val = val[:-1]
        elif val.lower().endswith("m"):
            multiplier = 1_000_000
            val = val[:-1]
        try:
            return int(float(val) * multiplier)
        except ValueError:
            return 0
