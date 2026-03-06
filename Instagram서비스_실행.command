#!/bin/bash
# ========================================
#  Instagram Service 실행 (macOS)
#  이 파일을 더블클릭하면 프로그램이 실행됩니다
# ========================================

cd "$(dirname "$0")"

# Python3가 있는지 확인
if ! command -v python3 &> /dev/null; then
    echo ""
    echo "============================================"
    echo "  Python3가 설치되어 있지 않습니다!"
    echo ""
    echo "  아래 방법으로 설치해주세요:"
    echo "  1. https://www.python.org 에서 다운로드"
    echo "  2. 또는 터미널에서: brew install python3"
    echo "============================================"
    echo ""
    read -p "아무 키나 누르면 종료합니다..."
    exit 1
fi

echo ""
echo "============================================"
echo "  Instagram Service를 시작합니다..."
echo "============================================"
echo ""

python3 start.py

# 오류 발생 시 창이 바로 닫히지 않도록
if [ $? -ne 0 ]; then
    echo ""
    echo "오류가 발생했습니다. 위의 메시지를 확인해주세요."
    read -p "아무 키나 누르면 종료합니다..."
fi
