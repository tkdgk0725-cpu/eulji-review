"""
인증 클라이언트 - 클라우드 auth_server 에 HTTP 로 연결.
관리자 앱과 가맹점주 앱 모두 이 파일을 사용 (배포 시 auth.py 로 복사).
"""
import os
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_SERVER_URL = os.getenv("AUTH_SERVER_URL", "").rstrip("/")
_API_KEY    = os.getenv("AUTH_API_KEY",    "euljireview2026")
_ADMIN_KEY  = os.getenv("AUTH_ADMIN_KEY",  "euljiadmin2026")
_TIMEOUT    = 8

USERS_FILE  = Path(__file__).parent / "users.json"   # 클라우드 버전에선 미사용


def _post(path, data, *, admin=False):
    key = _ADMIN_KEY if admin else _API_KEY
    if not _SERVER_URL:
        return {"ok": False, "reason": "AUTH_SERVER_URL 이 설정되지 않았습니다."}
    try:
        r = requests.post(f"{_SERVER_URL}{path}", json=data,
                          headers={"X-API-Key": key}, timeout=_TIMEOUT)
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"ok": False, "reason": "인증 서버에 연결할 수 없습니다."}
    except requests.exceptions.Timeout:
        return {"ok": False, "reason": "인증 서버 응답 시간 초과."}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _get(path, *, admin=False):
    key = _ADMIN_KEY if admin else _API_KEY
    if not _SERVER_URL:
        return None
    try:
        r = requests.get(f"{_SERVER_URL}{path}",
                         headers={"X-API-Key": key}, timeout=_TIMEOUT)
        return r.json()
    except Exception:
        return None


def _patch(path, data, *, admin=False):
    key = _ADMIN_KEY if admin else _API_KEY
    if not _SERVER_URL:
        return {"ok": False, "reason": "AUTH_SERVER_URL 이 설정되지 않았습니다."}
    try:
        r = requests.patch(f"{_SERVER_URL}{path}", json=data,
                           headers={"X-API-Key": key}, timeout=_TIMEOUT)
        return r.json()
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _delete(path, *, admin=False):
    key = _ADMIN_KEY if admin else _API_KEY
    if not _SERVER_URL:
        return
    try:
        requests.delete(f"{_SERVER_URL}{path}",
                        headers={"X-API-Key": key}, timeout=_TIMEOUT)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 공개 함수 (가맹점주 + 관리자)
# ---------------------------------------------------------------------------
def authenticate(username: str, password: str) -> dict:
    return _post("/auth/login", {"username": username, "password": password})


def register(username: str, password: str, name: str = "") -> dict:
    return _post("/auth/register", {"username": username, "password": password, "name": name})


def days_remaining(expires_at: str | None) -> int | None:
    if not expires_at:
        return None
    return (date.fromisoformat(expires_at) - date.today()).days


def load_users():
    result = _get("/admin/users", admin=True)
    if result and result.get("ok"):
        return {u["username"]: u for u in result.get("users", [])}
    return {}


# ---------------------------------------------------------------------------
# 관리자 함수
# ---------------------------------------------------------------------------
def all_users() -> list[dict]:
    result = _get("/admin/users", admin=True)
    if result and result.get("ok"):
        return result.get("users", [])
    return []


def add_user_by_admin(username: str, password: str, name: str,
                      role: str = "user", expires_at: str | None = None) -> dict:
    return _post("/admin/users", {
        "username": username, "password": password,
        "name": name, "role": role, "expires_at": expires_at,
    }, admin=True)


def set_expiry(username: str, expires_at: str | None) -> dict:
    return _patch(f"/admin/users/{username}/expiry", {"expires_at": expires_at}, admin=True)


def set_blocked(username: str, blocked: bool):
    _patch(f"/admin/users/{username}/blocked", {"blocked": blocked}, admin=True)


def delete_user(username: str):
    _delete(f"/admin/users/{username}", admin=True)


def change_password(username: str, new_pw: str) -> dict:
    return _patch(f"/admin/users/{username}/password", {"password": new_pw}, admin=True)
