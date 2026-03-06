@echo off
chcp 65001 >nul
title Instagram Service

echo.
echo ============================================
echo   Instagram Service를 시작합니다...
echo ============================================
echo.

cd /d "%~dp0"

REM Python3 확인
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo ============================================
    echo   Python이 설치되어 있지 않습니다!
    echo.
    echo   https://www.python.org 에서 다운로드하세요
    echo   설치 시 "Add Python to PATH" 체크 필수!
    echo ============================================
    echo.
    pause
    exit /b 1
)

python start.py

if %errorlevel% neq 0 (
    echo.
    echo 오류가 발생했습니다. 위의 메시지를 확인해주세요.
    pause
)
