"""
바이브코딩 스쿨 — Instagram 카드뉴스 자동화
──────────────────────────────────────────────
블로그 글 → 카드뉴스 5장 → Instagram 카루셀 포스팅
디자인: 비비드 그라데이션 (보라 → 핑크)
이미지 호스팅: Cloudinary (무료, Unsigned 업로드)
"""

import os
import sys
import json
import time
import logging
import subprocess
import requests
import anthropic

from io import BytesIO
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

ANTHROPIC_API_KEY       = os.environ["ANTHROPIC_API_KEY"]
INSTAGRAM_TOKEN         = os.environ["INSTAGRAM_ACCESS_TOKEN"]
INSTAGRAM_ACCOUNT_ID    = os.environ["INSTAGRAM_ACCOUNT_ID"]
CLOUDINARY_CLOUD_NAME   = os.environ["CLOUDINARY_CLOUD_NAME"]
CLOUDINARY_API_KEY      = os.environ["CLOUDINARY_API_KEY"]
CLOUDINARY_API_SECRET   = os.environ["CLOUDINARY_API_SECRET"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

W, H = 1080, 1080  # 인스타 정방형


# ═════════════════════════════════════════════════════════════
# 폰트 설정
# ═════════════════════════════════════════════════════════════
def get_font_path(bold: bool = False) -> str:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJKkr-Bold.otf" if bold else
        "/usr/share/fonts/truetype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Bold.otf" if bold else
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            log.info(f"  ✅ 폰트 로드: {path}")
            return path
    log.warning("  ⚠️ 한글 폰트 없음, 강제 설치 시도...")
    try:
        subprocess.run(["apt-get", "install", "-y", "fonts-noto-cjk"],
                       check=True, capture_output=True)
        for path in candidates:
            if os.path.exists(path):
                return path
    except Exception as e:
        log.warning(f"  ⚠️ 폰트 설치 실패: {e}")
    return None


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = get_font_path(bold)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ═════════════════════════════════════════════════════════════
# 유틸
# ═════════════════════════════════════════════════════════════
def call_claude(prompt: str, max_tokens: int = 1500) -> dict:
    for attempt in range(3):
        try:
            time.sleep(10)
            response = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            if "```" in raw:
                for part in raw.split("```"):
                    part = part.strip().lstrip("json").strip()
                    if part.startswith("{"):
                        raw = part
                        break
            return json.loads(raw.strip())
        except Exception as e:
            wait = 20 * (attempt + 1)
            log.warning(f"  ⚠️ Claude 호출 실패 (시도 {attempt+1}/3): {e}")
            time.sleep(wait)
    raise RuntimeError("Claude API 호출 3회 모두 실패")


def draw_gradient(draw: ImageDraw.ImageDraw, w: int, h: int):
    for y in range(h):
        t = y / h
        r = int(108 + (200 - 108) * t)
        g = int(61  + (64  - 61 ) * t)
        b = int(245 + (168 - 245) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def wrap_text(text: str, font: ImageFont.FreeTypeFont,
              max_width: int, draw: ImageDraw.ImageDraw) -> list:
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_width and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines


# ═════════════════════════════════════════════════════════════
# STEP 1: 카드뉴스 스크립트 생성
# ═════════════════════════════════════════════════════════════
def generate_card_script(blog_title: str, blog_content_html: str, tags: list) -> dict:
    log.info("📝 카드뉴스 스크립트 생성 중...")
    prompt = f"""
블로그 글을 인스타그램 카드뉴스 5장으로 변환해줘.

블로그 제목: {blog_title}
블로그 태그: {', '.join(tags)}
블로그 본문 (HTML):
{blog_content_html[:3000]}

## 카드 구성
- 카드 1 (훅): 궁금증 유발하는 한 줄 질문 or 충격적 사실
- 카드 2~4 (본문): 핵심 내용 각 1가지씩 (제목 + 설명 2~3줄)
- 카드 5 (마무리): 핵심 요약 + "블로그에서 더 보기" 유도

## 중요 규칙
- 이모지는 절대 사용하지 마세요 (렌더링 문제 있음)
- 제목: 15자 이내로 짧게
- 본문: 50자 이내
- 독자: 코딩 0% 일반인
- 말투: 친근하고 쉽게 (~해요체)

## 캡션 규칙
- 200자 이내
- 줄바꿈 활용
- 해시태그 15개 (이모지 없이)

JSON만 출력 (코드블록 없이):
{{
  "cards": [
    {{"card_num": 1, "title": "훅 제목", "body": ""}},
    {{"card_num": 2, "title": "핵심1", "body": "설명"}},
    {{"card_num": 3, "title": "핵심2", "body": "설명"}},
    {{"card_num": 4, "title": "핵심3", "body": "설명"}},
    {{"card_num": 5, "title": "마무리", "body": "블로그 링크 유도"}}
  ],
  "caption": "인스타 캡션 (해시태그 포함, 이모지 없이)"
}}
"""
    script = call_claude(prompt, max_tokens=1500)
    log.info("  ✅ 스크립트 생성 완료")
    return script


# ═════════════════════════════════════════════════════════════
# STEP 2: 카드 이미지 생성
# ═════════════════════════════════════════════════════════════
def make_card_image(card: dict, card_num: int, total: int) -> bytes:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    draw_gradient(draw, W, H)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 50))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    font_brand = load_font(30, bold=True)
    font_page  = load_font(28)
    font_title = load_font(72, bold=True)
    font_body  = load_font(38)
    badge_font = load_font(36, bold=True)

    draw.text((54, 50), "바이브코딩 스쿨", font=font_brand, fill=(255, 255, 255))

    page_text = f"{card_num} / {total}"
    bbox = draw.textbbox((0, 0), page_text, font=font_page)
    draw.text((W - bbox[2] - 54, 54), page_text, font=font_page, fill=(255, 255, 255))

    badge_size = 80
    badge_x = W // 2 - badge_size // 2
    badge_y = 280
    draw.ellipse([badge_x, badge_y, badge_x + badge_size, badge_y + badge_size],
                 fill=(255, 255, 255, 60))
    draw.text((W // 2, badge_y + badge_size // 2), str(card_num),
              font=badge_font, fill="white", anchor="mm")

    title = card.get("title", "")
    title_lines = wrap_text(title, font_title, W - 100, draw)
    y = 410
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        x = (W - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=font_title, fill="white")
        y += bbox[3] - bbox[1] + 14

    body = card.get("body", "")
    if body:
        body_lines = wrap_text(body, font_body, W - 140, draw)
        y += 24
        for line in body_lines:
            bbox = draw.textbbox((0, 0), line, font=font_body)
            x = (W - (bbox[2] - bbox[0])) // 2
            draw.text((x, y), line, font=font_body, fill=(255, 255, 255))
            y += bbox[3] - bbox[1] + 10

    bar_y = H - 80
    draw.rounded_rectangle([54, bar_y, W - 54, bar_y + 5], radius=3, fill=(255, 255, 255))

    dot_r = 7
    dot_gap = 22
    dot_start_x = W // 2 - (total * dot_gap) // 2
    for i in range(total):
        cx = dot_start_x + i * dot_gap
        cy = H - 44
        if i + 1 == card_num:
            draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill="white")
        else:
            draw.ellipse([cx - dot_r + 2, cy - dot_r + 2, cx + dot_r - 2, cy + dot_r - 2],
                         fill=(200, 200, 255))

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════
# STEP 3: Cloudinary 업로드 (Unsigned → 완전 공개 URL)
# ═════════════════════════════════════════════════════════════
def upload_to_cloudinary(image_bytes: bytes, public_id: str) -> str:
    log.info(f"  ☁️  Cloudinary 업로드: {public_id}")

    resp = requests.post(
        f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload",
        data={
            "upload_preset": "ml_default",
            "public_id": public_id,
        },
        files={"file": ("card.png", image_bytes, "image/png")},
        timeout=60,
    )

    if resp.status_code != 200:
        log.warning("  ⚠️ Unsigned 업로드 실패, Signed 방식으로 재시도...")
        import hashlib
        timestamp = str(int(time.time()))
        params_to_sign = f"public_id={public_id}&timestamp={timestamp}"
        signature = hashlib.sha1(
            (params_to_sign + CLOUDINARY_API_SECRET).encode()
        ).hexdigest()
        resp = requests.post(
            f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload",
            data={
                "public_id": public_id,
                "timestamp": timestamp,
                "api_key": CLOUDINARY_API_KEY,
                "signature": signature,
            },
            files={"file": ("card.png", image_bytes, "image/png")},
            timeout=60,
        )

    resp.raise_for_status()
    result = resp.json()
    url = result.get("url") or result.get("secure_url")
    url = url.replace("http://", "https://")
    log.info(f"    ✅ 업로드 완료: {url[:70]}...")
    return url


