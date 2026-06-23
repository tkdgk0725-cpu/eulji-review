"""
쿠팡이츠 사장님 포털 리뷰 자동 답글 봇.
"""
import sys
import re
import json
from pathlib import Path
import time
from datetime import datetime, date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from anthropic import Anthropic
import os

load_dotenv()

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
CE_STORAGE_FILE = BASE_DIR / "ce_storage_state.json"
CE_HISTORY_FILE = BASE_DIR / "ce_reviewer_history.json"
CE_NEGATIVE_FILE = BASE_DIR / "ce_negative_reviews.json"

LOGIN_URL = "https://store.coupangeats.com/merchant/login"
REVIEW_URL = "https://store.coupangeats.com/merchant/management/reviews"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

client = Anthropic(api_key=ANTHROPIC_API_KEY)

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR','ko','en-US','en']});
window.chrome = {runtime: {}};
"""

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}

def save_config(config: dict):
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

def is_configured(config: dict) -> bool:
    return bool(config.get("coupang_id") and config.get("coupang_pw"))

# ---------------------------------------------------------------------------
# 브라우저 / 로그인
# ---------------------------------------------------------------------------
def _make_context(playwright, storage_state=None):
    browser = playwright.chromium.launch(
        headless=False,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx_kwargs = dict(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        locale="ko-KR",
    )
    if storage_state:
        ctx_kwargs["storage_state"] = storage_state
    context = browser.new_context(**ctx_kwargs)
    context.add_init_script(STEALTH_SCRIPT)
    return browser, context


def login(playwright):
    config = load_config()
    if not is_configured(config):
        raise RuntimeError("쿠팡이츠 로그인 정보(아이디/비밀번호)가 설정되지 않았습니다. '설정' 탭에서 입력해주세요.")

    # 항상 새로 로그인 (쿠팡이츠는 브라우저 닫으면 세션 즉시 만료)
    CE_STORAGE_FILE.unlink(missing_ok=True)

    storage = None
    browser, context = _make_context(playwright, storage_state=storage)
    page = context.new_page()
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(LOGIN_URL)

    # 로그인 폼 입력
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PWTimeout:
        pass
    page.wait_for_timeout(1000)

    try:
        page.fill("#loginId", config["coupang_id"])
        page.fill("#password", config["coupang_pw"])
        page.click("button[type='submit']")
    except Exception as e:
        print(f"[WARN] 로그인 폼 입력 실패: {e}")

    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=120_000)
        print(f"[INFO] 쿠팡이츠 로그인 완료. ({page.url})")
    except PWTimeout:
        print(f"[WARN] 로그인 완료 감지 실패. 현재 URL: {page.url}")

    page.wait_for_timeout(2000)
    return browser, context, page


def _check_auth_error(page, playwright):
    """페이지 이동 후 권한 에러 감지 → 세션 삭제 + 재로그인 + 재이동."""
    try:
        page.wait_for_timeout(1000)
        body = page.inner_text("body")
        if "권한" in body or "접근" in body or "만료" in body:
            print("[INFO] 권한 에러 감지, 세션 삭제 후 재로그인합니다.")
            CE_STORAGE_FILE.unlink(missing_ok=True)
            url = page.url
            page.context.browser.close()
            browser, context, new_page = login(playwright)
            new_page.goto(url)
            new_page.wait_for_timeout(1500)
            return browser, context, new_page, True
    except Exception:
        pass
    return None, None, page, False


def dismiss_modal(page):
    """공지사항 팝업이 클릭을 가로막지 않도록 pointerEvents 비활성화."""
    page.evaluate(
        "document.querySelectorAll('.dialog-modal-wrapper').forEach("
        "el => { el.style.display='none'; el.style.pointerEvents='none'; })"
    )
    page.wait_for_timeout(200)


def set_date_filter(page, period: str):
    """날짜 필터를 변경하고 조회 버튼 클릭. period: '오늘' | '최근 1주일' | '1개월' 등"""
    if period == "오늘":
        return  # 기본값
    try:
        date_btn = page.locator("span:has-text('오늘'), button:has-text('오늘')").first
        date_btn.click(timeout=5000)
        page.wait_for_timeout(800)
        opt = page.locator(f"label:has-text('{period}'), span:has-text('{period}')").first
        opt.click(timeout=5000)
        page.wait_for_timeout(500)
    except Exception as e:
        print(f"[WARN] 날짜 필터 변경 실패: {e}")
    try:
        page.locator("button:has-text('조회')").click(timeout=5000)
        _wait_for_table(page, timeout=5000)
        page.wait_for_timeout(600)
    except Exception as e:
        print(f"[WARN] 조회 클릭 실패: {e}")


# ---------------------------------------------------------------------------
# 리뷰 스크래핑
# ---------------------------------------------------------------------------
_SKIP_PATTERNS = [
    re.compile(r"^주문메뉴$"),
    re.compile(r"^주문번호$"),
    re.compile(r"^수령방식$"),
    re.compile(r"^배달$"),
    re.compile(r"^포장$"),
    re.compile(r"^매장식사$"),
    re.compile(r"^\d+회 주문$"),
    re.compile(r"^.+\d+회 주문$"),  # "조*리3회 주문" 닉네임+횟수 합쳐진 줄
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^[A-Za-z0-9]{4,}[ㆍ・·]"),  # "18AEB8ㆍ2026-06-18(주문일)" 주문번호+날짜 줄
    re.compile(r"사장님 댓글 등록하기"),
    re.compile(r"사장님 댓글 수정하기"),
    re.compile(r"^사장님$"),
    re.compile(r"^취소$"),
    re.compile(r"^등록$"),
    re.compile(r"^수정$"),
    re.compile(r"^삭제$"),
    re.compile(r"^\* "),
]


def _parse_rows(page) -> list[dict]:
    rows = page.locator("table tbody tr")
    results = []
    n = rows.count()
    i = 0
    while i < n:
        row = rows.nth(i)
        text = row.inner_text()

        # 답글(사장님) 행 건너뜀: <b> 태그 없음
        bolds = row.locator("b")
        if bolds.count() == 0:
            i += 1
            continue

        has_replied = "사장님 댓글 등록하기" not in text
        reviewer = bolds.first.inner_text().strip()  # 닉네임 (마스킹됨)

        order_count = 0
        m = re.search(r"(\d+)회 주문", text)
        if m:
            order_count = int(m.group(1))

        date_str = ""
        m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if m:
            date_str = m.group(1)

        stars = row.locator("svg").count() // 2  # responsive 중복 제거

        order_no = ""
        m = re.search(r"주문번호\s*\n?([A-Z0-9]+)", text)
        if m:
            order_no = m.group(1)

        # 리뷰 텍스트: 불필요한 줄 제거
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        review_lines = []
        skip_bolds = set(bolds.all_inner_texts())
        for ln in lines:
            if ln in skip_bolds:
                continue
            if any(p.match(ln) for p in _SKIP_PATTERNS):
                continue
            if re.match(r"[A-Za-z0-9]{4,}[ㆍ・·]", ln):  # 주문번호+날짜 줄
                continue
            review_lines.append(ln)
        review_text = "\n".join(review_lines)

        results.append({
            "row_index": i,
            "reviewer": reviewer,
            "order_count": order_count,
            "stars": stars,
            "date": date_str,
            "order_no": order_no,
            "review_text": review_text,
            "has_replied": has_replied,
        })
        i += 1

    return results


def _wait_for_table(page, timeout: int = 5000):
    """리뷰 테이블 행이 나타날 때까지 대기 (networkidle보다 빠름)."""
    try:
        page.wait_for_selector("table tbody tr", timeout=timeout)
    except PWTimeout:
        pass


# UI 표시 기간 → (사이트 드롭다운 옵션, 클라이언트 필터 일수)
_CE_PERIOD_MAP: dict[str, tuple[str, int | None]] = {
    "1일": ("오늘",       1),
    "3일": ("최근 1주일", 3),
    "7일": ("최근 1주일", 7),
    "1달": ("1개월",      30),
    # 하위 호환
    "오늘":      ("오늘",       1),
    "최근 1주일": ("최근 1주일", 7),
    "1개월":     ("1개월",      30),
}


def fetch_reviews(page, period: str = "1일") -> list[dict]:
    site_period, filter_days = _CE_PERIOD_MAP.get(period, ("오늘", 1))

    _wait_for_table(page, timeout=8000)
    page.wait_for_timeout(600)
    dismiss_modal(page)
    set_date_filter(page, site_period)

    all_reviews: list[dict] = []
    page_num = 1
    while True:
        dismiss_modal(page)
        rows = _parse_rows(page)
        for r in rows:
            r["page_num"] = page_num
        all_reviews.extend(rows)

        next_btn = page.locator(f"button:has-text('{page_num + 1}')")
        if next_btn.count() == 0:
            break
        next_btn.first.click()
        _wait_for_table(page, timeout=5000)
        page.wait_for_timeout(400)
        page_num += 1
        if page_num > 20:
            break

    if filter_days is not None:
        cutoff = (date.today() - timedelta(days=filter_days - 1)).isoformat()
        all_reviews = [r for r in all_reviews if r.get("date", "9999") >= cutoff]

    return all_reviews


def generate_draft_replies(reviews: list[dict], config: dict) -> None:
    """미답변 리뷰 목록에 draft_reply를 병렬로 생성한다 (in-place)."""
    from concurrent.futures import ThreadPoolExecutor

    def _gen(rv):
        try:
            rv["draft_reply"] = generate_reply(rv, config)
        except Exception as e:
            rv["draft_reply"] = ""
            rv["error"] = str(e)

    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(_gen, reviews))


# ---------------------------------------------------------------------------
# 답글 생성
# ---------------------------------------------------------------------------
def generate_reply(review: dict, config: dict) -> str:
    store_name = config.get("store_name", "우리 가게")
    tone = config.get("store_tone", "친근하고 감사한 말투")

    prompt = f"""당신은 '{store_name}' 음식점의 사장님입니다.
