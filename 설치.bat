@echo off
chcp 65001 > nul
title 을지 리뷰 관리프로그램 - 설치
echo ================================================
echo   을지 리뷰 관리프로그램 설치
echo ================================================
echo.

:: Python 확인
python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo.
    echo  1. https://www.python.org/downloads/ 접속
    echo  2. 최신 버전 다운로드 및 설치
    echo     ^(설치 시 "Add Python to PATH" 반드시 체크^)
    echo  3. 설치 완료 후 이 파일을 다시 실행하세요.
    echo.
    pause
    exit /b 1
)

echo [1/4] Python 확인 완료
echo.

echo [2/4] 필요한 패키지 설치 중... (수 분 소요)
pip install streamlit playwright anthropic python-dotenv requests pillow --quiet
if errorlevel 1 (
    echo [오류] 패키지 설치 실패. 인터넷 연결을 확인하세요.
    pause
    exit /b 1
)
echo       완료
echo.

echo [3/4] 브라우저 설치 중... (수 분 소요)
python -m playwright install chrome
if errorlevel 1 (
    python -m playwright install chromium
)
echo       완료
echo.

echo [4/4] 한국어 번역 방지 패치 적용 중...
python -c "import streamlit; from pathlib import Path; idx=Path(streamlit.__file__).parent/'static'/'index.html'; t=idx.read_text('utf-8'); t2=t.replace('<html lang=\"en\">','<html lang=\"ko\" translate=\"no\">'); t2=t2.replace('</head>','<meta name=\"google\" content=\"notranslate\" /></head>') if '<meta name=\"google\"' not in t2 else t2; idx.write_text(t2,'utf-8') if t!=t2 else None; print('패치 완료')"
echo.

echo ================================================
echo   설치 완료!
echo   이제 "실행.bat" 을 더블클릭하면 됩니다.
echo ================================================
pause
