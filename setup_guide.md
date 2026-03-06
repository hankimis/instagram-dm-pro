# Instagram Service - 설치 및 실행 가이드

## 사전 준비 (한 번만)

1. **Python 설치**
   - https://www.python.org/downloads/ 에서 다운로드
   - Windows: 설치 시 **"Add Python to PATH"** 반드시 체크!
   - macOS: 다운받은 .pkg 파일 더블클릭하여 설치

2. **Google Chrome** 설치 (이미 있으면 생략)

## 프로그램 실행

### macOS
`Instagram서비스_실행.command` 파일을 더블클릭

### Windows
`Instagram서비스_실행.bat` 파일을 더블클릭

### 터미널에서 직접 실행
```
python3 start.py
```

최초 실행 시 자동으로:
- 가상환경 생성 (venv_service/)
- 필요한 패키지 설치 (1~2분)

이후 실행부터는 바로 시작됩니다.
브라우저에서 `http://localhost:8080` 이 자동으로 열립니다.

## 어드민 서버 (라이선스 관리용 - 운영자만)

```bash
cd admin/
pip install -r requirements.txt
python admin_server.py
```

- 접속: http://localhost:9090/docs
- 기본 관리자: admin@admin.com / admin1234
- 고객사 등록 → 라이선스 키 발급

## 사용 흐름

### 최초 설정
1. 어드민에서 고객사 등록 → 라이선스 키 발급
2. 프로그램 실행 → 라이선스 키 입력 → 활성화
3. 계정관리 → 인스타 계정 등록 (크롤링용/DM용)
4. Chrome 실행 → 인스타그램 로그인 (최초 1회)

### 일상 사용
1. 프로그램 실행 (자동 로그인 유지)
2. 크롤링 → 해시태그 + 수집 수 → 시작
3. 유저관리 → 결과 확인 / Excel 내보내기
4. DM발송 → 템플릿 작성 → 발송

## 설정 변경

`config.yml` 에서 크롤링 속도, DM 한도 등 조정 가능.
프로그램 재시작 시 적용.

## 프록시 설정

`proxies.txt`에 추가 (형식: `IP:PORT:USERNAME:PASSWORD`)
설정 페이지 → "proxies.txt 다시 로드" 클릭
