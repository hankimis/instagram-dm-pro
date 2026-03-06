#!/bin/bash
cd "$(dirname "$0")/admin"

if ! command -v python3 &> /dev/null; then
    echo "Python3가 설치되어 있지 않습니다!"
    echo "https://www.python.org 에서 설치해주세요."
    read -p "아무 키나 누르면 종료합니다..."
    exit 1
fi

echo ""
echo "============================================"
echo "  어드민 서버를 시작합니다..."
echo "  접속: http://localhost:9090/docs"
echo "  기본 계정: admin@admin.com / admin1234"
echo "============================================"
echo ""

python3 start_admin.py

if [ $? -ne 0 ]; then
    echo ""
    echo "오류가 발생했습니다."
    read -p "아무 키나 누르면 종료합니다..."
fi
