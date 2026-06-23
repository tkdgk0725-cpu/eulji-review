"""
실행.bat에서 호출되는 런처.
1) 자동 업데이트
2) Streamlit 실행
3) 브라우저 열기
"""
import subprocess
import sys
import time
import threading
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).parent
PORT = 8503


def run_updater():
    updater = BASE_DIR / "updater.py"
    if updater.exists():
        print("[업데이트 확인 중...]")
        subprocess.run([sys.executable, str(updater)], cwd=str(BASE_DIR))
        print()


def open_browser_delayed():
    time.sleep(12)
    webbrowser.open(f"http://localhost:{PORT}")


def start_streamlit():
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.port", str(PORT),
         "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        cwd=str(BASE_DIR),
    )


def cleanup_old_sessions():
    for f in ["ce_storage_state.json", "storage_state.json"]:
        p = BASE_DIR / f
        if p.exists():
            p.unlink()


if __name__ == "__main__":
    run_updater()
    cleanup_old_sessions()
    threading.Thread(target=open_browser_delayed, daemon=True).start()
    start_streamlit()
