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
_TIMEOUT    = 30
_MAX_RETRIES = 3

USERS_FILE  = Path(__file__).parent / "users.json"   # 클라우드 버전에선 미사용


def _post(path, data, *, admin=False):
    key = _ADMIN_KEY if admin else _API_KEY
    if not _SERVER_URL:
        return {"ok": False, "reason": "AUTH_SERVER_URL 이 설정되지 않았습니다."}
    import time
    for attempt in range(_MAX_RETRIES):
        try:
            r = requests.post(f"{_SERVER_URL}{path}", json=data,
                              headers={"X-API-Key": key}, timeout=_TIMEOUT)
            return r.json()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < _MAX_RETRIES - 1:
                time.sleep(3)
                continue
            return {"ok": False, "reason": "인증 서버 연결 실패 (서버 시작 중일 수 있습니다. 다시 시도해주세요.)"}
        except Exception as e:
            return {"ok": False, "reason": str(e)}


def _get(path, *, admin=False):
    key = _ADMIN_KEY if admin else _API_KEY
    if not _SERVER_URL:
        return None
    import time
    for attempt in range(_MAX_RETRIES):
        try:
            r = requests.get(f"{_SERVER_URL}{path}",
                             headers={"X-API-Key": key}, timeout=_TIMEOUT)
            return r.json()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < _MAX_RETRIES - 1:
                time.sleep(3)
                continue
            return None
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


# ---------------------------------------------------------------------------
# 가맹점 설정 동기화
# ---------------------------------------------------------------------------
def sync_config(username: str, config: dict) -> dict:
    return _post("/config/sync", {"username": username, "config": config})


def all_configs() -> list[dict]:
    result = _get("/admin/configs", admin=True)
    if result and result.get("ok"):
        return result.get("configs", [])
    return []


def get_config(username: str) -> dict | None:
    result = _get(f"/admin/configs/{username}", admin=True)
    if result and result.get("ok"):
        return result.get("config")
    return None


# ---------------------------------------------------------------------------
# 리뷰/답글 로그
# ---------------------------------------------------------------------------
def log_reply(username: str, platform: str, reviewer: str, rating: int,
              review_text: str, menu: str, reply_text: str, review_date: str) -> dict:
    return _post("/reviews/log", {
        "username": username, "platform": platform,
        "reviewer": reviewer, "rating": rating,
        "review_text": review_text, "menu": menu,
        "reply_text": reply_text, "review_date": review_date,
    })


def get_review_logs(username: str | None = None, limit: int = 200) -> list[dict]:
    path = f"/admin/reviews?limit={limit}"
    if username:
        path += f"&username={username}"
    result = _get(path, admin=True)
    if result and result.get("ok"):
        return result.get("logs", [])
    return []


def get_store_stats() -> list[dict]:
    result = _get("/admin/reviews/stats", admin=True)
    if result and result.get("ok"):
        return result.get("stats", [])
    return []


def get_reviewer_history(reviewer: str) -> list[dict]:
    result = _get(f"/admin/reviewer/{reviewer}", admin=True)
    if result and result.get("ok"):
        return result.get("history", [])
    return []
