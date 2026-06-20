"""
자동 업데이트 모듈.
앱 실행 시 GitHub 저장소에서 최신 코드를 확인하고 자동 업데이트.
.env, config.json 등 사용자 설정 파일은 절대 덮어쓰지 않음.
"""
import json
import os
import sys
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent

GITHUB_OWNER = "tkdgk0725"
GITHUB_REPO = "eulji-review"
GITHUB_BRANCH = "main"
VERSION_FILE = BASE_DIR / "version.json"

UPDATE_FILES = [
    "app.py",
    "baemin_bot.py",
    "coupangeats_bot.py",
    "auth.py",
    "updater.py",
]

NEVER_UPDATE = {".env", "config.json", "icon.png", "icon.ico"}


def _raw_url(filename: str) -> str:
    return f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{filename}"


def _api_url(path: str = "") -> str:
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/{path}"


def get_local_version() -> str:
    if VERSION_FILE.exists():
        data = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        return data.get("version", "0")
    return "0"


def _save_local_version(version: str):
    VERSION_FILE.write_text(
        json.dumps({"version": version}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_remote_version() -> str | None:
    try:
        r = requests.get(
            _raw_url("version.json"),
            timeout=5,
            headers={"Cache-Control": "no-cache"},
        )
        if r.ok:
            return r.json().get("version", "0")
    except Exception:
        pass
    return None


def check_update() -> dict:
    """업데이트 확인. {'available': bool, 'local': str, 'remote': str}"""
    local = get_local_version()
    remote = get_remote_version()
    if remote is None:
        return {"available": False, "local": local, "remote": None, "error": "서버 연결 실패"}
    return {
        "available": remote != local,
        "local": local,
        "remote": remote,
    }


def do_update(progress_callback=None) -> dict:
    """최신 파일을 다운로드해서 덮어쓴다. 성공 시 {'ok': True, 'updated': [...]}"""
    updated = []
    errors = []

    for i, filename in enumerate(UPDATE_FILES):
        if progress_callback:
            progress_callback(i, len(UPDATE_FILES), filename)
        try:
            r = requests.get(_raw_url(filename), timeout=10)
            if r.status_code == 404:
                continue
            if not r.ok:
                errors.append(f"{filename}: HTTP {r.status_code}")
                continue

            target = BASE_DIR / filename
            new_content = r.content

            if target.exists() and target.read_bytes() == new_content:
                continue

            target.write_bytes(new_content)
            updated.append(filename)
        except Exception as e:
            errors.append(f"{filename}: {e}")

    remote = get_remote_version()
    if remote:
        _save_local_version(remote)

    return {"ok": len(errors) == 0, "updated": updated, "errors": errors}
