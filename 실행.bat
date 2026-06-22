@echo off
chcp 65001 > nul
title 을지 리뷰 관리프로그램
cd /d "%~dp0"

:: Python 경로 자동 탐지
set "PY="
python --version >nul 2>&1 && set "PY=python" && goto :found
py --version >nul 2>&1 && set "PY=py" && goto :found
for /f "delims=" %%i in ('where python 2^>nul') do (set "PY=%%i" && goto :found)
echo [오류] Python을 찾을 수 없습니다. 설치.bat를 먼저 실행하세요.
pause
exit /b 1
:found

echo [업데이트 확인 중...]
%PY% updater.py 2>nul
echo.

:: Streamlit 준비될 때까지 대기 후 브라우저 열기
start /b cmd /c "timeout /t 15 /nobreak > nul && start http://localhost:8503"

%PY% -m streamlit run app.py --server.port 8503 --server.headless true --browser.gatherUsageStats false
pause
