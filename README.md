# Instagram Hashtag Crawler

인스타그램 해시태그 검색을 통해 사용자 아이디를 수집하는 GUI 프로그램입니다.

## 기능
- GUI 인터페이스를 통한 해시태그 검색
- 인스타그램 로그인 기능
- 해시태그 검색 결과에서 사용자 아이디 추출
- 엑셀 파일로 데이터 저장 (중복 제거)
- 진행 상황 실시간 표시

## 설치 방법
1. 필요한 패키지 설치:
```bash
pip install -r requirements.txt
```

## 사용 방법
1. 프로그램 실행:
```bash
python instagram_crawler.py
```

2. GUI에서 인스타그램 아이디와 비밀번호 입력
3. 검색하고 싶은 해시태그 입력 (예: python)
4. '검색' 버튼 클릭
5. 크롤링이 완료되면 'instagram_users.xlsx' 파일에 결과가 저장됩니다.

## 주의사항
- 인스타그램의 이용약관을 준수하여 사용해주세요.
- 과도한 크롤링은 계정 제한의 원인이 될 수 있습니다.
- 수집된 데이터는 개인 용도로만 사용해주세요. 

python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install undetected-chromedriver
python instagram_crawler.py