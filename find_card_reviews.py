import re
import sys
import json
import base64
from pathlib import Path

# Windows 콘솔(cp949)에서 이모지 등 출력 시 UnicodeEncodeError가 나는 것을 방지
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

import baemin_bot as bot

BASE_DIR = bot.BASE_DIR
STORAGE_STATE_FILE = bot.STORAGE_STATE_FILE
# 카드이벤트 후보는 답변 여부와 무관하게 모든 리뷰에서 찾아야 하므로
# 미답변 탭(tab=noComment)이 아닌 전체 리뷰 페이지를 사용한다.
_config = bot.load_config()
REVIEW_URL = f"https://self.baemin.com/shops/{_config['shop_id']}/reviews"
IMG_DIR = BASE_DIR / "review_images"
IMG_DIR.mkdir(exist_ok=True)
PICKS_FILE = BASE_DIR / "card_review_picks.json"

client = bot.client
CLAUDE_MODEL = bot.CLAUDE_MODEL

# 이번 작업은 주 1회(최근 7일치 리뷰) 진행. 한 번 선정된 리뷰어는 이후 8회(8주)동안 재선정하지 않음.
EXCLUDE_RECENT_RUNS = 8

# 매주 실행 기준: 오늘로부터 최근 7일치 리뷰만 수집
CUTOFF = (datetime.now() - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)


def load_excluded_reviewers() -> set:
    """최근 EXCLUDE_RECENT_RUNS회 동안 선정된 리뷰어 이름 집합을 반환."""
    if not PICKS_FILE.exists():
        return set()
    data = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
    runs = data.get("runs", [])[-EXCLUDE_RECENT_RUNS:]
    excluded = set()
    for run in runs:
        for pick in run.get("picks", []):
            excluded.add(pick["reviewer"])
    return excluded


def save_picks(date_str: str, picks: list) -> None:
    data = {"runs": []}
    if PICKS_FILE.exists():
        data = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
        data.setdefault("runs", [])
    data["runs"].append({"date": date_str, "picks": picks})
    PICKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_unused_images() -> None:
    """card_review_picks.json에서 선정되지 않은(참조되지 않는) 후보 이미지를 review_images에서 삭제한다."""
    referenced = set()
    if PICKS_FILE.exists():
        data = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
        for run in data.get("runs", []):
            for pick in run.get("picks", []):
                for img_path in pick.get("images", []):
                    referenced.add((BASE_DIR / img_path).resolve())

    removed = 0
    for f in IMG_DIR.glob("*.jpg"):
        if f.resolve() not in referenced:
            f.unlink()
            removed += 1
    if removed:
        print(f"[INFO] 선정되지 않은 후보 이미지 {removed}개를 정리했습니다.")

_BOILERPLATE_PATTERNS = [
    re.compile(r"^\d{4}년 \d{1,2}월 \d{1,2}일$"),
    re.compile(r"^리뷰번호 \d+$"),
    re.compile(r"^\d+회 주문 고객$"),
    re.compile(r"^\(.*누적 주문\)$"),
    re.compile(r"^파트너님에게만 보이는 리뷰입니다\.$"),
    re.compile(r"^(배달|포장|알뜰배달)리뷰?$"),
    re.compile(r"^좋아요\d*$"),
    re.compile(r"^사장님 댓글 등록하기$"),
    re.compile(r"^알뜰배달$"),
]


def parse_date(text):
    m = re.search(r"(\d{4})년 (\d{1,2})월 (\d{1,2})일", text)
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    return datetime(y, mo, d)


def parse_order_count(text):
    m = re.search(r"(\d+)회 주문 고객", text)
    return int(m.group(1)) if m else 0


def detect_card_no(local_images: list, review_text: str = "") -> str | None:
    """이미지와 리뷰 텍스트를 Claude로 확인해, 이벤트용 번호카드 번호를 찾으면 반환한다.
    음식과 카드가 함께 찍힌 사진도 인식 대상에 포함되며, 사진 없이 리뷰 본문에
    카드 번호를 직접 적어둔 경우도 인식 대상에 포함된다."""
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
            "- 사진에 카드가 없더라도, 리뷰 텍스트에 손님이 카드에 적힌 번호를 직접 적어둔 경우"
            "(예: 리뷰 맨 앞이나 뒤에 숫자만 단독으로 적힌 경우)도 인정합니다.\n"
            "카드 번호를 찾으면 정확히 읽어 "
            '다음 JSON 형식으로만 답하세요: {"has_card": true, "card_no": "1234"} '
            '찾지 못하면 {"has_card": false, "card_no": null} 로만 답하세요. '
            "다른 설명이나 텍스트는 출력하지 마세요.\n\n"
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
        data = json.loads(m.group()) if m else json.loads(text)
    except Exception as e:
        print(f"  [경고] 카드 인식 실패: {e}")
        return None

    if data.get("has_card") and data.get("card_no"):
        return str(data["card_no"])
    return None