아래 쿠팡이츠 리뷰에 대한 답글을 작성해주세요.

[규칙]
- 말투: {tone}
- 쿠팡이츠 제한: 300자 이내
- 고객 이름은 닉네임이 마스킹되어 있으므로 이름 없이 작성
- 리뷰 내용에 구체적으로 언급된 부분 1~2가지를 반드시 반영
- 다음에도 방문을 유도하는 내용 포함
- 답글 본문만 출력, 따옴표나 설명 없이

[리뷰 정보]
별점: {review['stars']}점
주문 횟수: {review['order_count']}회
리뷰 내용: {review['review_text'] or '(내용 없음)'}"""

    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# ---------------------------------------------------------------------------
# 답글 등록
# ---------------------------------------------------------------------------
def prepare_page(page, period: str = "1일"):
    """날짜 필터만 적용하고 페이지 순회는 하지 않는 가벼운 준비 함수."""
    site_period, _ = _CE_PERIOD_MAP.get(period, ("오늘", 1))
    _wait_for_table(page, timeout=8000)
    page.wait_for_timeout(600)
    dismiss_modal(page)
    set_date_filter(page, site_period)


def post_reply(page, row_index: int, reply_text: str, page_num: int = 1) -> bool:
    """row_index번째 리뷰에 답글 등록. 성공 시 True."""
    try:
        # 목표 페이지로 이동 (1페이지는 기본값이므로 건너뜀)
        dismiss_modal(page)
        if page_num > 1:
            nav_btn = page.locator(f"button:has-text('{page_num}')")
            if nav_btn.count() > 0:
                nav_btn.first.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except PWTimeout:
                    pass
                page.wait_for_timeout(500)

        dismiss_modal(page)

        # row_index번째 행에서 답글 버튼 찾기
        rows = page.locator("table tbody tr")
        target_row = rows.nth(row_index)
        btn = target_row.locator("button:has-text('사장님 댓글 등록하기')")
        if btn.count() == 0:
            btn = page.locator("button:has-text('사장님 댓글 등록하기')").first
        btn.click(timeout=5_000)
        page.wait_for_timeout(1000)

        # 입력 폼 대기
        ta = page.locator("textarea")
        ta.wait_for(timeout=8_000)
        ta.click()
        ta.fill(reply_text[:300])
        page.wait_for_timeout(300)

        # 등록 버튼 클릭 — exact="등록"으로 "등록하기" 버튼과 구분
        submit_btn = page.get_by_role("button", name="등록", exact=True)
        if submit_btn.count() == 0:
            submit_btn = page.locator("button").filter(has_text=re.compile(r"^등록$"))
        submit_btn.first.click(timeout=5_000)
        page.wait_for_timeout(1500)

        # 성공 확인
        try:
            page.wait_for_selector("button:has-text('사장님 댓글 수정하기')", timeout=3_000)
        except PWTimeout:
            pass
        return True

    except Exception as e:
        print(f"[WARN] 답글 등록 실패: {e}")
        return False


# ---------------------------------------------------------------------------
# 히스토리
# ---------------------------------------------------------------------------
def load_history() -> dict:
    if CE_HISTORY_FILE.exists():
        return json.loads(CE_HISTORY_FILE.read_text(encoding="utf-8"))
    return {}


def save_history(history: dict):
    CE_HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def build_full_history(page, progress_callback=None) -> dict:
    """전체 리뷰(답변 포함)를 긁어서 리뷰어 히스토리를 구축한다.
    기존 히스토리를 덮어쓴다."""
    _wait_for_table(page, timeout=8000)
    page.wait_for_timeout(600)
    dismiss_modal(page)
    set_date_filter(page, "1개월")

    all_reviews: list[dict] = []
    page_num = 1
    while True:
        dismiss_modal(page)
        rows = _parse_rows(page)
        for r in rows:
            all_reviews.append(r)
        if progress_callback:
            progress_callback(len(all_reviews))

        next_btn = page.locator(f"button:has-text('{page_num + 1}')")
        if next_btn.count() == 0:
            break
        next_btn.first.click()
        _wait_for_table(page, timeout=5000)
        page.wait_for_timeout(400)
        page_num += 1
        if page_num > 50:
            break

    history: dict = {}
    for rv in all_reviews:
        reviewer = rv["reviewer"]
        entry = history.get(reviewer, {"reviews": []})
        entry["reviews"].append({
            "date": rv.get("date", ""),
            "order_count": rv.get("order_count", 0),
            "stars": rv.get("stars", 0),
            "review_text": rv.get("review_text", ""),
            "has_replied": rv.get("has_replied", False),
        })
        history[reviewer] = entry

    save_history(history)
    print(f"[INFO] 쿠팡이츠 히스토리 구축 완료: {len(all_reviews)}건 리뷰, {len(history)}명 리뷰어")
    return history


def load_negative_reviews() -> list[dict]:
    if CE_NEGATIVE_FILE.exists():
        return json.loads(CE_NEGATIVE_FILE.read_text(encoding="utf-8"))
    return []


def save_negative_reviews(reviews: list[dict]):
    CE_NEGATIVE_FILE.write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_negative_reviews(reviews: list[dict], platform: str = "coupangeats"):
    """3점 이하 부정 리뷰를 필터링하고 AI 요약을 생성해 저장한다."""
    from concurrent.futures import ThreadPoolExecutor

    negatives = [r for r in reviews if r.get("stars", r.get("rating", 5)) <= 3]
    if not negatives:
        return

    existing = load_negative_reviews()
    existing_keys = {f"{r.get('reviewer')}|{r.get('date')}|{r.get('platform')}" for r in existing}

    new_items = []
    for rv in negatives:
        key = f"{rv.get('reviewer', '')}|{rv.get('date', '')}|{platform}"
        if key in existing_keys:
            continue
        new_items.append({
            "reviewer": rv.get("reviewer", ""),
            "date": rv.get("date", ""),
            "rating": rv.get("stars", rv.get("rating", 0)),
            "text": rv.get("review_text", rv.get("text", "")),
            "menu": "",
            "platform": platform,
            "summary": "",
        })

    if not new_items:
        return

    def _summarize(item):
        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=100,
                messages=[{"role": "user", "content": (
                    f"아래 배달앱 부정 리뷰(★{item['rating']}점)의 불만 이유를 1~2문장으로 요약해주세요.\n"
                    f"리뷰: {item['text'][:300]}"
                )}],
            )
            item["summary"] = resp.content[0].text.strip()
        except Exception:
            item["summary"] = "(요약 실패)"

    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(_summarize, new_items))

    existing.extend(new_items)
    save_negative_reviews(existing)
    print(f"[INFO] 쿠팡이츠 부정 리뷰 {len(new_items)}건 저장 (총 {len(existing)}건)")

    try:
        try:
            import auth_client as _auth
        except ImportError:
            import auth as _auth
        if hasattr(_auth, "log_negative_review"):
            import streamlit as st
            username = st.session_state.get("username", "")
            for item in new_items:
                _auth.log_negative_review(
                    username=username, platform="coupangeats",
                    reviewer=item["reviewer"], rating=item["rating"],
                    review_text=item["text"], summary=item["summary"],
                    review_date=item["date"],
                )
    except Exception:
        pass


def update_history(review: dict, reply_text: str):
    history = load_history()
    key = review["reviewer"]
    entry = history.get(key, {"reviews": []})
    entry["reviews"].append({
        "date": review["date"],
        "order_count": review["order_count"],
        "stars": review["stars"],
        "review_text": review["review_text"],
        "reply_text": reply_text,
        "replied_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    history[key] = entry
    save_history(history)
