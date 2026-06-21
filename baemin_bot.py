"""
배민 사장님 사이트 리뷰 자동 답글 봇

흐름:
1) Playwright로 ceo.baemin.com에서 로그인 (세션은 storage_state.json에 저장하여 재사용)
2) self.baemin.com의 리뷰 관리 페이지(미답변 탭)에서 최대 MAX_REVIEWS개까지 처리
3) 각 리뷰에 대해 Claude API로 답글 생성
4) 생성한 답글을 페이지에서 자동으로 등록
5) 리뷰어별 히스토리를 reviewer_history.json에 저장

주의:
- 배민은 봇 탐지(이상행동 감지)가 있어 반드시 headless=False(화면이 보이는 브라우저)로
  실행해야 합니다. headless=True로 전환하면 "비정상 동작이 감지되어 잠시 이용이
  제한돼요" 페이지가 뜨면서 차단됩니다.
- self.baemin.com은 React 기반으로 화면 구조/클래스명이 자주 바뀝니다. 동작이 안 되면
  "SELECTORS" 영역과 extract_review/post_reply 함수를 실제 화면에 맞게 수정하세요.
- 로그인 시 2단계 인증(OTP/SMS) 등이 뜨면, headless=False 화면에서 직접 인증을 완료하면
  세션이 storage_state.json에 저장되어 다음부터는 자동 로그인됩니다.
"""

import json
import os
import re
import time
from datetime import datetime, date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

# 가맹점 공통 설정 (대표가 배포 시 .env에 미리 채워서 제공)
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

MAX_REVIEWS = 5
HEADLESS = False  # 첫 실행은 False로 두고 로그인/동작을 직접 확인하세요.

HISTORY_FILE = BASE_DIR / "reviewer_history.json"
STORAGE_STATE_FILE = BASE_DIR / "storage_state.json"
CONFIG_FILE = BASE_DIR / "config.json"

DEFAULT_STORE_TONE = "20대 여자 알바생이 빠르게 타이핑한 것처럼 짧고 발랄한 존댓말, 이모지/이모티콘은 사용하지 않음"


# ---------------------------------------------------------------------------
# 가게별 설정 (이름/말투/배민 로그인/SHOP_ID) - config.json에 저장
# 가맹점마다 자신의 PC에서 "설정" 화면을 통해 직접 입력/관리
# ---------------------------------------------------------------------------
def load_config() -> dict:
    config = {
        "store_name": "우리가게",
        "store_tone": DEFAULT_STORE_TONE,
        "baemin_id": "",
        "baemin_pw": "",
        "shop_id": "",
    }

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config.update(json.load(f))
    else:
        save_config(config)

    return config


