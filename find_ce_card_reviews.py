"""
쿠팡이츠 주간 카드이벤트 리뷰 자동 선정 스크립트.

최근 1주일 리뷰 중 번호카드 인증 사진이 있는 리뷰를 Claude Vision으로 찾아
재주문수_높은_리뷰 / 정성스럽게_쓴_리뷰 2건을 자동 선정한다.
"""
import sys
import re
import json
import base64
from pathlib import Path
from datetime import datetime, timedelta
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import coupangeats_bot as bot

BASE_DIR = bot.BASE_DIR
IMG_DIR = BASE_DIR / "ce_review_images"
IMG_DIR.mkdir(exist_ok=True)
PICKS_FILE = BASE_DIR / "ce_card_review_picks.json"

client = bot.client
CLAUDE_MODEL = bot.CLAUDE_MODEL

EXCLUDE_RECENT_RUNS = 8
REVIEW_URL = bot.REVIEW_URL

STEALTH_SCRIPT = bot.STEALTH_SCRIPT

# ---------------------------------------------------------------------------
# 제외 대상 / 픽 저장
# ---------------------------------------------------------------------------
def load_excluded_reviewers() -> set:
    if not PICKS_FILE.exists():
        return set()
    data = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
    runs = data.get("runs", [])
    recent = runs[-EXCLUDE_RECENT_RUNS:]
    excluded = set()
    for run in recent:
        for pick in run.get("picks", []):
            excluded.add(pick["reviewer"])
    return excluded


def save_picks(date_str: str, picks: list):
    if PICKS_FILE.exists():
        data = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
    else:
        data = {"_comment": "쿠팡이츠 카드이벤트 리뷰 선정 기록", "runs": []}
    data["runs"].append({"date": date_str, "picks": picks})
    PICKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_unused_images():
    if not PICKS_FILE.exists():
        return
    data = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
    used = set()
    for run in data.get("runs", []):
        for pick in run.get("picks", []):
            for img in pick.get("images", []):
                used.add((BASE_DIR / img).resolve())
    for f in IMG_DIR.glob("*.jpg"):
        if f.resolve() not in used:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 카드 번호 인식 (Claude Vision)
# ---------------------------------------------------------------------------
def detect_card_no(local_images: list, review_text: str = "") -> str | None:
    content = []
    for img_path in local_images:
        data = base64.standard_b64encode(Path(img_path).read_bytes()).decode("utf-8")
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": data},
        })
    content.append({
        "type": "text",
        "text": (
            "위 사진(들)과 아래 리뷰 텍스트는 같은 리뷰에 속합니다. "
            "매장의 '번호카드 인증 이벤트'용으로 숫자가 적힌 카드(종이/플라스틱 카드)가 있는지 확인하세요.\n"
            "- 사진에 카드가 보이면 인정합니다 (음식 사진과 카드가 함께 찍힌 사진도 인정).\n"
            "- 사진에 카드가 없더라도 리뷰 텍스트에 카드 번호로 보이는 숫자가 단독으로 적힌 경우도 인정합니다.\n"
            "카드 번호를 찾으면 "
            '{"has_card": true, "card_no": "1234"} '
            '없으면 {"has_card": false, "card_no": null} 로만 답하세요.\n\n'
            f"리뷰 텍스트:\n{review_text or '(텍스트 없음)'}"
        ),
    })
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": content}],
        )
        text = resp.content[0].text.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data_parsed = json.loads(m.group()) if m else json.loads(text)
    except Exception as e:
        print(f"  [경고] 카드 인식 실패: {e}")
        return None
    if data_parsed.get("has_card") and data_parsed.get("card_no"):
        return str(data_parsed["card_no"])
    return None