# ═════════════════════════════════════════════════════════════
# STEP 4: Instagram 카루셀 포스팅 (재시도 로직 포함)
# ═════════════════════════════════════════════════════════════
def post_carousel_to_instagram(image_urls: list, caption: str) -> str:
    log.info("📤 Instagram 카루셀 포스팅 중...")
    base = "https://graph.instagram.com/v25.0"

    # 미디어 컨테이너 생성
    children_ids = []
    for i, url in enumerate(image_urls):
        log.info(f"  🖼️  미디어 컨테이너 {i+1}/{len(image_urls)}: {url[:60]}")
        for attempt in range(3):
            resp = requests.post(
                f"{base}/{INSTAGRAM_ACCOUNT_ID}/media",
                json={
                    "image_url": url,
                    "is_carousel_item": True,
                    "access_token": INSTAGRAM_TOKEN,
                },
                timeout=30,
            )
            if resp.ok:
                break
            log.warning(f"  ⚠️ 컨테이너 생성 실패 (시도 {attempt+1}/3): {resp.text[:100]}")
            time.sleep(30)
        resp.raise_for_status()
        children_ids.append(resp.json()["id"])
        time.sleep(2)

    # 카루셀 컨테이너 생성
    log.info("  📦 카루셀 컨테이너 생성 중...")
    for attempt in range(3):
        resp = requests.post(
            f"{base}/{INSTAGRAM_ACCOUNT_ID}/media",
            json={
                "media_type": "CAROUSEL",
                "children": ",".join(children_ids),
                "caption": caption,
                "access_token": INSTAGRAM_TOKEN,
            },
            timeout=30,
        )
        if resp.ok:
            break
        log.warning(f"  ⚠️ 카루셀 생성 실패 (시도 {attempt+1}/3): {resp.text[:100]}")
        time.sleep(30)
    resp.raise_for_status()
    carousel_id = resp.json()["id"]

    # 게시
    log.info("  🚀 게시 중...")
    time.sleep(10)  # ✅ 5초→10초로 늘림 (Instagram 처리 시간 확보)
    for attempt in range(3):
        resp = requests.post(
            f"{base}/{INSTAGRAM_ACCOUNT_ID}/media_publish",
            json={
                "creation_id": carousel_id,
                "access_token": INSTAGRAM_TOKEN,
            },
            timeout=30,
        )
        if resp.ok:
            break
        error_data = resp.json().get("error", {})
        is_transient = error_data.get("is_transient", False)
        log.warning(f"  ⚠️ 게시 실패 (시도 {attempt+1}/3, transient={is_transient}): {resp.text[:100]}")
        if is_transient:
            wait = 30 * (attempt + 1)
            log.info(f"  ⏳ {wait}초 대기 후 재시도...")
            time.sleep(wait)
        else:
            resp.raise_for_status()
    resp.raise_for_status()

    post_id = resp.json()["id"]
    post_url = f"https://www.instagram.com/p/{post_id}/"
    log.info(f"  ✅ 포스팅 완료: {post_url}")
    return post_url


# ═════════════════════════════════════════════════════════════
# 메인 함수 (main.py에서 호출)
# ═════════════════════════════════════════════════════════════
def post_instagram(blog_title: str, blog_content_html: str, tags: list) -> str:
    log.info("=" * 50)
    log.info("📸 Instagram 카드뉴스 자동화 시작")
    log.info("=" * 50)

    script  = generate_card_script(blog_title, blog_content_html, tags)
    cards   = script["cards"]
    caption = script["caption"]
    total   = len(cards)

    prefix = datetime.now().strftime("%Y%m%d%H%M")
    image_urls = []
    for card in cards:
        log.info(f"  🎨 카드 {card['card_num']} 생성 중...")
        img_bytes = make_card_image(card, card["card_num"], total)
        public_id = f"vibe_school/{prefix}_card{card['card_num']}"
        url = upload_to_cloudinary(img_bytes, public_id)
        image_urls.append(url)
        time.sleep(1)

    post_url = post_carousel_to_instagram(image_urls, caption)

    log.info("=" * 50)
    log.info(f"🎉 Instagram 포스팅 완료: {post_url}")
    log.info("=" * 50)
    return post_url
