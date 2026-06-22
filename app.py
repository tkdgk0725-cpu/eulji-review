"""을지 리뷰 관리프로그램 - 배민 + 쿠팡이츠 통합 (Streamlit)"""
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st
from playwright.sync_api import sync_playwright

import baemin_bot as bbot
import coupangeats_bot as cebot

# auth_client.py 있으면 클라우드 인증, 없으면 auth.py(로컬 또는 배포판 클라이언트)
try:
    import auth_client as auth
except ImportError:
    import auth

_ICON_PATH = Path(__file__).parent / "icon.png"
_ICON_B64 = base64.b64encode(_ICON_PATH.read_bytes()).decode() if _ICON_PATH.exists() else ""

st.set_page_config(
    page_title="을지 리뷰 관리프로그램",
    page_icon=str(_ICON_PATH) if _ICON_PATH.exists() else "📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# 전역 CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
/* 배경 */
[data-testid="stAppViewContainer"] > .main { background: #F4F6FB; }
[data-testid="stHeader"] { background: transparent; }

/* 헤더 */
.app-header {
    background: linear-gradient(135deg, #0F172A 0%, #1E293B 60%, #0F172A 100%);
    border-radius: 16px;
    padding: 26px 32px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.app-header-left { display: flex; align-items: center; gap: 14px; }
.app-logo {
    width: 44px; height: 44px;
    border-radius: 10px;
    overflow: hidden;
    display: flex; align-items: center; justify-content: center;
    background: rgba(255,255,255,0.10);
}
.app-logo img { width: 100%; height: 100%; object-fit: contain; }
.app-title { color: #F1F5F9; font-size: 20px; font-weight: 700; margin: 0; letter-spacing: -0.3px; }
.app-sub   { color: #64748B;  font-size: 12px; margin: 3px 0 0 0; }

/* 플랫폼 뱃지 */
.plat-badge {
    padding: 5px 14px; border-radius: 20px; font-size: 12px; font-weight: 700; letter-spacing: 0.3px;
}
.plat-baemin  { background: #00C47120; color: #00C471; border: 1px solid #00C47140; }
.plat-coupang { background: #EF3C2D20; color: #EF5350; border: 1px solid #EF3C2D40; }

/* 통계 배너 */
.stat-bar {
    display: flex; gap: 12px; margin: 12px 0;
}
.stat-card {
    flex: 1; background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px;
    padding: 16px 20px; text-align: center;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}
.stat-num   { font-size: 26px; font-weight: 800; color: #0F172A; line-height: 1.1; }
.stat-label { font-size: 12px; color: #94A3B8; margin-top: 3px; }
.stat-accent-b { border-top: 3px solid #00C471; }
.stat-accent-c { border-top: 3px solid #EF5350; }

/* 탭 스타일 */
.stTabs [data-baseweb="tab-list"] {
    background: #E8EDF5; border-radius: 10px; padding: 4px; gap: 2px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 7px; padding: 7px 20px; font-size: 13px; font-weight: 500; color: #64748B;
}
.stTabs [aria-selected="true"] {
    background: #FFFFFF !important; color: #0F172A !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.10);
}

/* 섹션 레이블 */
.section-label {
    font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;
    color: #94A3B8; margin: 20px 0 10px 0;
}

/* 리뷰 카드 */
.rv-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 14px;
    padding: 18px 22px 14px 22px;
    margin-bottom: 14px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}
.rv-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; margin-bottom: 10px; }
.rv-name { font-size: 15px; font-weight: 700; color: #0F172A; }
.rv-stars { color: #F59E0B; font-size: 13px; letter-spacing: 1px; }
.rv-chip {
    background: #F1F5F9; color: #475569; padding: 2px 9px;
    border-radius: 6px; font-size: 11px; font-weight: 500;
}
.rv-chip-date { background: #EFF6FF; color: #3B82F6; }
.rv-menu { font-size: 12px; color: #94A3B8; margin-bottom: 8px; }
.rv-text {
    font-size: 14px; color: #334155; line-height: 1.65;
    background: #F8FAFC; border-left: 3px solid #CBD5E1;
    border-radius: 0 8px 8px 0; padding: 10px 14px; margin-bottom: 12px;
}
.rv-empty { color: #94A3B8; font-size: 13px; font-style: italic; }
.rv-divider { border: none; border-top: 1px solid #F1F5F9; margin: 12px 0; }
.char-ok   { font-size: 11px; color: #94A3B8; text-align: right; margin-top: 2px; }
.char-warn { font-size: 11px; color: #EF4444; text-align: right; margin-top: 2px; font-weight: 600; }

/* 히스토리 타임라인 */
.hist-entry {
    border-left: 2px solid #E2E8F0; padding: 0 0 16px 16px; margin-bottom: 0;
}
.hist-date { font-size: 12px; font-weight: 600; color: #64748B; }
.hist-review { font-size: 13px; color: #334155; margin: 4px 0; }
.hist-reply { font-size: 13px; color: #0F172A; background: #F0FDF4; border-radius: 6px; padding: 6px 10px; }

/* 카드이벤트 픽 카드 */
.pick-card {
    background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px;
    padding: 18px 22px; margin-bottom: 14px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.pick-badge {
    display: inline-block; padding: 3px 10px; border-radius: 6px;
    font-size: 11px; font-weight: 700; margin-bottom: 8px;
}
.pick-badge-reorder  { background: #FFF7ED; color: #EA580C; }
.pick-badge-sincere  { background: #F0FDF4; color: #16A34A; }
.pick-reviewer { font-size: 16px; font-weight: 700; color: #0F172A; }
.pick-meta     { font-size: 12px; color: #94A3B8; margin-top: 2px; }
.pick-text     { font-size: 14px; color: #334155; margin-top: 10px; line-height: 1.6; }

/* 로그인 화면 */
.login-wrap {
    max-width: 400px; margin: 60px auto; padding: 40px 36px;
    background: #FFFFFF; border-radius: 20px;
    border: 1px solid #E2E8F0;
    box-shadow: 0 8px 32px rgba(0,0,0,0.08);
}
.login-logo { text-align: center; margin-bottom: 10px; }
.login-logo img { width: 90px; height: 90px; object-fit: contain; border-radius: 16px; }
.login-title { text-align: center; font-size: 20px; font-weight: 700; color: #0F172A; margin-bottom: 4px; }
.login-sub   { text-align: center; font-size: 13px; color: #94A3B8; margin-bottom: 24px; }
.login-label { font-size: 12px; font-weight: 600; color: #475569; margin-bottom: 4px; }

/* 사용자 관리 */
.user-row {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px; border-radius: 8px;
    background: #F8FAFC; border: 1px solid #E2E8F0; margin-bottom: 8px;
}
.user-badge-admin  { background: #FEF3C7; color: #92400E; padding: 2px 8px; border-radius: 5px; font-size: 11px; font-weight: 600; }
.user-badge-user   { background: #EFF6FF; color: #1D4ED8; padding: 2px 8px; border-radius: 5px; font-size: 11px; font-weight: 600; }
.user-badge-pending{ background: #FFF7ED; color: #C2410C; padding: 2px 8px; border-radius: 5px; font-size: 11px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 설정 동기화
# ---------------------------------------------------------------------------
def _sync_config_to_server():
    """로컬 config.json 내용을 서버에 동기화 (실패해도 무시)."""
    try:
        username = st.session_state.get("username", "")
        if username and hasattr(auth, "sync_config"):
            merged = {**bbot.load_config(), **cebot.load_config()}
            auth.sync_config(username, merged)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 인증 화면
# ---------------------------------------------------------------------------
def show_login():
    """로그인 / 접속 요청 화면. 인증 완료 시 st.rerun()."""
    mode = st.session_state.get("auth_mode", "login")

    _logo_html = (
        f'<img src="data:image/png;base64,{_ICON_B64}" alt="logo">'
        if _ICON_B64 else "📋"
    )
    st.markdown('<div class="login-wrap">', unsafe_allow_html=True)
    st.markdown(f'<div class="login-logo">{_logo_html}</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-title">을지 리뷰 관리프로그램</div>', unsafe_allow_html=True)

    if mode == "login":
        st.markdown('<div class="login-sub">로그인 후 이용할 수 있습니다</div>', unsafe_allow_html=True)
        with st.form("login_form"):
            username  = st.text_input("아이디", placeholder="아이디 입력")
            password  = st.text_input("비밀번호", placeholder="비밀번호 입력", type="password")
            submitted = st.form_submit_button("로그인", use_container_width=True, type="primary")
        if submitted:
            result = auth.authenticate(username, password)
            if result["ok"]:
                st.session_state["authenticated"] = True
                st.session_state["current_user"]  = result["user"]
                st.session_state["username"]      = username
                _sync_config_to_server()
                st.rerun()
            else:
                st.error(result["reason"])

        st.markdown('<br>', unsafe_allow_html=True)
        if st.button("계정 만들기 →", use_container_width=True):
            st.session_state["auth_mode"] = "register"
            st.rerun()

    else:  # register
        st.markdown('<div class="login-sub">가입 즉시 30일 무료 이용 가능합니다</div>',
                    unsafe_allow_html=True)
        with st.form("register_form"):
            username  = st.text_input("아이디 (3자 이상)", placeholder="사용할 아이디")
            name      = st.text_input("이름 / 별명",      placeholder="표시될 이름")
            password  = st.text_input("비밀번호 (6자 이상)", placeholder="비밀번호", type="password")
            pw_conf   = st.text_input("비밀번호 확인",      placeholder="비밀번호 재입력", type="password")
            submitted = st.form_submit_button("가입 및 시작하기", use_container_width=True, type="primary")
        if submitted:
            if password != pw_conf:
                st.error("비밀번호가 일치하지 않습니다.")
            else:
                result = auth.register(username, password, name)
                if result["ok"]:
                    st.success(f"가입 완료! 이용 기간: ~ {result['expires_at']}  \n"
                               "이제 로그인할 수 있습니다.")
                else:
                    st.error(result["reason"])

        st.markdown('<br>', unsafe_allow_html=True)
        if st.button("← 로그인으로 돌아가기", use_container_width=True):
            st.session_state["auth_mode"] = "login"
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


def show_admin_panel():
    """관리자 전용 — 계약기간·차단 관리 패널."""
    from datetime import date as _date

    users = auth.all_users()
    current_username = st.session_state["current_user"]["username"]

    st.markdown(f'<div class="section-label">전체 사용자 ({len(users)}명)</div>',
                unsafe_allow_html=True)

    for u in users:
        exp    = u.get("expires_at")
        days   = auth.days_remaining(exp)
        blocked = u.get("blocked", False)

        # 상태 뱃지
        if u["role"] == "admin":
            badge = '<span class="user-badge-admin">관리자</span>'
        elif blocked:
            badge = '<span class="user-badge-pending">차단됨</span>'
        elif days is not None and days < 0:
            badge = '<span class="user-badge-pending">만료</span>'
        elif days is not None and days <= 7:
            badge = f'<span class="user-badge-pending">D-{days}</span>'
        else:
            exp_str = f"~{exp}" if exp else "무제한"
            badge = f'<span class="user-badge-user">{exp_str}</span>'

        col_info, col_ext, col_blk, col_del = st.columns([3, 1.2, 1, 0.8])
        with col_info:
            st.markdown(
                f'<div class="user-row"><b>{u["name"]}</b>&nbsp;<code>{u["username"]}</code>'
                f'&nbsp;{badge}</div>',
                unsafe_allow_html=True)

        if u["username"] == current_username:
            continue  # 자기 자신 조작 불가

        with col_ext:
            # 기간 연장 버튼
            if st.button("기간 설정", key=f"ext_{u['username']}"):
                st.session_state["expiry_target"] = u["username"]
                st.session_state["expiry_current"] = exp or ""

        with col_blk:
            if blocked:
                if st.button("차단 해제", key=f"unblk_{u['username']}"):
                    auth.set_blocked(u["username"], False)
                    st.rerun()
            else:
                if st.button("차단", key=f"blk_{u['username']}"):
                    auth.set_blocked(u["username"], True)
                    st.rerun()

        with col_del:
            if st.button("삭제", key=f"del_{u['username']}"):
                auth.delete_user(u["username"])
                st.rerun()

    # 기간 설정 폼
    exp_target = st.session_state.get("expiry_target")
    if exp_target:
        st.divider()
        st.markdown(f"**{exp_target}** — 이용 기간 설정")
        with st.form("set_expiry_form"):
            c1, c2 = st.columns(2)
            quick = c1.selectbox("빠른 선택",
                                  ["직접 입력", "+30일", "+60일", "+90일", "+180일", "+1년", "무제한"])
            manual = c2.text_input("직접 입력 (YYYY-MM-DD)",
                                    value=st.session_state.get("expiry_current", ""))
            if st.form_submit_button("저장"):
                if quick == "무제한":
                    new_exp = None
                elif quick == "직접 입력":
                    new_exp = manual.strip() or None
                else:
                    days_add = {"30": 30, "60": 60, "90": 90, "180": 180, "1": 365}
                    n = int(quick.replace("+", "").replace("일", "").replace("년", ""))
                    from datetime import timedelta
                    new_exp = (_date.today() + timedelta(days=n if "년" not in quick else 365)).isoformat()
                res = auth.set_expiry(exp_target, new_exp)
                if res["ok"]:
                    label = new_exp or "무제한"
                    st.success(f"이용 기간이 {label} 로 설정되었습니다.")
                    del st.session_state["expiry_target"]
                    st.rerun()
                else:
                    st.error(res["reason"])

    st.divider()

    # 계정 직접 추가
    st.markdown('<div class="section-label">계정 직접 추가</div>', unsafe_allow_html=True)
    with st.form("add_user_form"):
        c1, c2 = st.columns(2)
        new_id   = c1.text_input("아이디")
        new_name = c2.text_input("이름")
        new_pw   = c1.text_input("비밀번호", type="password")
        new_role = c2.selectbox("권한", ["user", "admin"])
        exp_opt  = c1.selectbox("이용 기간", ["+30일", "+60일", "+90일", "+180일", "+1년", "무제한"])
        if st.form_submit_button("추가"):
            from datetime import timedelta
            if exp_opt == "무제한":
                exp_val = None
            else:
                n_map = {"+30일": 30, "+60일": 60, "+90일": 90, "+180일": 180, "+1년": 365}
                exp_val = (_date.today() + timedelta(days=n_map[exp_opt])).isoformat()
            res = auth.add_user_by_admin(new_id, new_pw, new_name, new_role, exp_val)
            if res["ok"]:
                st.success(f"{new_id} 계정이 추가되었습니다.")
                st.rerun()
            else:
                st.error(res["reason"])

    # 내 비밀번호 변경
    st.divider()
    st.markdown('<div class="section-label">내 비밀번호 변경</div>', unsafe_allow_html=True)
    with st.form("change_my_pw"):
        new_pw = st.text_input("새 비밀번호", type="password")
        if st.form_submit_button("변경"):
            res = auth.change_password(current_username, new_pw)
            st.success("변경되었습니다.") if res["ok"] else st.error(res["reason"])


# ---------------------------------------------------------------------------
# 인증 게이트
# ---------------------------------------------------------------------------
if not st.session_state.get("authenticated"):
    show_login()
    st.stop()

current_user = st.session_state["current_user"]
is_admin     = current_user.get("role") == "admin"

# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def stars_html(n: int, total: int = 5) -> str:
    return "★" * n + "☆" * max(0, total - n)


def render_review_header(reviewer: str, stars: int, date: str,
                          order_count: int | None = None, menu: str | None = None):
    chips = f'<span class="rv-chip rv-chip-date">{date}</span>' if date else ""
    if order_count is not None:
        chips += f'<span class="rv-chip">주문 {order_count}회</span>'
    menu_line = f'<div class="rv-menu">메뉴 · {menu}</div>' if menu else ""
    st.markdown(f"""
<div class="rv-meta">
  <span class="rv-name">{reviewer}</span>
  <span class="rv-stars">{stars_html(stars)}</span>
  {chips}
</div>
{menu_line}
""", unsafe_allow_html=True)


def render_review_text(text: str):
    if text:
        st.markdown(f'<div class="rv-text">{text.replace(chr(10), "<br>")}</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="rv-text rv-empty">(리뷰 내용 없음)</div>',
                    unsafe_allow_html=True)


def char_count_html(n: int, limit: int | None = None) -> str:
    if limit:
        cls = "char-warn" if n > limit else "char-ok"
        return f'<div class="{cls}">{n} / {limit}자</div>'
    return f'<div class="char-ok">{n}자</div>'


# ---------------------------------------------------------------------------
# 앱 헤더 + 플랫폼 선택
# ---------------------------------------------------------------------------
platform = st.session_state.get("platform", "배민")

col_hdr, col_radio = st.columns([3, 1])
with col_hdr:
    badge_class = "plat-baemin" if platform == "배민" else "plat-coupang"
    badge_text  = "배민" if platform == "배민" else "쿠팡이츠"
    user_name   = current_user.get("name", current_user.get("username", ""))
    st.markdown(f"""
<div class="app-header">
  <div class="app-header-left">
    <div class="app-logo"><img src="data:image/png;base64,{_ICON_B64}" alt="logo"></div>
    <div>
      <p class="app-title">을지 리뷰 관리프로그램</p>
      <p class="app-sub">AI 기반 리뷰 자동 답글 관리 시스템</p>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:10px">
    <span style="color:#64748B;font-size:13px">{user_name}</span>
    <span class="plat-badge {badge_class}">{badge_text}</span>
  </div>
</div>
""", unsafe_allow_html=True)

with col_radio:
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    platform = st.radio(
        "플랫폼",
        ["배민", "쿠팡이츠"],
        horizontal=False,
        key="platform",
        label_visibility="collapsed",
    )
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    if is_admin and st.button("사용자 관리", use_container_width=True):
        st.session_state["show_admin"] = not st.session_state.get("show_admin", False)
        st.rerun()
    if st.button("로그아웃", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# 관리자 패널 (토글)
if is_admin and st.session_state.get("show_admin"):
    with st.expander("사용자 관리 패널", expanded=True):
        show_admin_panel()

    # ----- 관리자 대시보드 탭 -----
    dash_tabs = st.tabs(["가맹점 설정/계정", "리뷰·답글 현황", "리뷰어 히스토리"])

    # 탭1: 가맹점 설정/계정
    with dash_tabs[0]:
        if hasattr(auth, "all_configs"):
            configs = auth.all_configs()
            if not configs:
                st.info("등록된 가맹점 설정이 없습니다.")
            else:
                for cfg in configs:
                    uname = cfg.get("username", "?")
                    with st.container(border=True):
                        st.markdown(f"**{uname}** — {cfg.get('store_name', '미설정')}")
                        c1, c2 = st.columns(2)
                        with c1:
                            st.text(f"배민 ID: {cfg.get('baemin_id', '-')}")
                            st.text(f"배민 PW: {cfg.get('baemin_pw', '-')}")
                            st.text(f"Shop ID: {cfg.get('shop_id', '-')}")
                        with c2:
                            st.text(f"쿠팡 ID: {cfg.get('coupang_id', '-')}")
                            st.text(f"쿠팡 PW: {cfg.get('coupang_pw', '-')}")
                        st.caption(f"답글톤: {cfg.get('store_tone', '-')}")
                        st.caption(f"최종 수정: {cfg.get('updated_at', '-')}")

    # 탭2: 리뷰·답글 현황
    with dash_tabs[1]:
        if hasattr(auth, "get_store_stats"):
            stats = auth.get_store_stats()
            if stats:
                st.markdown("**가맹점별 답글 현황**")
                for s in stats:
                    st.metric(
                        label=s["username"],
                        value=f"{s['total_replies']}건",
                        delta=f"평균 {s['avg_rating']}점",
                    )
                st.divider()

            # 가맹점 필터
            filter_user = st.selectbox(
                "가맹점 선택",
                ["전체"] + [s["username"] for s in stats] if stats else ["전체"],
                key="dash_filter_user",
            )
            sel_user = None if filter_user == "전체" else filter_user
            logs = auth.get_review_logs(username=sel_user, limit=100)
            if not logs:
                st.info("등록된 답글 로그가 없습니다.")
            else:
                for log in logs:
                    with st.container(border=True):
                        hdr = f"**{log.get('username', '?')}** | {log.get('platform', '')} | {log.get('review_date', '')}"
                        st.markdown(hdr)
                        st.markdown(f"{log.get('reviewer', '?')} ★{log.get('rating', '?')}")
                        st.text(f"리뷰: {log.get('review_text', '-')[:100]}")
                        st.text(f"답글: {log.get('reply_text', '-')[:100]}")
                        st.caption(f"등록: {log.get('replied_at', '-')}")
        else:
            st.warning("리뷰 로그 기능이 서버에 없습니다.")

    # 탭3: 리뷰어 히스토리
    with dash_tabs[2]:
        if hasattr(auth, "get_reviewer_history"):
            search = st.text_input("리뷰어 닉네임 검색", key="dash_reviewer_search",
                                    placeholder="닉네임 입력 후 Enter")
            if search:
                hist = auth.get_reviewer_history(search.strip())
                if not hist:
                    st.info(f"'{search}' 리뷰어의 기록이 없습니다.")
                else:
                    st.markdown(f"**{search}** — 총 {len(hist)}건")
                    for h in hist:
                        with st.container(border=True):
                            st.markdown(f"★{h.get('rating', '?')} | {h.get('review_date', '')} | {h.get('username', '')}")
                            st.text(f"리뷰: {h.get('review_text', '-')[:100]}")
                            st.text(f"답글: {h.get('reply_text', '-')[:100]}")

    st.divider()


# ===========================================================================
#  공통 탭 렌더러
# ===========================================================================
def tab_replies(platform_key: str):
    """탭 1 – 답글 검토/등록 (배민·쿠팡이츠 공통 레이아웃)"""
    is_baemin  = platform_key == "baemin"
    rev_key    = "baemin_reviews" if is_baemin else "ce_reviews"
    draft_pfx  = "bd_" if is_baemin else "ced_"
    accent_cls = "stat-accent-b" if is_baemin else "stat-accent-c"

    st.markdown('<div class="section-label">리뷰 불러오기</div>', unsafe_allow_html=True)

    # 기간 선택 (배민·쿠팡이츠 공통)
    period_key = "baemin_period" if is_baemin else "ce_period"
    options = ["1일", "3일", "7일", "1달", "전체"]
    period = st.radio(
        "기간",
        options,
        horizontal=True,
        key=period_key,
        label_visibility="collapsed",
    )

    col_btn, col_info = st.columns([2, 3])
    with col_btn:
        fetch_label = f"미답변 리뷰 불러오기 ({period})"
        fetch_clicked = st.button(fetch_label, key=f"{platform_key}_fetch", use_container_width=True)

    if fetch_clicked:
        if is_baemin:
            days_map = {"1일": 1, "3일": 3, "7일": 7, "1달": 30, "전체": None}
            days = days_map[period]
            history = bbot.load_history()
            with st.spinner(f"배민 미답변 리뷰 불러오는 중 ({period})..."):
                with sync_playwright() as pw:
                    browser, _ctx, page = bbot.login(pw)
                    try:
                        reviews = bbot.fetch_unanswered_reviews(page, history, days=days)
                    finally:
                        browser.close()
            with st.spinner(f"AI 답글 초안 생성 중... ({len(reviews)}건 병렬 처리)"):
                bbot.generate_draft_replies(reviews)
            st.session_state[rev_key] = reviews
        else:
            with st.spinner(f"쿠팡이츠 리뷰 불러오는 중 ({period})..."):
                with sync_playwright() as pw:
                    browser, _ctx, page = cebot.login(pw)
                    try:
                        page.goto(cebot.REVIEW_URL)
                        all_rv = cebot.fetch_reviews(page, period=period)
                    finally:
                        browser.close()
            config = cebot.load_config()
            unanswered = [r for r in all_rv if not r["has_replied"]]
            with st.spinner(f"AI 답글 초안 생성 중... ({len(unanswered)}건 병렬 처리)"):
                cebot.generate_draft_replies(unanswered, config)
            st.session_state[rev_key] = unanswered
            st.session_state["ce_period_used"] = period
            st.session_state["ce_total"] = len(all_rv)

    reviews = st.session_state.get(rev_key, [])

    # 통계 배너
    if reviews:
        total_ce = st.session_state.get("ce_total", len(reviews)) if not is_baemin else len(reviews)
        stat_label_total = "미답변" if is_baemin else "전체 조회"
        stat_total       = len(reviews) if is_baemin else total_ce
        stat_unanswered  = len(reviews)

        st.markdown(f"""
<div class="stat-bar">
  <div class="stat-card {accent_cls}">
    <div class="stat-num">{stat_total}</div>
    <div class="stat-label">{stat_label_total}</div>
  </div>
  <div class="stat-card">
    <div class="stat-num">{stat_unanswered}</div>
    <div class="stat-label">답글 대기</div>
  </div>
  <div class="stat-card">
    <div class="stat-num">{stat_total - stat_unanswered if not is_baemin else 0}</div>
    <div class="stat-label">답변 완료</div>
  </div>
</div>
""", unsafe_allow_html=True)

    if not reviews:
        st.info("위 버튼을 눌러 미답변 리뷰를 가져오세요.")
        return

    # 전체 등록하기
    st.markdown('<div class="section-label">일괄 등록</div>', unsafe_allow_html=True)
    if st.button("전체 등록하기", type="primary", key=f"{platform_key}_post_all",
                 use_container_width=False):
        if is_baemin:
            history = bbot.load_history()
            items = [
                {"review_no": r["review_no"],
                 "reply_text": st.session_state.get(f"{draft_pfx}{r['review_no']}",
                                                     r.get("draft_reply", ""))}
                for r in reviews
            ]
            with st.spinner(f"{len(reviews)}건 일괄 등록 중..."):
                with sync_playwright() as pw:
                    browser, _ctx, page = bbot.login(pw)
                    try:
                        ok_cnt, fail_cnt = bbot.submit_all_replies(page, items)
                    finally:
                        browser.close()
            reply_map = {i["review_no"]: i["reply_text"] for i in items}
            for rv in reviews:
                rt = reply_map.get(rv["review_no"], "")
                entry = history.get(rv["reviewer"], {"reviews": []})
                entry["reviews"].append(bbot.make_history_record(rv, rt))
                history[rv["reviewer"]] = entry
            bbot.save_history(history)
        else:
            _period_used = st.session_state.get("ce_period_used", "오늘")
            ok_cnt = fail_cnt = 0
            with st.spinner(f"{len(reviews)}건 일괄 등록 중..."):
                with sync_playwright() as pw:
                    browser, _ctx, page = cebot.login(pw)
                    try:
                        page.goto(cebot.REVIEW_URL)
                        cebot.prepare_page(page, period=_period_used)
                        for i, rv in enumerate(reviews):
                            reply_text = st.session_state.get(f"{draft_pfx}{i}",
                                                               rv.get("draft_reply", ""))
                            ok = cebot.post_reply(page, rv["row_index"], reply_text,
                                                  page_num=rv.get("page_num", 1))
                            if ok:
                                cebot.update_history(rv, reply_text)
                                ok_cnt += 1
                            else:
                                fail_cnt += 1
                    finally:
                        browser.close()

        if ok_cnt:
            st.success(f"{ok_cnt}건 등록 완료!")
        if fail_cnt:
            st.error(f"{fail_cnt}건 실패.")
        st.session_state[rev_key] = [] if not fail_cnt else (
            [reviews[i] for i in range(len(reviews)) if i >= ok_cnt] if not is_baemin else reviews
        )
        st.rerun()

    # 리뷰 카드 목록
    st.markdown('<div class="section-label">답글 초안 검토</div>', unsafe_allow_html=True)

    for idx, rv in enumerate(reviews):
        if is_baemin:
            rno         = rv["review_no"]
            reviewer    = rv["reviewer"]
            rating      = rv["rating"]
            date        = rv.get("date", "")
            menu        = rv.get("menu", "")
            review_text = rv.get("text", "")
            uid         = rno or f"{idx}_{reviewer}"
            draft_key   = f"{draft_pfx}{uid}"
            post_key    = f"{platform_key}_post_{uid}"
            char_limit  = None
        else:
            rno         = str(idx)
            reviewer    = rv["reviewer"]
            rating      = rv["stars"]
            date        = rv.get("date", "")
            menu        = None
            review_text = rv.get("review_text", "")
            draft_key   = f"{draft_pfx}{idx}"
            post_key    = f"{platform_key}_post_{idx}"
            char_limit  = 300

        if draft_key not in st.session_state:
            st.session_state[draft_key] = rv.get("draft_reply", "")

        with st.container(border=True):
            render_review_header(reviewer, rating, date,
                                  order_count=rv.get("order_count") if not is_baemin else None,
                                  menu=menu or None)
            render_review_text(review_text)

            st.markdown('<hr class="rv-divider">', unsafe_allow_html=True)
            st.text_area("AI 초안 답글 (수정 가능)", key=draft_key, height=72,
                          label_visibility="collapsed")
            cur_len = len(st.session_state.get(draft_key, ""))
            st.markdown(char_count_html(cur_len, char_limit), unsafe_allow_html=True)

            col_post, col_space = st.columns([1, 4])
            with col_post:
                if st.button("등록", key=post_key, use_container_width=True):
                    reply_text = st.session_state[draft_key]
                    if char_limit and len(reply_text) > char_limit:
                        st.error(f"{char_limit}자를 초과했습니다.")
                    else:
                        with st.spinner("등록 중..."):
                            if is_baemin:
                                with sync_playwright() as pw:
                                    browser, _ctx, page = bbot.login(pw)
                                    try:
                                        ok = bbot.submit_reply_by_review_no(
                                            page, rno, reply_text,
                                            reviewer=reviewer, review_date=date)
                                    finally:
                                        browser.close()
                                if ok:
                                    history = bbot.load_history()
                                    entry = history.get(reviewer, {"reviews": []})
                                    entry["reviews"].append(bbot.make_history_record(rv, reply_text))
                                    history[reviewer] = entry
                                    bbot.save_history(history)
                            else:
                                _period_used = st.session_state.get("ce_period_used", "오늘")
                                _ce_err = ""
                                ok = False
                                _browser = None
                                try:
                                    with sync_playwright() as pw:
                                        _browser, _ctx, page = cebot.login(pw)
                                        try:
                                            page.goto(cebot.REVIEW_URL)
                                            cebot.prepare_page(page, period=_period_used)
                                            ok = cebot.post_reply(page, rv["row_index"], reply_text,
                                                                  page_num=rv.get("page_num", 1))
                                        finally:
                                            _browser.close()
                                except Exception as _e:
                                    ok = False
                                    _ce_err = str(_e)
                                if ok:
                                    cebot.update_history(rv, reply_text)

                        if ok:
                            try:
                                if hasattr(auth, "log_reply"):
                                    auth.log_reply(
                                        username=st.session_state.get("username", ""),
                                        platform="baemin" if is_baemin else "coupangeats",
                                        reviewer=reviewer,
                                        rating=rating,
                                        review_text=review_text[:500],
                                        menu=menu[:200] if menu else "",
                                        reply_text=reply_text,
                                        review_date=date,
                                    )
                            except Exception:
                                pass
                            st.success("등록 완료!")
                            remaining = [r for j, r in enumerate(reviews) if j != idx]
                            st.session_state[rev_key] = remaining
                            st.rerun()
                        else:
                            st.error(f"등록 실패: {_ce_err}" if not is_baemin and _ce_err else "등록 실패.")


def tab_history(platform_key: str):
    """탭 2 – 리뷰어 히스토리"""
    is_baemin = platform_key == "baemin"
    history   = bbot.load_history() if is_baemin else cebot.load_history()

    query = st.text_input("리뷰어 검색", placeholder="닉네임으로 검색...",
                           key=f"{platform_key}_hist_query", label_visibility="collapsed")
    names = sorted(history.keys())
    if query:
        names = [n for n in names if query in n]

    if not names:
        st.info("히스토리가 없습니다." if not history else "검색 결과가 없습니다.")
        return

    for name in names:
        entry = history[name]
        rvs   = entry.get("reviews", [])
        total = len(rvs)
        with st.expander(f"**{name}**  ·  {total}건", expanded=False):
            for rv in reversed(rvs):
                if is_baemin:
                    rating = rv.get("rating", "?")
                    rv_text = rv.get("review_text") or "(내용 없음)"
                    rep_text = rv.get("reply") or ""
                else:
                    rating = rv.get("stars", "?")
                    rv_text = rv.get("review_text") or "(내용 없음)"
                    rep_text = rv.get("reply_text") or ""

                st.markdown(f"""
<div class="hist-entry">
  <div class="hist-date">{'★' * int(rating) if isinstance(rating, int) else '?'}&nbsp;&nbsp;{rv.get('date','')}&nbsp;&nbsp;{rv.get('replied_at','')}</div>
  <div class="hist-review">{rv_text[:120]}{'…' if len(rv_text) > 120 else ''}</div>
  <div class="hist-reply">{rep_text}</div>
</div>
""", unsafe_allow_html=True)


def tab_card_event(platform_key: str):
    """탭 3 – 주간 카드이벤트 리뷰"""
    is_baemin  = platform_key == "baemin"
    script     = "find_card_reviews.py" if is_baemin else "find_ce_card_reviews.py"
    base_dir   = bbot.BASE_DIR if is_baemin else cebot.BASE_DIR
    picks_file = base_dir / ("card_review_picks.json" if is_baemin else "ce_card_review_picks.json")
    btn_key    = f"{platform_key}_card_run"
    sel_key    = f"{platform_key}_card_date"

    if st.button("이번 주 후보 찾기 + 자동 선정", type="primary", key=btn_key,
                  use_container_width=False):
        with st.spinner("최근 1주일 리뷰에서 카드 인증 사진을 AI로 분석 중... (몇 분 소요)"):
            result = subprocess.run(
                [sys.executable, script],
                cwd=str(base_dir),
                capture_output=True, text=True, encoding="utf-8",
            )
        if result.returncode == 0:
            st.success("선정이 완료되었습니다.")
        else:
            st.error("선정 중 오류가 발생했습니다.")
        with st.expander("실행 로그"):
            st.code(result.stdout or "(출력 없음)", language=None)
            if result.stderr:
                st.code(result.stderr, language=None)

    if not picks_file.exists():
        st.info("아직 선정 결과가 없습니다.")
        return

    data = json.loads(picks_file.read_text(encoding="utf-8"))
    runs = data.get("runs", [])
    if not runs:
        st.info("아직 선정 결과가 없습니다.")
        return

    selected_date = st.selectbox(
        "주차", options=[r["date"] for r in reversed(runs)], key=sel_key,
        label_visibility="collapsed",
    )
    run = next(r for r in runs if r["date"] == selected_date)

    for pick in run["picks"]:
        cat   = pick["category"]
        is_re = "재주문" in cat
        badge_cls  = "pick-badge-reorder" if is_re else "pick-badge-sincere"
        badge_text = "재주문 최다" if is_re else "정성 리뷰"
        st.markdown(f"""
<div class="pick-card">
  <span class="pick-badge {badge_cls}">{badge_text}</span>
  <div class="pick-reviewer">{pick['reviewer']}</div>
  <div class="pick-meta">{pick['date_written']} · 주문 {pick['order_count']}회 · 카드 NO.{pick['card_no']}</div>
  <div class="pick-text">{pick.get('review_text','')}</div>
</div>
""", unsafe_allow_html=True)
        images = pick.get("images", [])
        if images:
            cols = st.columns(min(len(images), 3))
            for col, img_path in zip(cols, images):
                full = base_dir / img_path
                if full.exists():
                    col.image(str(full))


def tab_settings(platform_key: str):
    """탭 4 – 설정"""
    is_baemin = platform_key == "baemin"
    config    = bbot.load_config() if is_baemin else cebot.load_config()

    st.markdown('<div class="section-label">가게 정보</div>', unsafe_allow_html=True)
    store_name = st.text_input("가게 이름", value=config.get("store_name", ""),
                                key=f"{platform_key}_sname")
    store_tone = st.text_area("답글 톤 / 말투", value=config.get("store_tone", ""),
                               height=110, key=f"{platform_key}_stone")

    st.markdown('<div class="section-label">로그인 정보</div>', unsafe_allow_html=True)
    if is_baemin:
        baemin_id = st.text_input("배민 아이디", value=config.get("baemin_id", ""), key="b_id")
        baemin_pw = st.text_input("배민 비밀번호", value=config.get("baemin_pw", ""),
                                   type="password", key="b_pw")
        shop_url  = st.text_input(
            "배민 리뷰창 URL",
            value=f"https://self.baemin.com/shops/{config['shop_id']}/reviews"
                  if config.get("shop_id") else "",
            placeholder="https://self.baemin.com/shops/123456/reviews",
            key="b_url",
        )
        if st.button("저장", key="b_save"):
            shop_id = bbot.extract_shop_id(shop_url)
            if not shop_id:
                st.error("URL에서 가게 번호를 찾을 수 없습니다.")
            else:
                bbot.save_config({**config, "store_name": store_name, "store_tone": store_tone,
                                   "baemin_id": baemin_id, "baemin_pw": baemin_pw,
                                   "shop_id": shop_id})
                _sync_config_to_server()
                st.success("저장되었습니다.")
    else:
        coupang_id = st.text_input("쿠팡이츠 아이디", value=config.get("coupang_id", ""), key="c_id")
        coupang_pw = st.text_input("쿠팡이츠 비밀번호", value=config.get("coupang_pw", ""),
                                    type="password", key="c_pw")
        if st.button("저장", key="c_save"):
            cebot.save_config({**config, "store_name": store_name, "store_tone": store_tone,
                                "coupang_id": coupang_id, "coupang_pw": coupang_pw})
            _sync_config_to_server()
            st.success("저장되었습니다.")


# ===========================================================================
#  배민
# ===========================================================================
if platform == "배민":
    _config = bbot.load_config()
    if not bbot.is_configured(_config):
        st.subheader("초기 설정 — 배민")
        with st.form("baemin_setup"):
            _sn  = st.text_input("가게 이름", value=_config.get("store_name", ""))
            _st  = st.text_area("답글 톤/말투", value=_config.get("store_tone", bbot.DEFAULT_STORE_TONE), height=90)
            _bid = st.text_input("배민 아이디")
            _bpw = st.text_input("배민 비밀번호", type="password")
            _url = st.text_input("배민 리뷰창 URL", placeholder="https://self.baemin.com/shops/123456/reviews")
            if st.form_submit_button("저장하고 시작하기"):
                sid = bbot.extract_shop_id(_url)
                if not sid:
                    st.error("URL에서 가게 번호를 찾을 수 없습니다.")
                else:
                    bbot.save_config({**_config, "store_name": _sn, "store_tone": _st,
                                      "baemin_id": _bid, "baemin_pw": _bpw, "shop_id": sid})
                    _sync_config_to_server()
                    st.rerun()
        st.stop()

    t1, t2, t3, t4 = st.tabs(["답글 검토/등록", "리뷰어 히스토리", "주간 카드이벤트", "설정"])
    with t1: tab_replies("baemin")
    with t2: tab_history("baemin")
    with t3: tab_card_event("baemin")
    with t4: tab_settings("baemin")

# ===========================================================================
#  쿠팡이츠
# ===========================================================================
elif platform == "쿠팡이츠":
    _ce_config = cebot.load_config()
    if not cebot.is_configured(_ce_config):
        st.subheader("초기 설정 — 쿠팡이츠")
        with st.form("ce_setup"):
            _sn  = st.text_input("가게 이름", value=_ce_config.get("store_name", ""))
            _st  = st.text_area("답글 톤/말투", value=_ce_config.get("store_tone", ""), height=90)
            _cid = st.text_input("쿠팡이츠 아이디")
            _cpw = st.text_input("쿠팡이츠 비밀번호", type="password")
            if st.form_submit_button("저장하고 시작하기"):
                cebot.save_config({**_ce_config, "store_name": _sn, "store_tone": _st,
                                   "coupang_id": _cid, "coupang_pw": _cpw})
                _sync_config_to_server()
                st.rerun()
        st.stop()

    t1, t2, t3, t4 = st.tabs(["답글 검토/등록", "리뷰어 히스토리", "주간 카드이벤트", "설정"])
    with t1: tab_replies("coupangeats")
    with t2: tab_history("coupangeats")
    with t3: tab_card_event("coupangeats")
    with t4: tab_settings("coupangeats")
