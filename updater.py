"""
실행.bat에서 호출되는 자동 업데이트 스크립트.
GitHub에서 최신 .py 파일만 다운로드하고, 데이터 파일은 절대 건드리지 않음.
실패해도 기존 파일로 정상 실행됨.
"""
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit(0)

GITHUB_RAW = "https://raw.githubusercontent.com/tkdgk0725-cpu/eulji-review/main"
BASE_DIR = Path(__file__).parent

UPDATE_FILES = [
    "app.py",
    "baemin_bot.py",
    "coupangeats_bot.py",
    "auth.py",
    "updater.py",
    "launcher.py",
    "find_card_reviews.py",
    "find_ce_card_reviews.py",
]

updated = []
for fname in UPDATE_FILES:
    try:
        r = requests.get(f"{GITHUB_RAW}/{fname}", timeout=8)
        if not r.ok:
            continue
        target = BASE_DIR / fname
        if target.exists() and target.read_bytes() == r.content:
            continue
        target.write_bytes(r.content)
        updated.append(fname)
    except Exception:
        pass

if updated:
    print(f"  업데이트됨: {', '.join(updated)}")
else:
    print("  최신 버전입니다.")
