@echo off
chcp 65001 >nul
title Instagram Service Admin

echo.
echo ============================================
echo   어드민 서버를 시작합니다...
echo   접속: http://localhost:9090/docs
echo   기본 계정: admin@admin.com / admin1234
echo ============================================
echo.

cd /d "%~dp0\admin"
python start_admin.py

if %errorlevel% neq 0 (
    echo.
    echo 오류가 발생했습니다.
    pause
)
