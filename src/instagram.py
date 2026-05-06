"""
바이브코딩 스쿨 — Instagram 카드뉴스 자동화 v2.1
──────────────────────────────────────────────────────
v2.1 변경사항:
  - 커버 카드(1번): Gemini 일러스트 + 어두운 오버레이 + 큰 훅 제목
  - 본문 카드(2~4): 보라 그라데이션 + 번호 + 제목 + 본문
  - CTA 카드(5번): 보라 그라데이션 + 별 + 요약 + 블로그 유도
  - 반환값 (post_url, card_image_urls) 유지 — main.py 호환

비용:
  - Gemini 이미지 카드 1장당 1회 생성 (블로그 썸네일과 동일 모델)
  - 본문/CTA는 PIL 그라데이션만 → 추가 비용 0
"""

import os
import sys
import io
import json
import time
import base64
import logging
import subprocess
import requests
import anthropic

from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

ANTHROPIC_API_KEY     = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY        = os.environ["GEMINI_API_KEY"]
INSTAGRAM_TOKEN       = os.environ["INSTAGRAM_ACCESS_TOKEN"]
INSTAGRAM_ACCOUNT_ID  = os.environ["INSTAGRAM_ACCOUNT_ID"]
CLOUDINARY_CLOUD_NAME = os.environ["CLOUDINARY_CLOUD_NAME"]
CLOUDINARY_API_KEY    = os.environ["CLOUDINARY_API_KEY"]
CLOUDINARY_API_SECRET = os.environ["CLOUDINARY_API_SECRET"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

W, H  = 1080, 1080
IMG_H = 720   # 커버 카드 사진 영역 높이 (66%)

# ─────────────────────────────────────────────────────────────
# VIBE 브랜드 컬러 (보라 그라데이션)
# ─────────────────────────────────────────────────────────────
BG_TOP   = (108,  61, 245)   # #6C3DF5 진한 보라
BG_BOT   = (168,  72, 200)   # #A848C8 핑크빛 보라
TEXT_HI  = (255, 255, 255)
TEXT_MID = (240, 220, 255)   # 라벤더
ACCENT   = (255, 215, 100)   # 골드 (브랜드명)

PAD     = 60
INNER_W = W - PAD * 2

# ─────────────────────────────────────────────────────────────
# 폰트
# ─────────────────────────────────────────────────────────────
_fcache: dict = {}

def _find_font(bold: bool) -> str | None:
    s = "Bold" if bold else "Regular"
    for p in [
        f"/usr/share/fonts/truetype/noto/NotoSansCJKkr-{s}.otf",
        f"/usr/share/fonts/opentype/noto/NotoSansCJKkr-{s}.otf",
        f"/usr/share/fonts/truetype/noto/NotoSansCJK-{s}.ttc",
        f"/usr/share/fonts/opentype/noto/NotoSansCJK-{s}.ttc",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
    ]:
        if os.path.exists(p):
            return p
    return None

def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    k = (size, bold)
    if k not in _fcache:
        path = _find_font(bold)
        if not path:
            try:
                subprocess.run(["apt-get", "install", "-y", "fonts-noto-cjk"],
                               check=True, capture_output=True)
            except Exception:
                pass
            path = _find_font(bold)
        _fcache[k] = ImageFont.truetype(path, size) if path else ImageFont.load_default()
    return _fcache[k]


# ─────────────────────────────────────────────────────────────
# 드로잉 유틸
# ─────────────────────────────────────────────────────────────

def purple_bg() -> Image.Image:
    """보라 세로 그라데이션 1080×1080."""
    img  = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    return img


def wrap_text(text: str, font: ImageFont.FreeTypeFont,
              max_w: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textbbox((0, 0), t, font=font)[2] > max_w and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def text_block(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
               fill: tuple, x: int, y: int, max_w: int,
               align: str = "left", line_gap: int = 12) -> int:
    for line in wrap_text(text, font, max_w, draw):
        bb = draw.textbbox((0, 0), line, font=font)
        lw, lh = bb[2] - bb[0], bb[3] - bb[1]
        dx = (max_w - lw) // 2 if align == "center" else 0
        draw.text((x + dx, y), line, font=font, fill=fill)
        y += lh + line_gap
    return y


def draw_pill(img: Image.Image, draw: ImageDraw.ImageDraw,
              x0: int, y0: int, x1: int, y1: int,
              fill: tuple, radius: int = 24) -> tuple:
    """RGBA pill 합성. (img, draw) 반환."""
    pill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)
    img_rgba = img.convert("RGBA")
    img_rgba = Image.alpha_composite(img_rgba, pill)
    img = img_rgba.convert("RGB")
    return img, ImageDraw.Draw(img)


def dot_row(draw: ImageDraw.ImageDraw, total: int, current: int, cy: int,
            on_dark: bool = False):
    """하단 도트 인디케이터."""
    DOT_R, GAP, ACT_W = 6, 14, 24
    total_w = (total - 1) * (DOT_R * 2 + GAP) + ACT_W
    x = W - PAD - total_w
    inactive = (255, 255, 255, 100) if on_dark else (200, 200, 220)
    for i in range(total):
        if i + 1 == current:
            draw.rounded_rectangle([x, cy - DOT_R, x + ACT_W, cy + DOT_R],
                                   radius=DOT_R, fill=TEXT_HI)
            x += ACT_W + GAP
        else:
            draw.ellipse([x, cy - DOT_R, x + DOT_R * 2, cy + DOT_R],
                         fill=inactive[:3] if not on_dark else (130, 100, 180))
            x += DOT_R * 2 + GAP


# ─────────────────────────────────────────────────────────────
# Gemini 이미지 생성
# ─────────────────────────────────────────────────────────────
def generate_cover_image(image_prompt: str) -> Image.Image | None:
    """블로그 썸네일과 동일한 Gemini 모델로 카드 커버용 일러스트 생성."""
    log.info("  🎨 커버 일러스트 생성 중...")
    enhanced = (
        f"{image_prompt}, modern flat illustration, vibrant purple and pink tones, "
        "1:1 square composition, no text no letters, professional tech illustration, "
        "centered subject, dark moody atmosphere"
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash-image:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": enhanced}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=90)
            resp.raise_for_status()
            for part in resp.json()["candidates"][0]["content"]["parts"]:
                if "inlineData" in part:
                    img_bytes = base64.b64decode(part["inlineData"]["data"])
                    log.info(f"    ✅ 커버 이미지 생성 완료 (시도 {attempt+1})")
                    return Image.open(io.BytesIO(img_bytes)).convert("RGB")
            log.warning(f"    ⚠️ inlineData 없음 (시도 {attempt+1}/3)")
        except Exception as e:
            log.warning(f"    ⚠️ 생성 실패 (시도 {attempt+1}/3): {e}")
        if attempt < 2:
            time.sleep(20 * (attempt + 1))
    log.error("    ❌ 커버 이미지 3회 실패 — 보라 그라데이션으로 fallback")
    return None


# ─────────────────────────────────────────────────────────────
# 카드 생성 — 커버 (1번)
# ─────────────────────────────────────────────────────────────
def make_cover_card(card: dict, total: int, cover_image: Image.Image | None) -> bytes:
    img = purple_bg()

    if cover_image is not None:
        # 위 IMG_H 영역에 일러스트 fit
        photo = cover_image
        pw, ph = photo.size
        target_ratio = (W - 40) / (IMG_H - 40)
        src_ratio    = pw / ph
        if src_ratio > target_ratio:
            new_w = int(ph * target_ratio)
            left  = (pw - new_w) // 2
            photo = photo.crop((left, 0, left + new_w, ph))
        else:
            new_h = int(pw / target_ratio)
            top   = (ph - new_h) // 2
            photo = photo.crop((0, top, pw, top + new_h))
        photo = photo.resize((W - 40, IMG_H - 40), Image.LANCZOS)

        # 둥근 모서리 마스크로 위 영역에 paste
        mask = Image.new("L", (W - 40, IMG_H - 40), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, W - 40, IMG_H - 40], radius=28, fill=255
        )
        img.paste(photo, (20, 20), mask)

        # 사진 위 어두운 그라데이션 (하단 텍스트 가독성)
        overlay = Image.new("RGBA", (W, IMG_H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for y in range(IMG_H):
            if y > IMG_H * 0.50:
                t = (y - IMG_H * 0.50) / (IMG_H * 0.50)
                alpha = int(180 * t)
                od.line([(0, y), (W, y)], fill=(40, 15, 70, alpha))
        img_rgba = img.convert("RGBA")
        img_rgba.paste(overlay, (0, 0), overlay)
        img = img_rgba.convert("RGB")

    draw = ImageDraw.Draw(img)

    # 좌상단 — 페이지 인디케이터
    page_text = f"{1} / {total}"
    f_page = load_font(28, bold=True)
    bb     = draw.textbbox((0, 0), page_text, font=f_page)
    pw_, ph_ = bb[2] - bb[0], bb[3] - bb[1]
    px0, py0 = 60, 60
    px1, py1 = px0 + pw_ + 32, py0 + ph_ + 16
    img, draw = draw_pill(img, draw, px0, py0, px1, py1,
                          fill=(0, 0, 0, 130), radius=24)
    draw.text((px0 + 16, py0 + 8), page_text, font=f_page, fill=TEXT_HI)

    # 좌하단 사진 위 — 태그 pill (흰 배경 + 보라 텍스트)
    tag = card.get("tag", "AI 뉴스")
    f_tag = load_font(28, bold=True)
    bb    = draw.textbbox((0, 0), tag, font=f_tag)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    tx0, ty0 = 60, IMG_H - 90
    tx1, ty1 = tx0 + tw + 36, ty0 + th + 18
    img, draw = draw_pill(img, draw, tx0, ty0, tx1, ty1,
                          fill=(255, 255, 255, 240), radius=24)
    draw.text((tx0 + 18, ty0 + 9), tag, font=f_tag, fill=BG_TOP)

    # 아래 영역 — 메인 제목
    text_y = IMG_H + 50
    f_title = load_font(72, bold=True)
    text_y = text_block(draw, card.get("title", ""), f_title, TEXT_HI,
                        PAD, text_y, INNER_W, line_gap=14)

    # 부제
    body = card.get("body", "")
    if body:
        text_y += 14
        f_body = load_font(34)
        text_block(draw, body, f_body, TEXT_MID, PAD, text_y, INNER_W)

    # 하단 브랜드 + 도트
    brand_y = H - 70
    f_brand = load_font(22, bold=True)
    draw.text((PAD, brand_y), "VIBE CODING SCHOOL", font=f_brand, fill=ACCENT)
    dot_row(draw, total, 1, brand_y + 12, on_dark=True)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# 카드 생성 — 본문 (2~4번)
# ─────────────────────────────────────────────────────────────
def make_content_card(card: dict, card_num: int, total: int) -> bytes:
    img  = purple_bg()
    draw = ImageDraw.Draw(img)

    # 상단 헤더 — 브랜드명 + 페이지
    f_brand = load_font(26, bold=True)
    draw.text((PAD, 54), "VIBE CODING SCHOOL", font=f_brand, fill=ACCENT)

    page_text = f"{card_num} / {total}"
    f_page = load_font(26, bold=True)
    bb     = draw.textbbox((0, 0), page_text, font=f_page)
    pw_, ph_ = bb[2] - bb[0], bb[3] - bb[1]
    px0 = W - PAD - pw_ - 36
    py0 = 44
    px1 = W - PAD
    py1 = py0 + ph_ + 22
    img, draw = draw_pill(img, draw, px0, py0, px1, py1,
                          fill=(255, 255, 255, 60), radius=28)
    draw.text((px0 + 18, py0 + 11), page_text, font=f_page, fill=TEXT_HI)

    # 구분선
    line_y = 130
    draw.line([(PAD, line_y), (W - PAD, line_y)],
              fill=(255, 255, 255, 80), width=2)

    # 큰 번호 배경 (배경 워터마크 느낌)
    big_num = str(card_num - 1)
    f_big   = load_font(360, bold=True)
    bb      = draw.textbbox((0, 0), big_num, font=f_big)
    bw, bh  = bb[2] - bb[0], bb[3] - bb[1]
    big_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd        = ImageDraw.Draw(big_layer)
    bd.text((W - PAD - bw - 20, 180), big_num, font=f_big,
            fill=(255, 255, 255, 38))
    img_rgba = img.convert("RGBA")
    img_rgba = Image.alpha_composite(img_rgba, big_layer)
    img      = img_rgba.convert("RGB")
    draw     = ImageDraw.Draw(img)

    # STEP 라벨
    step_label = f"STEP {str(card_num - 1).zfill(2)}"
    f_step = load_font(24, bold=True)
    bb     = draw.textbbox((0, 0), step_label, font=f_step)
    sw     = bb[2] - bb[0]
    sx0, sy0 = PAD, 220
    sx1, sy1 = sx0 + sw + 32, sy0 + (bb[3] - bb[1]) + 18
    img, draw = draw_pill(img, draw, sx0, sy0, sx1, sy1,
                          fill=(255, 255, 255, 240), radius=22)
    draw.text((sx0 + 16, sy0 + 9), step_label, font=f_step, fill=BG_TOP)

    # 메인 제목
    f_title = load_font(80, bold=True)
    title_y = 320
    title_y = text_block(draw, card.get("title", ""), f_title, TEXT_HI,
                         PAD, title_y, INNER_W, line_gap=14)

    # 본문
    body = card.get("body", "")
    if body:
        body_y = title_y + 36
        # 반투명 본문 박스
        f_body  = load_font(38)
        lines   = wrap_text(body, f_body, INNER_W - 56, draw)
        box_h   = len(lines) * 60 + 56
        box_y0  = body_y
        box_y1  = min(body_y + box_h, H - 130)
        img, draw = draw_pill(img, draw, PAD, box_y0, W - PAD, box_y1,
                              fill=(255, 255, 255, 35), radius=20)
        text_block(draw, body, f_body, TEXT_HI,
                   PAD + 28, box_y0 + 26, INNER_W - 56, line_gap=10)

    # 하단 도트
    dot_row(draw, total, card_num, H - 60, on_dark=True)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# 카드 생성 — CTA (5번)
# ─────────────────────────────────────────────────────────────
def make_cta_card(card: dict, card_num: int, total: int) -> bytes:
    img  = purple_bg()
    draw = ImageDraw.Draw(img)

    # 헤더
    f_brand = load_font(26, bold=True)
    draw.text((PAD, 54), "VIBE CODING SCHOOL", font=f_brand, fill=ACCENT)

    page_text = f"{card_num} / {total}"
    f_page = load_font(26, bold=True)
    bb = draw.textbbox((0, 0), page_text, font=f_page)
    pw_, ph_ = bb[2] - bb[0], bb[3] - bb[1]
    px0 = W - PAD - pw_ - 36
    py0 = 44
    img, draw = draw_pill(img, draw, px0, py0, W - PAD, py0 + ph_ + 22,
                          fill=(255, 255, 255, 60), radius=28)
    draw.text((px0 + 18, py0 + 11), page_text, font=f_page, fill=TEXT_HI)

    # 별 아이콘 원
    ICR = 80
    ICX, ICY = W // 2, 280
    img, draw = draw_pill(img, draw,
                          ICX - ICR, ICY - ICR, ICX + ICR, ICY + ICR,
                          fill=(255, 255, 255, 240), radius=ICR)
    f_ico = load_font(80, bold=True)
    bb = draw.textbbox((0, 0), "*", font=f_ico)
    draw.text((ICX - (bb[2] - bb[0]) // 2,
               ICY - (bb[3] - bb[1]) // 2 - 8),
              "*", font=f_ico, fill=BG_TOP)

    # 제목
    f_title = load_font(72, bold=True)
    y = ICY + ICR + 44
    y = text_block(draw, card.get("title", "오늘의 핵심 요약"),
                   f_title, TEXT_HI, PAD, y, INNER_W,
                   align="center", line_gap=14)

    # 본문 박스 (반투명)
    body = card.get("body", "")
    if body:
        f_body = load_font(36)
        lines  = wrap_text(body, f_body, INNER_W - 60, draw)
        box_h  = len(lines) * 56 + 56
        bx0, by0 = PAD, y + 24
        bx1, by1 = W - PAD, by0 + box_h
        img, draw = draw_pill(img, draw, bx0, by0, bx1, by1,
                              fill=(255, 255, 255, 35), radius=22)
        text_block(draw, body, f_body, TEXT_HI,
                   bx0 + 30, by0 + 28, INNER_W - 60,
                   align="center", line_gap=10)
        y = by1 + 28

    # CTA 버튼 (흰 배경 + 보라 텍스트)
    btn_text = "블로그에서 더 보기  >"
    f_btn = load_font(38, bold=True)
    bb = draw.textbbox((0, 0), btn_text, font=f_btn)
    bw_ = bb[2] - bb[0]
    bx0_ = (W - bw_) // 2 - 48
    by0_ = max(y + 8, H - 200)
    bx1_ = bx0_ + bw_ + 96
    by1_ = by0_ + 84
    img, draw = draw_pill(img, draw, bx0_, by0_, bx1_, by1_,
                          fill=(255, 255, 255, 250), radius=42)
    draw.text(((W - bw_) // 2, by0_ + 22), btn_text, font=f_btn, fill=BG_TOP)

    # 도트
    dot_row(draw, total, card_num, H - 60, on_dark=True)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# 통합 카드 생성
# ─────────────────────────────────────────────────────────────
def make_card_image(card: dict, card_num: int, total: int,
                    cover_image: Image.Image | None = None) -> bytes:
    if card_num == 1:
        return make_cover_card(card, total, cover_image)
    elif card_num == total:
        return make_cta_card(card, card_num, total)
    else:
        return make_content_card(card, card_num, total)


# ─────────────────────────────────────────────────────────────
# Claude 호출
# ─────────────────────────────────────────────────────────────
def call_claude(prompt: str, max_tokens: int = 1500) -> dict:
    for attempt in range(3):
        try:
            time.sleep(10)
            resp = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            if "```" in raw:
                for part in raw.split("```"):
                    part = part.strip().lstrip("json").strip()
                    if part.startswith("{"):
                        raw = part
                        break
            return json.loads(raw.strip())
        except Exception as e:
            log.warning(f"  ⚠️ Claude 호출 실패 (시도 {attempt+1}/3): {e}")
            time.sleep(20 * (attempt + 1))
    raise RuntimeError("Claude API 3회 모두 실패")


def call_claude_text(prompt: str, max_tokens: int = 200) -> str:
    for attempt in range(3):
        try:
            time.sleep(8)
            resp = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            log.warning(f"  ⚠️ Claude 호출 실패 (시도 {attempt+1}/3): {e}")
            time.sleep(20 * (attempt + 1))
    return ""


# ─────────────────────────────────────────────────────────────
# STEP 1: 스크립트 생성 (+ 커버 이미지 프롬프트)
# ─────────────────────────────────────────────────────────────
def generate_card_script(blog_title: str, blog_content_html: str, tags: list) -> dict:
    log.info("📝 카드뉴스 스크립트 생성 중...")
    prompt = f"""
블로그 글을 인스타그램 카드뉴스 5장으로 변환해줘.

블로그 제목: {blog_title}
블로그 태그: {', '.join(tags)}
블로그 본문 (HTML):
{blog_content_html[:3000]}

## 카드 구성
- 카드 1 (커버): tag(카테고리 6자 이내) + title(훅 질문 20자 이내) + body(부제 30자 이내)
- 카드 2~4 (본문): title(15자 이내) + body(40자 이내, 핵심 설명)
- 카드 5 (CTA): title(15자 이내) + body(블로그 유도 40자 이내)

## 규칙
- 이모지 절대 금지
- ~해요, ~거예요 말투
- 일반인 눈높이

## cover_image_prompt
- 카드 1번에 들어갈 일러스트 영문 프롬프트 (50단어 이내)
- 주제와 어울리는 시각적 메타포
- 모던 플랫 일러스트 스타일
- 텍스트 없음, 1:1 정사각형 구도

## 캡션
- 400~700자, 첫 줄=후크, 줄바꿈 적극 활용
- 끝: "전체 가이드는 블로그에서 보세요" + 프로필 링크 안내
- 해시태그 5~7개, 이모지 금지

JSON만 출력 (코드블록 없이):
{{
  "cards": [
    {{"card_num": 1, "tag": "카테고리", "title": "훅 제목", "body": "부제"}},
    {{"card_num": 2, "title": "핵심1", "body": "설명"}},
    {{"card_num": 3, "title": "핵심2", "body": "설명"}},
    {{"card_num": 4, "title": "핵심3", "body": "설명"}},
    {{"card_num": 5, "title": "요약 제목", "body": "블로그 유도 문구"}}
  ],
  "cover_image_prompt": "english illustration prompt for card 1",
  "caption": "캡션 전체 (해시태그 포함, 이모지 없이)"
}}
"""
    result = call_claude(prompt, max_tokens=1500)
    log.info("  ✅ 스크립트 완료")
    return result


# ─────────────────────────────────────────────────────────────
# STEP 2: Cloudinary 업로드
# ─────────────────────────────────────────────────────────────
def upload_to_cloudinary(image_bytes: bytes, public_id: str) -> str:
    import hashlib
    log.info(f"  ☁️  업로드: {public_id}")

    resp = requests.post(
        f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload",
        data={"upload_preset": "ml_default", "public_id": public_id},
        files={"file": ("card.png", image_bytes, "image/png")},
        timeout=60,
    )
    if not resp.ok:
        timestamp = str(int(time.time()))
        sig = hashlib.sha1(
            (f"public_id={public_id}&timestamp={timestamp}" + CLOUDINARY_API_SECRET).encode()
        ).hexdigest()
        resp = requests.post(
            f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload",
            data={"public_id": public_id, "timestamp": timestamp,
                  "api_key": CLOUDINARY_API_KEY, "signature": sig},
            files={"file": ("card.png", image_bytes, "image/png")},
            timeout=60,
        )
    resp.raise_for_status()
    url = (resp.json().get("url") or resp.json().get("secure_url", "")).replace("http://", "https://")
    log.info(f"    ✅ {url[:70]}...")
    return url


# ─────────────────────────────────────────────────────────────
# STEP 3: Instagram 캐러셀 포스팅
# ─────────────────────────────────────────────────────────────
def post_carousel_to_instagram(image_urls: list, caption: str) -> str:
    log.info("📤 Instagram 포스팅 중...")
    base = "https://graph.instagram.com/v25.0"

    children = []
    for i, url in enumerate(image_urls):
        for attempt in range(3):
            r = requests.post(f"{base}/{INSTAGRAM_ACCOUNT_ID}/media",
                              json={"image_url": url, "is_carousel_item": True,
                                    "access_token": INSTAGRAM_TOKEN}, timeout=30)
            if r.ok:
                break
            log.warning(f"  컨테이너 실패 {attempt+1}/3: {r.text[:80]}")
            time.sleep(30)
        r.raise_for_status()
        children.append(r.json()["id"])
        time.sleep(2)

    for attempt in range(3):
        r = requests.post(f"{base}/{INSTAGRAM_ACCOUNT_ID}/media",
                          json={"media_type": "CAROUSEL",
                                "children": ",".join(children),
                                "caption": caption,
                                "access_token": INSTAGRAM_TOKEN}, timeout=30)
        if r.ok:
            break
        time.sleep(30)
    r.raise_for_status()
    cid = r.json()["id"]

    time.sleep(10)
    for attempt in range(3):
        r = requests.post(f"{base}/{INSTAGRAM_ACCOUNT_ID}/media_publish",
                          json={"creation_id": cid, "access_token": INSTAGRAM_TOKEN},
                          timeout=30)
        if r.ok:
            break
        if r.json().get("error", {}).get("is_transient"):
            time.sleep(30 * (attempt + 1))
        else:
            r.raise_for_status()
    r.raise_for_status()

    url = f"https://www.instagram.com/p/{r.json()['id']}/"
    log.info(f"  ✅ 포스팅 완료: {url}")
    return url


# ─────────────────────────────────────────────────────────────
# 메인 (main.py에서 호출)  반환: (post_url, card_image_urls)
# ─────────────────────────────────────────────────────────────
def post_instagram(blog_title: str, blog_content_html: str, tags: list) -> tuple:
    log.info("=" * 50)
    log.info("📸 Instagram 카드뉴스 v2.1 (보라+커버일러스트) 시작")
    log.info("=" * 50)

    # 1. 스크립트 생성
    script  = generate_card_script(blog_title, blog_content_html, tags)
    cards   = script["cards"]
    caption = script["caption"]
    total   = len(cards)
    cover_prompt = script.get("cover_image_prompt", "")

    # 2. 커버용 일러스트 생성 (실패해도 보라 그라데이션으로 fallback)
    cover_image = generate_cover_image(cover_prompt) if cover_prompt else None

    # 3. 카드별 생성 + 업로드
    prefix = datetime.now().strftime("%Y%m%d%H%M")
    image_urls = []
    for card in cards:
        num = card["card_num"]
        log.info(f"  🎨 카드 {num}/{total} 생성...")
        img_bytes = make_card_image(card, num, total, cover_image=cover_image)
        url = upload_to_cloudinary(img_bytes, f"vibe_school/{prefix}_card{num}")
        image_urls.append(url)
        time.sleep(1)

    # 4. 캐러셀 포스팅
    post_url = post_carousel_to_instagram(image_urls, caption)

    log.info("=" * 50)
    log.info(f"🎉 완료: {post_url}")
    log.info("=" * 50)
    return post_url, image_urls
