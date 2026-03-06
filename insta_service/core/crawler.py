import re
import time
import random
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from insta_service.config import cfg
from insta_service.db import repository as repo
from insta_service.core.browser import detect_action_block
from insta_service.utils.logger import log

# 크롤링 설정
_c = cfg["crawling"]
_sel = cfg["selectors"]


class CrawlResult:
    def __init__(self):
        self.collected: list[str] = []
        self.errors: list[str] = []
        self.is_cancelled = False


class HashtagCrawler:
    def __init__(self, driver, account_id: int | None = None):
        self.driver = driver
        self.account_id = account_id
        self._cancel_requested = False
        self.blocked = False

    def cancel(self):
        self._cancel_requested = True

    def crawl(self, hashtag: str, target_count: int, job_id: int | None = None,
              on_progress=None) -> CrawlResult:
        """해시태그 페이지에서 유저네임을 수집한다."""
        result = CrawlResult()
        self._cancel_requested = False
        existing_users = repo.get_all_usernames()

        try:
            url = f"https://www.instagram.com/explore/tags/{hashtag}/"
            self.driver.get(url)
            time.sleep(random.uniform(_c["page_load_wait"], _c["page_load_wait"] + 2))

            if job_id:
                repo.update_crawl_job(job_id, status="running", started_at=datetime.utcnow())

            collected = set()
            visited_hrefs = set()
            scroll_try = 0

            while len(collected) < target_count and scroll_try < _c["max_scroll_attempts"]:
                if self._cancel_requested:
                    result.is_cancelled = True
                    break

                # 게시물 링크 수집
                posts = self.driver.find_elements(By.CSS_SELECTOR, _sel["post_link"])
                post_elems = []
                for post in posts:
                    href = post.get_attribute("href")
                    if href and "/p/" in href and href not in visited_hrefs:
                        post_elems.append((post, href))

                log.info(f"[{hashtag}] 게시물: {len(post_elems)}개 발견, 수집: {len(collected)}/{target_count}")

                # 게시물 하나씩 클릭하여 아이디 추출
                for post_elem, href in post_elems:
                    if len(collected) >= target_count or self._cancel_requested:
                        break
                    if href in visited_hrefs:
                        continue

                    username = self._extract_username_from_post(post_elem, href)
                    visited_hrefs.add(href)

                    if username and username not in existing_users and username not in collected:
                        is_new = repo.add_user(username, hashtag)
                        if is_new:
                            collected.add(username)
                            result.collected.append(username)
                            existing_users.add(username)
                            log.info(f"[{hashtag}] {len(collected)}/{target_count}: @{username}")

                            if job_id:
                                repo.update_crawl_job(job_id, collected_count=len(collected))
                            if on_progress:
                                try:
                                    on_progress(len(collected), target_count, username)
                                except Exception:
                                    pass

                # 차단 감지
                block_status = detect_action_block(self.driver)
                if block_status:
                    log.warning(f"[{hashtag}] 차단 감지: {block_status}")
                    self.blocked = True
                    result.errors.append(f"차단 감지: {block_status}")
                    if self.account_id:
                        repo.update_account_status(self.account_id, "limited")
                    break

                # 스크롤
                if len(collected) < target_count and not self._cancel_requested:
                    scroll_height = self.driver.execute_script("return document.body.scrollHeight")
                    scroll_to = int(scroll_height * random.uniform(0.7, 1.0))
                    self.driver.execute_script(f"window.scrollTo(0, {scroll_to});")
                    time.sleep(random.uniform(_c["scroll_min_delay"], _c["scroll_max_delay"]))
                    scroll_try += 1

            if len(collected) < target_count and not result.is_cancelled:
                log.warning(f"[{hashtag}] 목표({target_count}) 미달. 수집: {len(collected)}")

        except Exception as e:
            log.error(f"[{hashtag}] 크롤링 오류: {e}")
            result.errors.append(str(e))

        # 작업 상태 업데이트
        if job_id:
            final_status = "cancelled" if result.is_cancelled else (
                "completed" if not result.errors else "failed"
            )
            update_kwargs = {
                "status": final_status,
                "collected_count": len(result.collected),
                "completed_at": datetime.utcnow(),
            }
            if result.errors:
                update_kwargs["error_message"] = "; ".join(result.errors[:3])
            repo.update_crawl_job(job_id, **update_kwargs)

        log.info(f"[{hashtag}] 크롤링 완료. 수집: {len(result.collected)}명")
        return result

    def _extract_username_from_post(self, post_elem, href: str) -> str | None:
        """게시물을 클릭하고 작성자 아이디를 추출한다."""
        try:
            # 스크롤 & 클릭
            self.driver.execute_script(
                "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", post_elem
            )
            time.sleep(random.uniform(0.7, 1.5))
            ActionChains(self.driver).move_to_element(post_elem).pause(
                random.uniform(0.2, 0.6)
            ).click().perform()
            time.sleep(random.uniform(_c["min_delay"], _c["max_delay"]))

            # 아이디 추출 (폴백 체인)
            username = None
            for selector_key in ["username_primary", "username_fallback1", "username_fallback2"]:
                try:
                    selector = _sel[selector_key]
                    elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if selector_key == "username_fallback2":
                        href_val = elem.get_attribute("href")
                        m = re.search(r"instagram\.com/([^/]+)/?", href_val)
                        username = m.group(1) if m else href_val.strip("/").split("/")[-1]
                    else:
                        username = elem.text
                    if username:
                        break
                except Exception:
                    continue

            # 모달 닫기
            self._close_modal()
            return username

        except Exception as e:
            log.debug(f"게시물 처리 오류: {e}")
            self._close_modal()
            return None

    def _close_modal(self):
        """게시물 모달을 닫는다."""
        try:
            close_btn = self.driver.find_element(By.CSS_SELECTOR, _sel["close_button"])
            close_btn.click()
        except Exception:
            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
        time.sleep(random.uniform(0.5, 1.0))