# ---------------------------------------------------------------------------
# 정성 리뷰 선정 (Claude)
# ---------------------------------------------------------------------------
def pick_sincere_review(candidates: list) -> dict | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    items = "\n\n".join(
        f"[{i+1}] (주문 {c['order_count']}회)\n{c['review_text'] or '(텍스트 없음)'}"
        for i, c in enumerate(candidates)
    )
    prompt = (
        "다음은 음식점 리뷰 목록입니다. 가장 정성스럽게 작성된 리뷰 하나를 골라 번호만 답하세요.\n\n"
        + items
        + "\n\n가장 정성스러운 리뷰 번호:"
    )
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        num = int(re.search(r"\d+", resp.content[0].text).group()) - 1
        return candidates[num] if 0 <= num < len(candidates) else candidates[0]
    except Exception:
        return candidates[0]


# ---------------------------------------------------------------------------
# 이미지 다운로드
# ---------------------------------------------------------------------------
def download_image(url: str, dest: Path) -> bool:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            dest.write_bytes(r.read())
        return True
    except Exception as e:
        print(f"  [경고] 이미지 다운로드 실패 ({url[:60]}): {e}")
        return False


# ---------------------------------------------------------------------------
# 리뷰 스크래핑 (최근 1주일)
# ---------------------------------------------------------------------------
def set_date_filter_1week(page):
    """날짜 필터를 '최근 1주일'로 변경하고 조회 버튼 클릭."""
    try:
        # 날짜 드롭다운 열기
        date_btn = page.locator("span:has-text('오늘'), button:has-text('오늘')").first
        date_btn.click(timeout=5000)
        page.wait_for_timeout(800)

        # '최근 1주일' 라디오 클릭
        week_opt = page.locator("label:has-text('최근 1주일'), span:has-text('최근 1주일')").first
        week_opt.click(timeout=5000)
        page.wait_for_timeout(500)
    except Exception as e:
        print(f"  [경고] 날짜 필터 변경 실패: {e}")

    # 조회 버튼 클릭
    try:
        page.locator("button:has-text('조회')").click(timeout=5000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PWTimeout:
            pass
        page.wait_for_timeout(1500)
    except Exception as e:
        print(f"  [경고] 조회 클릭 실패: {e}")


def scrape_all_pages(page) -> list[dict]:
    """현재 필터 기준 모든 페이지의 리뷰를 수집한다."""
    all_results = []
    page_num = 1

    while True:
        print(f"  페이지 {page_num} 스크래핑...")
        bot.dismiss_modal(page)
        rows = page.locator("table tbody tr")
        n = rows.count()

        for i in range(n):
            row = rows.nth(i)
            bolds = row.locator("b")
            if bolds.count() == 0:
                continue  # 답글 행 건너뜀

            reviewer = bolds.first.inner_text().strip()
            text = row.inner_text()

            order_count = 0
            m = re.search(r"(\d+)회 주문", text)
            if m:
                order_count = int(m.group(1))

            date_str = ""
            m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
            if m:
                date_str = m.group(1)

            # 리뷰 텍스트 추출
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            bold_set = set(bolds.all_inner_texts())
            skip_pats = [
                re.compile(r"^\d+회 주문$"),
                re.compile(r"^\d{4}-\d{2}-\d{2}$"),
                re.compile(r"^주문메뉴$"),
                re.compile(r"^주문번호$"),
                re.compile(r"^수령방식$"),
                re.compile(r"^(배달|포장|매장식사)$"),
                re.compile(r"사장님 댓글"),
                re.compile(r"^[A-Za-z0-9]{4,}[ㆍ・·]"),
                re.compile(r"^\* "),
            ]
            review_lines = [
                ln for ln in lines
                if ln not in bold_set and not any(p.match(ln) for p in skip_pats)
            ]
            review_text = "\n".join(review_lines)

            # 이미지 (eats_review_api URL)
            imgs = row.locator("img")
            img_srcs = []
            for j in range(imgs.count()):
                src = imgs.nth(j).get_attribute("src") or ""
                if "eats_review_api" in src or "eats_review" in src:
                    img_srcs.append(src)

            all_results.append({
                "reviewer": reviewer,
                "order_count": order_count,
                "date": date_str,
                "review_text": review_text,
                "image_urls": img_srcs,
                "local_images": [],
            })

        # 다음 페이지
        next_btn = page.locator(f"button:has-text('{page_num + 1}')")
        if next_btn.count() == 0:
            break
        next_btn.first.click()
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            pass
        page.wait_for_timeout(1200)
        page_num += 1
        if page_num > 20:  # 안전장치
            break

    return all_results


# ---------------------------------------------------------------------------
# 메인 실행
# ---------------------------------------------------------------------------
cleanup_unused_images()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=False,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        storage_state=str(bot.CE_STORAGE_FILE) if bot.CE_STORAGE_FILE.exists() else None,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        locale="ko-KR",
    )
    context.add_init_script(STEALTH_SCRIPT)
    page = context.new_page()
    page.set_viewport_size({"width": 1280, "height": 900})

    page.goto(REVIEW_URL)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    page.wait_for_timeout(2000)
    bot.dismiss_modal(page)

    print("날짜 필터를 '최근 1주일'로 변경 중...")
    set_date_filter_1week(page)

    print("리뷰 목록 수집 중...")
    results = scrape_all_pages(page)
    browser.close()