def save_config(config: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def is_configured(config: dict | None = None) -> bool:
    """배민 로그인/가게 설정이 모두 입력되었는지 확인."""
    config = config or load_config()
    return bool(config.get("baemin_id") and config.get("baemin_pw") and config.get("shop_id"))


LOGIN_URL = "https://ceo.baemin.com/login"


def extract_shop_id(text: str) -> str:
    """가게 홈페이지 URL 또는 SHOP_ID 입력값에서 숫자로 된 SHOP_ID를 추출."""
    text = text.strip()
    match = re.search(r"/shops/(\d+)", text)
    if match:
        return match.group(1)
    if text.isdigit():
        return text
    return ""


def review_url(config: dict | None = None) -> str:
    config = config or load_config()
    return f"https://self.baemin.com/shops/{config['shop_id']}/reviews?tab=noComment"

# ---------------------------------------------------------------------------
# 셀렉터 (실제 화면 구조에 맞게 조정 필요)
# ---------------------------------------------------------------------------
SELECTORS = {
    # 로그인 페이지
    "login_id_input": "input[name='id']",
    "login_pw_input": "input[name='password']",
    "login_submit": "button[type='submit']",

    # 리뷰 목록 (self.baemin.com/shops/{SHOP_ID}/reviews?tab=noComment)
    "review_card": '[class*="ReviewContent-module"]',
    "menu_box": '[class*="ReviewMenus-module"]',
    "gold_star": 'svg path[fill="#FFC600"]',

    # 답글 작성
    "reply_open_button": "사장님 댓글 등록하기",
    "reply_textarea": "textarea",
}

# 리뷰 카드 텍스트에서 제거할 보일러플레이트 패턴
_BOILERPLATE_PATTERNS = [
    re.compile(r"^\d{4}년 \d{1,2}월 \d{1,2}일$"),
    re.compile(r"^리뷰번호 \d+$"),
    re.compile(r"^\d+회 주문 고객$"),
    re.compile(r"^\(.*누적 주문\)$"),
    re.compile(r"^파트너님에게만 보이는 리뷰입니다\.$"),
    re.compile(r"^(배달|포장)리뷰$"),
    re.compile(r"^좋아요\d*$"),
    re.compile(r"^사장님 댓글 등록하기$"),
]


# ---------------------------------------------------------------------------
# 히스토리 저장소
# ---------------------------------------------------------------------------
def load_history() -> dict:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(history: dict) -> None:
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def make_history_record(review: dict, reply_text: str) -> dict:
    return {
        "review_no": review["review_no"],
        "date": review["date"],
        "rating": review["rating"],
        "menu": review["menu"],
        "review_text": review["text"],
        "reply": reply_text,
        "replied_at": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# 로그인
# ---------------------------------------------------------------------------
def login(playwright):
    config = load_config()
    if not is_configured(config):
        raise RuntimeError("배민 로그인 정보(아이디/비밀번호/SHOP_ID)가 설정되지 않았습니다. '설정' 탭에서 입력해주세요.")

    browser = playwright.chromium.launch(headless=HEADLESS)

    if STORAGE_STATE_FILE.exists():
        context = browser.new_context(storage_state=str(STORAGE_STATE_FILE))
    else:
        context = browser.new_context()

    page = context.new_page()
    page.goto(LOGIN_URL)

    # 기존 세션으로 이미 로그인되어 있는지 확인
    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=5_000)
        print(f"[INFO] 기존 세션으로 로그인되었습니다. ({page.url})")
        return browser, context, page
    except PWTimeoutError:
        pass

    # 로그인 폼 입력
    try:
        page.fill(SELECTORS["login_id_input"], config["baemin_id"])
        page.fill(SELECTORS["login_pw_input"], config["baemin_pw"])
        page.click(SELECTORS["login_submit"])
    except PWTimeoutError:
        print("[WARN] 로그인 폼을 찾지 못했습니다. SELECTORS 값을 확인하세요.")

    # 로그인 후 /login 을 벗어나는지 확인 (OTP 등 추가 인증 화면 대비 넉넉한 타임아웃)
    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=120_000)
        print(f"[INFO] 로그인 완료. ({page.url})")
    except PWTimeoutError:
        print(f"[WARN] 로그인 완료 여부를 확인하지 못했습니다. 현재 URL: {page.url}")
        print("[WARN] OTP 등 추가 인증이 필요한 화면일 수 있습니다. 셀렉터/플로우 확인이 필요합니다.")

    context.storage_state(path=str(STORAGE_STATE_FILE))
    print("[INFO] 로그인 세션을 storage_state.json에 저장했습니다.")
    return browser, context, page


# ---------------------------------------------------------------------------
# Claude로 답글 생성
# ---------------------------------------------------------------------------
client = Anthropic(api_key=ANTHROPIC_API_KEY)

# 이모지/이모티콘 등 특수문자 제거용 패턴
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # 이모지, 기호, 픽토그램 전반
    "\U00002600-\U000027BF"  # 기타 기호 및 딩뱃
    "\U0001F1E6-\U0001F1FF"  # 국기
    "\U00002190-\U000021FF"  # 화살표
    "\U00002300-\U000023FF"  # 기술 기호
    "\U00002B00-\U00002BFF"  # 화살표/기호 추가
    "\U0000FE00-\U0000FE0F"  # variation selector
    "\U0001F900-\U0001F9FF"  # 추가 이모지
    "\U00002700-\U000027BF"  # 딩뱃
    "]+",
    flags=re.UNICODE,
)

# 허용 문자: 한글/영문/숫자/공백 및 기본 문장부호
_ALLOWED_CHAR_PATTERN = re.compile(r"[^가-힣ㄱ-ㅎㅏ-ㅣ\w\s.,!?~()\-'\"%]")


def sanitize_text(text: str) -> str:
    """Claude API로 보내기 전, 텍스트에서 이모지/이모티콘 등 특수문자를 제거한다."""
    if not text:
        return text
    text = _EMOJI_PATTERN.sub("", text)
    text = _ALLOWED_CHAR_PATTERN.sub("", text)
    return text.strip()