def pick_sincere_review(candidates: list) -> dict | None:
    """후보 중 가장 정성스럽게/구체적으로 작성된 리뷰를 Claude에게 골라달라고 요청한다."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    listing = "\n\n".join(
        f"[{i}] (주문 {c['order_count']}회, 작성자: {c['reviewer']})\n{c['review_text'] or '(텍스트 없음)'}"
        for i, c in enumerate(candidates)
    )
    prompt = (
        "아래는 리뷰 후보 목록입니다. 이 중에서 가장 정성스럽고 구체적으로, "
        "진심을 담아 작성된 리뷰를 하나 골라 그 번호만 출력하세요. "
        "숫자만 출력하고 다른 텍스트는 출력하지 마세요.\n\n"
        f"{listing}"
    )
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        idx = int(re.search(r"\d+", resp.content[0].text).group())
        return candidates[idx]
    except Exception as e:
        print(f"  [경고] 리뷰 선정 실패, 첫 번째 후보로 대체: {e}")
        return candidates[0]


cleanup_unused_images()

with sync_playwright() as playwright:
    browser, context, page = bot.login(playwright)
    page.goto(REVIEW_URL)
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        pass
    page.wait_for_timeout(1500)

    results = []
    seen_keys: set[str] = set()
    stale = 0
    found_old = False

    bot._dismiss_baemin_overlays(page)

    for _ in range(300):
        cards = page.locator('[class*="ReviewContent-module"]')
        n = cards.count()
        new_found = False

        for i in range(n):
            card = cards.nth(i)
            try:
                text = card.inner_text()
            except Exception:
                continue
            m = re.search(r"리뷰번호 (\d+)", text)
            review_no = m.group(1) if m else ""
            card_key = f"{review_no}|{text[:60]}"
            if card_key in seen_keys:
                continue
            seen_keys.add(card_key)
            new_found = True

            date = parse_date(text)
            if date is None:
                continue
            if date < CUTOFF:
                found_old = True
                continue

            imgs = card.locator('[class*="ReviewImages-module"] img')
            img_srcs = []
            for j in range(imgs.count()):
                src = imgs.nth(j).get_attribute("src")
                if src:
                    img_srcs.append(src)

            lines = [l.strip() for l in text.split("\n") if l.strip()]

            badge_texts = set(card.locator('[class*="Badge"]').all_inner_texts())
            name_idx = 0
            while name_idx < len(lines) and lines[name_idx] in badge_texts:
                name_idx += 1
            reviewer = lines[name_idx] if name_idx < len(lines) else (lines[0] if lines else "")

            order_count = parse_order_count(text)

            text_lines = []
            for ln in lines[name_idx + 1:]:
                if any(p.match(ln) for p in _BOILERPLATE_PATTERNS):
                    continue
                text_lines.append(ln)
            review_text = "\n".join(text_lines)

            results.append({
                "review_no": review_no or f"idx{len(results)}",
                "reviewer": reviewer,
                "date": date.strftime("%Y-%m-%d"),
                "order_count": order_count,
                "review_text": review_text,
                "images": img_srcs,
            })

        if found_old or (not new_found and (stale := stale + 1) >= 5):
            break
        if new_found:
            stale = 0

        # 가상 리스트 대응 스크롤
        if n > 0:
            last = cards.nth(n - 1)
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

    print(f"7일 내 리뷰 수집: {len(results)}건")

    # 이미지 포함 리뷰만 다운로드
    img_results = [r for r in results if r["images"]]
    print(f"이미지 포함 리뷰: {len(img_results)}건")

    for r in img_results:
        for idx, src in enumerate(r["images"]):
            try:
                resp = context.request.get(src)
                fname = IMG_DIR / f"{r['review_no']}_{idx}.jpg"
                fname.write_bytes(resp.body())
                r.setdefault("local_images", []).append(str(fname))
            except Exception as e:
                print(f"  이미지 다운로드 실패 {src}: {e}")

    (BASE_DIR / "card_review_candidates.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    excluded = load_excluded_reviewers()
    print(f"\n최근 {EXCLUDE_RECENT_RUNS}회 선정되어 이번에 제외할 리뷰어: {excluded or '없음'}")

    print("\n=== 이미지 포함 리뷰 목록 ===")
    for r in img_results:
        mark = " [제외 대상]" if r["reviewer"] in excluded else ""
        print(f"- {r['date']} {r['reviewer']}{mark} (주문 {r['order_count']}회) : {r['review_text'][:60]}")
        print(f"    이미지: {r.get('local_images')}")

    browser.close()

# ---------------------------------------------------------------------------
# 카드 인증 사진 자동 인식 + 이번 주 선정
# ---------------------------------------------------------------------------
eligible = [
    r for r in img_results
    if r["reviewer"] not in excluded and r.get("local_images")
]

print(f"\n카드 인증 사진 확인 중... ({len(eligible)}건)")
for r in eligible:
    r["card_no"] = detect_card_no(r["local_images"], r["review_text"])
    status = r["card_no"] if r["card_no"] else "미확인"
    print(f"  - {r['reviewer']}: {status}")

with_card = [r for r in eligible if r["card_no"]]
print(f"카드 인증이 확인된 리뷰: {len(with_card)}건")

picks = []

# 재주문수가 높은 리뷰: 주문 횟수가 가장 많은 후보를 선택
reorder_pick = max(with_card, key=lambda r: r["order_count"]) if with_card else None

# 정성스럽게 쓴 리뷰: 위에서 고른 후보를 제외한 나머지 중 Claude가 선택
remaining = [r for r in with_card if r is not reorder_pick]
sincere_pick = pick_sincere_review(remaining)

for category, pick in [("재주문수_높은_리뷰", reorder_pick), ("정성스럽게_쓴_리뷰", sincere_pick)]:
    if not pick:
        continue
    picks.append({
        "category": category,
        "reviewer": pick["reviewer"],
        "review_no": pick["review_no"],
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
    print(f"\n{len(picks)}건 자동 선정 완료, card_review_picks.json에 저장했습니다.")
    for p in picks:
        print(f"  - [{p['category']}] {p['reviewer']} (카드 번호: {p['card_no']})")
else:
    print("\n선정 가능한 리뷰가 없습니다 (카드 인증 사진 없음 또는 모두 제외 대상).")

cleanup_unused_images()
