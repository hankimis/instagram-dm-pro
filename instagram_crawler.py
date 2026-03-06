import sys
import time
import re
import pandas as pd
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from bs4 import BeautifulSoup
import os  # os 모듈 추가
import undetected_chromedriver as uc  # 상단에 추가
from selenium.webdriver.common.action_chains import ActionChains
import random
import chromedriver_autoinstaller  # 추가
import shutil

class InstagramCrawler:
    def __init__(self, root):
        self.root = root
        self.root.title('Instagram Hashtag Crawler')
        self.root.geometry('600x500')
        
        # 데이터 초기화
        self.data = []
        self.existing_users = set()
        self.is_crawling = False  # 크롤링 상태 추적
        self.driver = None
        
        # GUI 위젯들을 먼저 생성
        self.create_widgets()
        
        # 기존 데이터 로드
        try:
            self.load_existing_data()
        except Exception as e:
            self.existing_users = set()
            self.log(f'초기 데이터 로드 실패: {str(e)}')
        
    def create_widgets(self):
        # 해시태그 입력 프레임
        hashtag_frame = ttk.Frame(self.root, padding="5")
        hashtag_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(hashtag_frame, text="해시태그:").pack(side=tk.LEFT)
        self.hashtag_input = ttk.Entry(hashtag_frame)
        self.hashtag_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))
        self.hashtag_input.insert(0, "python")
        
        # 수집할 아이디 수 입력
        ttk.Label(hashtag_frame, text="수집할 아이디 수:").pack(side=tk.LEFT, padx=(10, 0))
        self.target_user_count = ttk.Spinbox(hashtag_frame, from_=1, to=1000, width=7)
        self.target_user_count.set(10)
        self.target_user_count.pack(side=tk.LEFT, padx=(5, 5))
        
        # 버튼 프레임
        button_frame = ttk.Frame(self.root, padding="5")
        button_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # 크롬 실행 버튼
        self.chrome_btn = ttk.Button(button_frame, text="크롬 실행", command=self.start_chrome)
        self.chrome_btn.pack(side=tk.LEFT, padx=5)
        
        # 검색 버튼
        self.search_btn = ttk.Button(button_frame, text="크롤링 시작", command=self.start_crawling)
        self.search_btn.pack(side=tk.LEFT, padx=5)
        self.search_btn['state'] = 'disabled'  # 초기에는 비활성화
        
        # 취소 버튼
        self.cancel_btn = ttk.Button(button_frame, text="크롤링 취소", command=self.cancel_crawling)
        self.cancel_btn.pack(side=tk.LEFT, padx=5)
        self.cancel_btn['state'] = 'disabled'  # 초기에는 비활성화
        
        # 로그 프레임
        log_frame = ttk.LabelFrame(self.root, text="로그", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 진행 상황 표시
        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(fill=tk.X, padx=5, pady=5)
        
        # 상태 표시줄
        self.status_var = tk.StringVar()
        self.status_var.set('준비')
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=5, pady=2)

    def start_chrome(self):
        """크롬 브라우저 실행"""
        try:
            if self.driver is None:
                chromedriver_autoinstaller.install()  # 크롬드라이버 자동 설치
                options = uc.ChromeOptions()
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-gpu')
                options.add_argument('--disable-extensions')
                options.add_argument('--disable-popup-blocking')
                options.add_argument('--ignore-certificate-errors')
                options.add_argument('--no-first-run')
                options.add_argument('--no-service-autorun')
                options.add_argument('--password-store=basic')
                options.add_argument('--start-maximized')

                # macOS의 기본 Chrome 바이너리 경로 설정 (존재할 때만 사용)
                chrome_binary_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
                if os.path.exists(chrome_binary_path):
                    options.binary_location = chrome_binary_path
                
                # 설치된 Chrome 버전 자동 감지 (예: 137.0.XXXX.YYY)
                detected_version = None
                detected_major = None
                try:
                    detected_version = chromedriver_autoinstaller.get_chrome_version()
                    detected_major = int(detected_version.split('.')[0]) if detected_version else None
                except Exception:
                    detected_version = None
                    detected_major = None
                if detected_version:
                    self.log(f"감지된 Chrome 버전: {detected_version}")
                
                # 기존 크롬 프로필 삭제 후 새로 생성
                if os.path.exists('./chrome_profile'):
                    shutil.rmtree('./chrome_profile')
                os.makedirs('./chrome_profile', exist_ok=True)
                
                options.add_argument('--user-data-dir=./chrome_profile')
                # 감지된 주요 버전이 있으면 전달, 없으면 자동 매칭에 맡김
                chrome_kwargs = {
                    'options': options,
                    'headless': False,
                    'use_subprocess': True
                }
                if detected_major:
                    chrome_kwargs['version_main'] = detected_major
                self.driver = uc.Chrome(**chrome_kwargs)
                
                self.log("Chrome 브라우저가 실행되었습니다.")
                self.log("인스타그램에 로그인한 후 '크롤링 시작' 버튼을 클릭하세요.")
                self.search_btn['state'] = 'normal'  # 크롤링 시작 버튼 활성화
                self.chrome_btn['state'] = 'disabled'  # 크롬 실행 버튼 비활성화
            else:
                self.log("Chrome 브라우저가 이미 실행 중입니다.")
        except Exception as e:
            self.log(f"Chrome 실행 중 오류 발생: {str(e)}")
            messagebox.showerror("오류", "Chrome 브라우저 실행에 실패했습니다.")

    def cancel_crawling(self):
        """크롤링 취소"""
        if self.is_crawling:
            self.is_crawling = False
            self.log("크롤링이 취소되었습니다.")
            self.search_btn['state'] = 'normal'
            self.cancel_btn['state'] = 'disabled'
            self.progress['value'] = 0

    def start_crawling(self):
        """크롤링 시작"""
        if not self.driver:
            messagebox.showwarning('경고', '먼저 Chrome 브라우저를 실행해주세요.')
            return
            
        hashtag = self.hashtag_input.get().strip()
        if not hashtag:
            messagebox.showwarning('경고', '해시태그를 입력해주세요.')
            return
            
        try:
            target_user_count = int(self.target_user_count.get())
            if target_user_count < 1:
                messagebox.showwarning('경고', '수집할 아이디 수는 1 이상이어야 합니다.')
                return
        except ValueError:
            messagebox.showwarning('경고', '올바른 수집할 아이디 수를 입력해주세요.')
            return
            
        # 로그인 상태 확인
        try:
            self.driver.get('https://www.instagram.com')
            time.sleep(2)
            if 'login' in self.driver.current_url:
                messagebox.showwarning('경고', '인스타그램에 로그인해주세요.')
                return
        except Exception as e:
            self.log(f"로그인 상태 확인 중 오류: {str(e)}")
            return
            
        self.is_crawling = True
        self.search_btn['state'] = 'disabled'
        self.cancel_btn['state'] = 'normal'
        self.progress['value'] = 0
        
        try:
            self.crawl_hashtag(hashtag)
        except Exception as e:
            self.log(f"크롤링 중 오류 발생: {str(e)}")
        finally:
            self.is_crawling = False
            self.search_btn['state'] = 'normal'
            self.cancel_btn['state'] = 'disabled'
            self.save_to_excel()

    def crawl_hashtag(self, hashtag):
        try:
            url = f'https://www.instagram.com/explore/tags/{hashtag}/'
            self.driver.get(url)
            time.sleep(random.uniform(3.5, 5.5))
            target_user_count = int(self.target_user_count.get())
            collected_usernames = set()
            post_elems = []  # (element, href) 쌍 저장
            visited_hrefs = set()
            scroll_try = 0
            max_scroll = 50  # 무한스크롤 방지
            while len(collected_usernames) < target_user_count and scroll_try < max_scroll:
                # 썸네일(게시물) element 모두 수집
                posts = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/p/"]')
                for post in posts:
                    href = post.get_attribute('href')
                    if href and '/p/' in href and href not in visited_hrefs:
                        post_elems.append((post, href))
                self.log(f"현재까지 발견된 게시물: {len(post_elems)}개, 수집된 아이디: {len(collected_usernames)}개")
                # 게시물 하나씩 클릭해서 아이디 추출
                for idx, (post_elem, href) in enumerate(post_elems):
                    if len(collected_usernames) >= target_user_count:
                        break
                    if not self.is_crawling:
                        return
                    if href in visited_hrefs:
                        continue
                    try:
                        # 썸네일이 화면에 보이도록 자연스럽게 스크롤
                        self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", post_elem)
                        time.sleep(random.uniform(0.7, 1.5))
                        # 마우스 이동 후 클릭
                        ActionChains(self.driver).move_to_element(post_elem).pause(random.uniform(0.2, 0.6)).click().perform()
                        time.sleep(random.uniform(1.2, 2.2))
                        visited_hrefs.add(href)
                        # 아이디 추출: 게시물 상단의 작성자 아이디만 추출 (header 내 a._acan)
                        username = None
                        try:
                            user_elem = self.driver.find_element(By.CSS_SELECTOR, 'a._acan._acao._acat._acaw._aj1-._ap30._a6hd')
                            username = user_elem.text
                        except Exception:
                            try:
                                # 대체 선택자로 시도
                                user_elem = self.driver.find_element(By.CSS_SELECTOR, 'a[role="link"][tabindex="0"]._acan')
                                username = user_elem.text
                            except Exception:
                                try:
                                    # href 속성으로 시도
                                    user_elem = self.driver.find_element(By.CSS_SELECTOR, 'article header a[href^="/"][role="link"]')
                                    href = user_elem.get_attribute('href')
                                    import re
                                    m = re.search(r'instagram.com/([^/]+)/?', href)
                                    if m:
                                        username = m.group(1)
                                    else:
                                        username = href.strip('/').split('/')[-1]
                                except Exception:
                                    username = None
                        if username and username not in self.existing_users and username not in collected_usernames:
                            self.data.append({
                                'username': username,
                                'hashtag': hashtag,
                                'crawled_date': datetime.now().strftime('%Y-%m-%d')
                            })
                            self.existing_users.add(username)
                            collected_usernames.add(username)
                            self.log(f"{len(collected_usernames)}/{target_user_count}: {username}")
                        self.progress['value'] = (len(collected_usernames)) * (100/target_user_count)
                        self.root.update()
                        # 게시물 닫기 (ESC 또는 close 버튼)
                        try:
                            close_btn = self.driver.find_element(By.CSS_SELECTOR, 'svg[aria-label="닫기"]')
                            close_btn.click()
                        except Exception:
                            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                        time.sleep(random.uniform(0.8, 1.5))
                    except Exception as e:
                        self.log(f"{idx+1}번째 게시물 처리 오류: {e}")
                # 부족하면 스크롤 추가
                if len(collected_usernames) < target_user_count:
                    scroll_height = self.driver.execute_script('return document.body.scrollHeight')
                    scroll_to = int(scroll_height * random.uniform(0.7, 1.0))
                    self.driver.execute_script(f'window.scrollTo(0, {scroll_to});')
                    time.sleep(random.uniform(1.2, 2.2))
                    scroll_try += 1
            if len(collected_usernames) < target_user_count:
                self.log(f"수집 목표({target_user_count})에 도달하지 못했습니다. 최종 수집: {len(collected_usernames)}개")
        except Exception as e:
            self.log(f'해시태그 크롤링 중 오류: {str(e)}')

    def save_to_excel(self):
        try:
            if self.data:
                df_new = pd.DataFrame(self.data)
                
                try:
                    if os.path.exists('instagram_users.xlsx'):
                        df_existing = pd.read_excel('instagram_users.xlsx')
                        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                    else:
                        df_combined = df_new
                        
                    df_combined.to_excel('instagram_users.xlsx', index=False)
                    self.log(f'데이터 저장 완료: {len(self.data)}명의 새로운 사용자')
                    self.data = []
                except Exception as e:
                    self.log(f'데이터 저장 중 오류: {str(e)}')
            else:
                self.log('저장할 새로운 데이터가 없습니다.')
                
        except Exception as e:
            self.log(f'데이터 저장 중 오류: {str(e)}')
            
    def get_all_posts(self):
        """이 메서드는 더 이상 사용하지 않음"""
        pass

    def load_existing_data(self):
        try:
            # 파일이 없으면 빈 DataFrame 생성
            if not os.path.exists('instagram_users.xlsx'):
                self.log('새로운 데이터 파일을 생성합니다.')
                return
                
            df = pd.read_excel('instagram_users.xlsx')
            self.existing_users = set(df['username'].tolist())
            self.log('기존 데이터 로드 완료: {}명의 사용자'.format(len(self.existing_users)))
        except Exception as e:
            self.log(f'데이터 로드 중 오류 발생: {str(e)}')
            self.existing_users = set()
            
    def log(self, message):
        current_time = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f'[{current_time}] {message}\n')
        self.log_text.see(tk.END)
        self.root.update()
        
    def on_closing(self):
        """프로그램 종료 시 처리"""
        if self.is_crawling:
            if not messagebox.askokcancel("종료", "크롤링이 진행 중입니다. 정말 종료하시겠습니까?"):
                return
        if self.driver:
            # 드라이버는 종료하지 않고 유지
            pass
        self.root.destroy()

if __name__ == '__main__':
    root = tk.Tk()
    app = InstagramCrawler(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop() 