def generate_reply(review: dict, history_entry: dict | None) -> str:
    config = load_config()
    store_name = config["store_name"]
    store_tone = config["store_tone"]

    review_menu = sanitize_text(review["menu"])
    review_text_raw = sanitize_text(review["text"])

    past_reviews = (history_entry or {}).get("reviews", [])
    history_note = ""
    if past_reviews:
        last = past_reviews[-1]
        history_note = (
            f"이 리뷰어는 이전에 {len(past_reviews)}번 주문 후 리뷰를 남긴 단골 고객입니다. "
            f"가장 최근 리뷰 별점은 {last.get('rating', '?')}점이었습니다."
        )
        last_menu = sanitize_text((last.get("menu") or "").strip())
        if last_menu and last_menu != review_menu.strip():
            history_note += (
                f" 지난번에는 '{last_menu}'를 주문했었고, 이번엔 메뉴가 달라졌습니다."
            )

    menu_line = f"- 주문 메뉴: {review_menu}\n" if review_menu else ""
    review_text = review_text_raw or "(작성된 리뷰 내용 없음, 별점만 등록됨)"

    prompt = f"""당신은 '{store_name}' 사장님을 대신해 배달앱 리뷰에 답글을 작성하는 어시스턴트입니다.

[말투/톤 — 반드시 아래 지침을 최우선으로 따를 것]
{store_tone}

[리뷰 정보]
- 별점: {review['rating']}점
{menu_line}- 리뷰 내용: {review_text}
{history_note}

[기본 규칙]
- 리뷰 내용에 언급된 메뉴나 구체적인 부분을 자연스럽게 반영
- 단골 고객이고 이전과 다른 메뉴를 주문했다면 자연스럽게 한 번 언급 (정보 없으면 생략)
- 존재하지 않는 이벤트·쿠폰·할인 언급 금지
- 답글 본문만 출력, 따옴표나 설명 없이
"""

    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# ---------------------------------------------------------------------------
# 리뷰 스크래핑 & 답글 등록
# ---------------------------------------------------------------------------
def extract_review(card) -> dict:
    full_text = card.inner_text().strip()
    lines = [ln.strip() for ln in full_text.split("\n")]
    lines = [ln for ln in lines if ln]

    # 카드 맨 앞에는 '알뜰배달/한집배달/가게배달' 같은 배송 방식 배지가 먼저 나오고
    # 그 다음 줄이 실제 닉네임이므로, 배지 텍스트를 건너뛰고 닉네임을 찾는다.
    badge_texts = set(card.locator('[class*="Badge"]').all_inner_texts())
    name_idx = 0
    while name_idx < len(lines) and lines[name_idx] in badge_texts:
        name_idx += 1
    reviewer = lines[name_idx] if name_idx < len(lines) else (lines[0] if lines else "익명")

    date_match = re.search(r"\d{4}년 \d{1,2}월 \d{1,2}일", full_text)
    date = date_match.group() if date_match else ""

    review_no_match = re.search(r"리뷰번호 (\d+)", full_text)
    review_no = review_no_match.group(1) if review_no_match else ""

    rating = card.locator(SELECTORS["gold_star"]).count()

    menu_box = card.locator(SELECTORS["menu_box"])
    menu = menu_box.first.inner_text().strip().replace("\n", ", ") if menu_box.count() else ""
    menu_lines = set(menu.split(", ")) if menu else set()

    text_lines = []
    for ln in lines[name_idx + 1:]:
        if ln in menu_lines:
            continue
        if any(p.match(ln) for p in _BOILERPLATE_PATTERNS):
            continue
        text_lines.append(ln)

    return {
        "reviewer": reviewer,
        "rating": rating,
        "menu": menu,
        "text": "\n".join(text_lines),
        "date": date,
        "review_no": review_no,
    }


def _dismiss_baemin_overlays(page):
    """배민 페이지의 팝업/공지/백드롭을 제거해 클릭 차단을 해소한다."""
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    page.evaluate("""
        // Dialog 백드롭 숨김
        document.querySelectorAll('[data-testid="backdrop"]').forEach(el => {
            el.style.pointerEvents = 'none';
            el.style.display = 'none';
        });
        // "미사용 가게보다 노출수가" 같은 고정 공지 팝업 숨김
        document.querySelectorAll('p, span, div').forEach(el => {
            if (el.childElementCount === 0 &&
                el.textContent.trim().startsWith('미사용 가게보다')) {
                let p = el;
                for (let i = 0; i < 10; i++) {
                    p = p.parentElement;
                    if (!p) break;
                    const s = window.getComputedStyle(p);
                    if (s.position === 'fixed' || s.position === 'absolute') {
                        p.style.pointerEvents = 'none';
                        p.style.display = 'none';
                        break;
                    }
                }
            }
        });
    """)
    page.wait_for_timeout(200)