print(f"\n총 {len(results)}건 수집 완료")

# 이미지 다운로드
print("\n이미지 다운로드 중...")
for r in results:
    for k, url in enumerate(r["image_urls"]):
        safe_name = re.sub(r"[^a-zA-Z0-9]", "_", r["reviewer"])[:20]
        dest = IMG_DIR / f"{r['date']}_{safe_name}_{k}.jpg"
        if not dest.exists():
            download_image(url, dest)
        if dest.exists():
            r["local_images"].append(str(dest))

with_images = [r for r in results if r["local_images"]]
print(f"사진 있는 리뷰: {len(with_images)}건")

# 제외 대상 로드
excluded = load_excluded_reviewers()
print(f"최근 {EXCLUDE_RECENT_RUNS}주 내 선정된 리뷰어 (제외): {excluded}")

# 카드 인식
eligible = [r for r in with_images if r["reviewer"] not in excluded]
print(f"\n카드 인증 사진 확인 중... ({len(eligible)}건, 5건씩 병렬 처리)")
from concurrent.futures import ThreadPoolExecutor

def _check_card(r):
    r["card_no"] = detect_card_no(r["local_images"], r["review_text"])
    status = r["card_no"] if r["card_no"] else "미확인"
    print(f"  - {r['reviewer']} ({r['date']}): {status}")

with ThreadPoolExecutor(max_workers=5) as ex:
    list(ex.map(_check_card, eligible))

with_card = [r for r in eligible if r.get("card_no")]
print(f"\n카드 인증 확인된 리뷰: {len(with_card)}건")

# 자동 선정
picks = []
reorder_pick = max(with_card, key=lambda r: r["order_count"]) if with_card else None
remaining = [r for r in with_card if r is not reorder_pick]
sincere_pick = pick_sincere_review(remaining)

for category, pick in [("재주문수_높은_리뷰", reorder_pick), ("정성스럽게_쓴_리뷰", sincere_pick)]:
    if not pick:
        continue
    picks.append({
        "category": category,
        "reviewer": pick["reviewer"],
        "date_written": pick["date"],
        "order_count": pick["order_count"],
        "card_no": pick["card_no"],
        "review_text": pick["review_text"],
        "images": [
            str(Path(p).relative_to(BASE_DIR)).replace("\\", "/")
            for p in pick["local_images"]
        ],
    })

if picks:
    save_picks(datetime.now().strftime("%Y-%m-%d"), picks)
    print(f"\n{len(picks)}건 자동 선정 완료, ce_card_review_picks.json에 저장했습니다.")
    for p in picks:
        print(f"  - [{p['category']}] {p['reviewer']} (카드 번호: {p['card_no']})")
else:
    print("\n선정 가능한 리뷰가 없습니다 (카드 인증 사진 없음 또는 모두 제외 대상).")

cleanup_unused_images()