def post_reply(page, card, reply_text: str) -> bool:
    """리뷰 카드 내 답글 작성 버튼을 열고 답글을 등록한다."""
    open_btn = card.get_by_text(SELECTORS["reply_open_button"])
    if open_btn.count() == 0:
        print("  [WARN] 답글 작성 버튼을 찾지 못했습니다.")
        return False

    _dismiss_baemin_overlays(page)
    open_btn.first.click(force=True)
    page.wait_for_timeout(300)

    textarea = card.locator(SELECTORS["reply_textarea"])
    if textarea.count() == 0:
        print("  [WARN] 답글 입력창을 찾지 못했습니다.")
        return False

    textarea.first.fill(reply_text)
    page.wait_for_timeout(150)

    submit_btn = card.get_by_role("button", name="등록", exact=True)
    if submit_btn.count() == 0:
        print("  [WARN] 답글 등록 버튼을 찾지 못했습니다.")
        return False

    submit_btn.first.click(force=True)
    page.wait_for_timeout(800)
    return True


def _scroll_load_all(page):
    """무한스크롤로 모든 리뷰 카드를 로드 — 마지막 카드 위치에서 스크롤."""
    prev = 0
    stale = 0
    for _ in range(200):
        cards = page.locator(SELECTORS["review_card"])
        count = cards.count()

        if count > 0:
            last = cards.nth(count - 1)
            # 마지막 카드를 뷰포트로 스크롤
            last.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            # 마지막 카드 위에 마우스를 올리고 휠 스크롤
            try:
                box = last.bounding_box()
                if box:
                    page.mouse.move(box["x"] + box["width"] / 2,
                                    box["y"] + box["height"] / 2)
                    page.mouse.wheel(0, 3000)
            except Exception:
                pass

        page.keyboard.press("End")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)

        cur = page.locator(SELECTORS["review_card"]).count()
        if cur == prev:
            stale += 1
            if stale >= 5:
                break
        else:
            stale = 0
        prev = cur
    print(f"[INFO] 배민 리뷰 {prev}건 로드 완료")


def _parse_baemin_date(date_str: str) -> date | None:
    """'2026년 6월 18일' → date(2026, 6, 18)"""
    m = re.match(r"(\d{4})년 (\d{1,2})월 (\d{1,2})일", date_str)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def fetch_unanswered_reviews(page, history: dict, days: int | None = None) -> list[dict]:
    """미답변 리뷰를 전부 스크래핑해서 반환한다 (가상 리스트 대응).
    days=N 이면 최근 N일 이내 리뷰만 반환 (None=전체).
    답글 초안 없음 — generate_draft_replies로 별도 생성."""
    page.goto(review_url())
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    _dismiss_baemin_overlays(page)

    # 가상 리스트: 스크롤하면서 보이는 카드를 계속 수집
    seen_keys: set[str] = set()
    results: list[dict] = []
    stale = 0

    for _ in range(300):
        cards = page.locator(SELECTORS["review_card"])
        count = cards.count()
        new_found = False

        for i in range(count):
            try:
                rv = extract_review(cards.nth(i))
            except Exception:
                continue
            key = f"{rv['reviewer']}|{rv['date']}|{rv.get('review_no', '')}|{rv['text'][:40]}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rv["_history_entry"] = history.get(rv["reviewer"], {"reviews": []})
            results.append(rv)
            new_found = True

        if not new_found:
            stale += 1
            if stale >= 5:
                break
        else:
            stale = 0

        # 카드 1개 분량씩 천천히 스크롤 (가상 리스트가 건너뛰지 않도록)
        if count > 0:
            last = cards.nth(count - 1)
            last.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            try:
                box = last.bounding_box()
                if box:
                    page.mouse.move(box["x"] + box["width"] / 2,
                                    box["y"] + box["height"] / 2)
                    page.mouse.wheel(0, 400)
            except Exception:
                pass

        page.wait_for_timeout(1000)

    print(f"[INFO] 배민 리뷰 {len(results)}건 수집 완료")

    if days is not None:
        cutoff = date.today() - timedelta(days=days - 1)
        results = [
            r for r in results
            if (d := _parse_baemin_date(r.get("date", ""))) is None or d >= cutoff
        ]

    return results


def generate_draft_replies(reviews: list[dict]) -> None:
    """리뷰 목록에 draft_reply를 병렬로 생성한다 (in-place)."""
    from concurrent.futures import ThreadPoolExecutor

    def _gen(rv):
        entry = rv.pop("_history_entry", {"reviews": []})
        try:
            rv["draft_reply"] = generate_reply(rv, entry)
        except Exception as e:
            rv["draft_reply"] = ""
            rv["error"] = str(e)

    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(_gen, reviews))


def submit_reply_by_review_no(page, review_no: str, reply_text: str,
                              reviewer: str = "", review_date: str = "") -> bool:
    """가상 리스트를 스크롤하면서 카드를 찾아 답글 등록.
    review_no 우선, 없으면 reviewer+date로 매칭."""
    page.goto(review_url())
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
    _dismiss_baemin_overlays(page)

    seen: set[str] = set()
    stale = 0
    for _ in range(300):
        cards = page.locator(SELECTORS["review_card"])
        count = cards.count()
        new_found = False

        for i in range(count):
            card = cards.nth(i)
            try:
                text = card.inner_text()
            except Exception:
                continue

            # review_no로 매칭
            if review_no:
                m = re.search(r"리뷰번호 (\d+)", text)
                if m and m.group(1) == review_no:
                    return post_reply(page, card, reply_text)

            # reviewer 이름 + 날짜로 매칭 (review_no 없을 때)
            if not review_no and reviewer:
                if reviewer in text and (not review_date or review_date in text):
                    open_btn = card.get_by_text(SELECTORS["reply_open_button"])
                    if open_btn.count() > 0:
                        return post_reply(page, card, reply_text)

            card_id = text[:80]
            if card_id not in seen:
                seen.add(card_id)
                new_found = True

        if not new_found:
            stale += 1
            if stale >= 5:
                break
        else:
            stale = 0

        if count > 0:
            last = cards.nth(count - 1)
            last.scroll_into_view_if_needed()
            page.wait_for_timeout(150)
            try:
                box = last.bounding_box()
                if box:
                    page.mouse.move(box["x"] + box["width"] / 2,
                                    box["y"] + box["height"] / 2)
                    page.mouse.wheel(0, 400)
            except Exception:
                pass
        page.wait_for_timeout(500)

    print(f"[WARN] 리뷰를 찾지 못했습니다: review_no={review_no}, reviewer={reviewer}")
    return False


def submit_all_replies(page, reviews_with_replies: list[dict]) -> tuple[int, int]:
    """리뷰 목록에서 각 review_no를 찾아 답글을 등록한다. (ok, fail) 건수 반환."""
    ok_count = 0
    fail_count = 0
    for item in reviews_with_replies:
        ok = submit_reply_by_review_no(page, item["review_no"], item["reply_text"])
        if ok:
            ok_count += 1
        else:
            fail_count += 1
    return ok_count, fail_count


def process_reviews(page, history: dict, max_count: int = MAX_REVIEWS) -> int:
    processed = 0

    while processed < max_count:
        page.goto(review_url())
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        cards = page.locator(SELECTORS["review_card"])
        if cards.count() == 0:
            print("[INFO] 더 이상 미답변 리뷰가 없습니다.")
            break

        card = cards.first
        review = extract_review(card)
        reviewer_key = review["reviewer"]

        entry = history.get(reviewer_key, {"reviews": []})

        try:
            reply_text = generate_reply(review, entry)
        except Exception as e:
            print(f"  [ERROR] 답글 생성 실패: {e}")
            break

        print(f"[{processed + 1}] {reviewer_key} (★{review['rating']}) -> {reply_text[:40]}...")

        ok = post_reply(page, card, reply_text)
        if not ok:
            print("  [WARN] 답글 등록에 실패하여 다음 리뷰로 넘어갑니다.")
            break

        entry["reviews"].append({
            "review_no": review["review_no"],
            "date": review["date"],
            "rating": review["rating"],
            "menu": review["menu"],
            "review_text": review["text"],
            "reply": reply_text,
            "replied_at": datetime.now().isoformat(timespec="seconds"),
        })
        history[reviewer_key] = entry
        save_history(history)

        processed += 1
        time.sleep(2)

    return processed


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main():
    history = load_history()

    with sync_playwright() as playwright:
        browser, context, page = login(playwright)
        try:
            count = process_reviews(page, history, MAX_REVIEWS)
            print(f"[DONE] 총 {count}개 리뷰에 답글을 등록했습니다.")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
