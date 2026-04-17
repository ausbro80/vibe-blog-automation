"""
바이브코딩 스쿨 — YouTube Shorts 자동화 v4.0
─────────────────────────────────────────
v4.0 변경사항 (도달률·블로그 유입 최적화):
  - 인트로 로고/나레이션 제거 → 첫 프레임부터 후크 (retention +20~40%)
  - 아웃로 나레이션 → 무음 1.5초 블로그 CTA 끝카드 (TTS 1회 절감)
  - Card 1 후크 4공식 강제, hook_keyword 필드로 큰 자막 최적화
  - 자막 폰트 48 → 60pt (무음 시청자 가독성)
  - TTS 1.1x → 1.18x (쇼츠 평균 retention 최적)
  - 릴스 캡션 분리 (#Shorts 제거, niche 해시태그, 블로그 CTA 첫 줄)
  - 채널별 태그 분리 (youtube_tags 광범위, reels_tags niche)

v3.4 변경사항:
  - 릴스 썸네일 고정: 카드1 프레임을 Cloudinary 업로드 후 cover_url로 지정
  - create_shorts_video() 반환값 tuple(video_path, card1_frame) 로 변경
  - upload_to_instagram_reels() cover_url 파라미터 추가
  - post_youtube_shorts() 썸네일 업로드 로직 추가
"""

import os
import re
import json
import time
import base64
import logging
import tempfile
import subprocess
import hashlib
from pathlib import Path
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import anthropic

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY     = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY        = os.environ["GEMINI_API_KEY"]
GOOGLE_CREDENTIALS    = os.environ["GOOGLE_CREDENTIALS_JSON"]
GOOGLE_TTS_API_KEY    = os.environ["GOOGLE_TTS_API_KEY"]
INSTAGRAM_TOKEN       = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID  = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY    = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

END_CARD_LINE1 = "블로그에서 전체 보기"
END_CARD_LINE2 = "설명란 링크 ↓"
END_CARD_DURATION = 1.5

W, H = 1080, 1920
LOGO_PATH  = os.path.join(os.path.dirname(__file__), "logo.png")
LOGO_PATH2 = os.path.join(os.path.dirname(__file__), "logo2.png")


# ═════════════════════════════════════════════════════════════════════════════
# 폰트
# ═════════════════════════════════════════════════════════════════════════════
def get_font_path(bold: bool = False) -> str:
    import glob
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJKkr-Bold.otf" if bold else
        "/usr/share/fonts/truetype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Bold.otf" if bold else
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc" if bold else
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    patterns = ["*Bold*CJK*", "*CJK*Bold*"] if bold else ["*Regular*CJK*", "*CJK*.ttc"]
    for pattern in patterns:
        found = glob.glob(f"/usr/share/fonts/**/{pattern}", recursive=True)
        if found:
            return found[0]
    return None


def load_font(size: int, bold: bool = False):
    path = get_font_path(bold)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: 카드별 스크립트 + 이미지 프롬프트 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_card_scripts(title: str, content_html: str, blog_url: str, num_cards: int = 5) -> dict:
    log.info("📝 카드별 대사 + 이미지 프롬프트 생성 중...")

    text = re.sub(r'<[^>]+>', '', content_html)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text[:3000]

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2200,
        messages=[{
            "role": "user",
            "content": f"""아래 블로그를 유튜브 쇼츠/인스타 릴스용 카드 {num_cards}장으로 변환해줘.
2026년 기준 (2024/2025 언급 금지).

블로그 제목: {title}
블로그 본문:
{text}

블로그 URL: {blog_url}

## 5카드 구조 (절대 규칙)
- 카드 1 = 후크. 첫 1.5초가 전부. 아래 4가지 후크 공식 중 정확히 1개 선택.
  ① 충격 수치   예) 월 20달러가 갑자기 200달러로
  ② 반전 질문   예) 아직도 ChatGPT로 코딩하세요?
  ③ 직접 호명   예) AI 쓰는 직장인이라면 꼭 보세요
  ④ 비밀 폭로   예) 이거 모르면 4시간씩 낭비합니다
  → 인사말 절대 금지. 35~45자.
  → hook_keyword: 후크의 핵심 ≤8자. 큰 자막에 띄울 단어. 예) "200달러", "4시간 낭비", "꼭 보세요"
- 카드 2~4 = 본문. 블로그에서 가장 임팩트 있는 정보 3가지.
  - 구체 수치/실제 사례/실용 팁. "오 이거 몰랐다" 할 내용.
  - 단순 요약 금지. 55~65자.
- 카드 5 = 블로그 유입 CTA (가장 중요). 한 줄 요약 + 블로그 유도.
  - 반드시 "블로그", "설명란", "링크" 중 1개 이상 포함.
  - 예) "전체 가이드는 블로그에서 보세요. 설명란 링크예요"

## 작성 규칙
- 친근한 ~해요 ~거예요 말투. 문어체 금지.
- 한 문장에 정보 1개. 짧게 끊어서.
- 블로그에 명시된 수치만 사용. 창작 금지.
- 카드별 image_prompt: 영문 ≤50단어. 구체적이고 생생한 장면.

## 채널별 메타데이터
- youtube_title: ≤40자. 클릭 유발 형. **#Shorts 반드시 포함**.
- youtube_description: ≤150자. 후크 첫 줄 + 핵심 한 줄. (블로그 URL은 코드가 자동 추가)
- youtube_tags: 광범위 한국어 5개. 예) ["AI코딩", "바이브코딩", "Cursor", "Claude", "AI도구"]
- reels_caption: 300~450자. 첫 줄 = 후크 한 문장. 본문 3~5줄 핵심 요약(줄바꿈 활용). 마지막 줄 = "전체 가이드는 블로그에서 보세요 ↓ {blog_url}". **#Shorts 절대 금지**. 이모지 0개.
- reels_tags: niche 한국어 4~5개. **#Shorts 절대 금지**. 예) ["#AI개발자", "#바이브코딩스쿨", "#Cursor사용법", "#자동화코딩"]

## 출력 (JSON만, 코드블록 없이)
{{
  "cards": [
    {{"card": 1, "hook_type": "①|②|③|④", "hook_keyword": "≤8자", "title": "≤10자", "script": "후크 35~45자", "image_prompt": "vivid English ≤50 words"}},
    {{"card": 2, "title": "≤10자", "script": "55~65자", "image_prompt": "..."}},
    {{"card": 3, "title": "≤10자", "script": "55~65자", "image_prompt": "..."}},
    {{"card": 4, "title": "≤10자", "script": "55~65자", "image_prompt": "..."}},
    {{"card": 5, "title": "≤10자", "script": "55~65자 + 블로그/설명란/링크 포함", "image_prompt": "..."}}
  ],
  "youtube_title": "쇼츠 제목 ≤40자 #Shorts 포함",
  "youtube_description": "≤150자",
  "youtube_tags": ["광범위 태그 5개"],
  "reels_caption": "300~450자 본문",
  "reels_tags": ["#niche 4~5개"]
}}"""
        }]
    )

    raw = response.content[0].text.strip()
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("{"):
                raw = part
                break
    meta = json.loads(raw)
    meta["youtube_description"] = meta["youtube_description"] + f"\n\n🔗 {blog_url}"

    # 하위 호환: 구버전 응답에 신규 필드 없으면 합리적 기본값 채움
    if "youtube_tags" not in meta:
        meta["youtube_tags"] = meta.get("tags", ["AI코딩", "바이브코딩", "Cursor", "Claude", "Shorts"])
    if "reels_tags" not in meta:
        meta["reels_tags"] = ["#AI개발자", "#바이브코딩스쿨", "#Cursor사용법", "#자동화코딩"]
    if "reels_caption" not in meta:
        meta["reels_caption"] = (
            f"{title}\n\n"
            f"전체 가이드는 블로그에서 보세요 ↓\n{blog_url}"
        )

    log.info("  ✅ 카드별 스크립트 생성 완료")
    return meta


# ═════════════════════════════════════════════════════════════════════════════
# STEP 2: 카드별 Gemini 이미지 생성 (9:16 세로)
# ═════════════════════════════════════════════════════════════════════════════
def generate_card_image(image_prompt: str, card_num: int) -> bytes:
    log.info(f"  🎨 카드 {card_num} 이미지 생성 중...")

    enhanced = (
        f"{image_prompt}, "
        "9:16 vertical portrait, ultra high quality, "
        "modern tech illustration, vibrant colors, "
        "no text no letters, professional design"
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
            time.sleep(5)
            resp = requests.post(url, json=payload, timeout=90)
            resp.raise_for_status()
            data = resp.json()
            for part in data["candidates"][0]["content"]["parts"]:
                if "inlineData" in part:
                    img_bytes = base64.b64decode(part["inlineData"]["data"])
                    log.info(f"  ✅ 카드 {card_num} 이미지 생성 완료")
                    return img_bytes
        except Exception as e:
            wait = 20 * (attempt + 1)
            log.warning(f"  ⚠️ 이미지 생성 실패 (시도 {attempt+1}/3): {e}")
            time.sleep(wait)

    raise RuntimeError(f"카드 {card_num} 이미지 생성 3회 모두 실패")


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: 이미지 위에 텍스트 오버레이
# ═════════════════════════════════════════════════════════════════════════════
def make_card_frame(image_bytes: bytes, title: str, subtitle: str) -> bytes:
    bio = BytesIO(bytes(image_bytes))
    bio.seek(0)
    img = Image.open(bio)
    img.load()
    img = img.convert("RGB")
    img = img.resize((W, H), Image.LANCZOS)
    draw = ImageDraw.Draw(img)

    top_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    top_draw = ImageDraw.Draw(top_overlay)
    top_draw.rectangle([0, 0, W, 130], fill=(0, 0, 0, 160))
    img = Image.alpha_composite(img.convert("RGBA"), top_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    if os.path.exists(LOGO_PATH):
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo_h = 90
            ratio = logo_h / logo.height
            logo_w = int(logo.width * ratio)
            logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
            img.paste(logo, ((W - logo_w) // 2, 20), logo)
        except:
            font_brand = load_font(36, bold=True)
            draw = ImageDraw.Draw(img)
            draw.text((W//2, 65), "바이브코딩 스쿨", font=font_brand, fill=(255,255,255), anchor="mm")
    draw = ImageDraw.Draw(img)

    if title:
        font_title = load_font(90, bold=True)
        title_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        title_draw = ImageDraw.Draw(title_overlay)
        words = title.split()
        lines, current = [], ""
        for word in words:
            test = (current + " " + word).strip()
            bbox = title_draw.textbbox((0, 0), test, font=font_title)
            if bbox[2] > W - 80 and current:
                lines.append(current)
                current = word
            else:
                current = test
        if current:
            lines.append(current)
        line_h = 100
        box_h = len(lines) * line_h + 40
        box_y = H // 2 - box_h // 2
        title_draw.rectangle([40, box_y - 20, W - 40, box_y + box_h], fill=(0, 0, 0, 150))
        img = Image.alpha_composite(img.convert("RGBA"), title_overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        y = box_y + 10
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font_title)
            x = (W - (bbox[2] - bbox[0])) // 2
            for dx, dy in [(-3,-3),(3,-3),(-3,3),(3,3)]:
                draw.text((x+dx, y+dy), line, font=font_title, fill=(0,0,0))
            draw.text((x, y), line, font=font_title, fill=(255, 255, 255))
            y += line_h

    if subtitle:
        font_sub = load_font(60, bold=True)
        sub_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sub_draw = ImageDraw.Draw(sub_overlay)
        sub_draw.rectangle([0, H - 380, W, H], fill=(0, 0, 0, 215))
        img = Image.alpha_composite(img.convert("RGBA"), sub_overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        words = subtitle.split()
        lines, current = [], ""
        for word in words:
            test = (current + " " + word).strip()
            bbox = draw.textbbox((0, 0), test, font=font_sub)
            if bbox[2] > W - 60 and current:
                lines.append(current)
                current = word
            else:
                current = test
        if current:
            lines.append(current)
        y = H - 360
        for line in lines[:2]:
            bbox = draw.textbbox((0, 0), line, font=font_sub)
            x = (W - (bbox[2] - bbox[0])) // 2
            for dx, dy in [(-3,-3),(3,-3),(-3,3),(3,3)]:
                draw.text((x+dx, y+dy), line, font=font_sub, fill=(0,0,0))
            draw.text((x, y), line, font=font_sub, fill=(255, 230, 0))
            y += bbox[3] - bbox[1] + 12

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: 무음 블로그 유입 끝카드 (v4.0: 인트로 제거, 아웃로 나레이션 제거)
# ═════════════════════════════════════════════════════════════════════════════
def make_end_card_frame() -> bytes:
    """무음 1.5초로 끝에 붙는 블로그 CTA 카드. TTS 호출 0회."""
    img = Image.new("RGB", (W, H), color=(10, 10, 20))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(30 + (80 - 30) * t)
        g = int(0 + (20 - 0) * t)
        b = int(60 + (120 - 60) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # 로고 상단
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo_w = 500
            ratio = logo_w / logo.width
            logo_h = int(logo.height * ratio)
            logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
            img.paste(logo, ((W - logo_w) // 2, 280), logo)
        except Exception as e:
            log.warning(f"  ⚠️ 끝카드 로고 삽입 실패: {e}")

    # CTA 메인 카피 (큰 글씨, 노란색)
    font_main = load_font(120, bold=True)
    bbox = draw.textbbox((0, 0), END_CARD_LINE1, font=font_main)
    x = (W - (bbox[2] - bbox[0])) // 2
    y = H // 2 - 60
    for dx, dy in [(-4,-4),(4,-4),(-4,4),(4,4)]:
        draw.text((x+dx, y+dy), END_CARD_LINE1, font=font_main, fill=(0,0,0))
    draw.text((x, y), END_CARD_LINE1, font=font_main, fill=(255, 230, 0))

    # 서브 카피 (설명란 링크 안내)
    font_sub = load_font(72, bold=True)
    bbox = draw.textbbox((0, 0), END_CARD_LINE2, font=font_sub)
    x = (W - (bbox[2] - bbox[0])) // 2
    y = H // 2 + 120
    for dx, dy in [(-3,-3),(3,-3),(-3,3),(3,3)]:
        draw.text((x+dx, y+dy), END_CARD_LINE2, font=font_sub, fill=(0,0,0))
    draw.text((x, y), END_CARD_LINE2, font=font_sub, fill=(255, 255, 255))

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_silent_audio(duration: float, path: Path) -> Path:
    """TTS와 동일 포맷(24kHz mono LINEAR16)으로 무음 WAV 생성. concat 호환."""
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
        "-t", str(duration),
        "-c:a", "pcm_s16le",
        str(path),
    ], capture_output=True)
    return path


# ═════════════════════════════════════════════════════════════════════════════
# STEP 5: Google Cloud TTS 음성 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_voice(script: str) -> bytes:
    url = f"https://us-texttospeech.googleapis.com/v1beta1/text:synthesize?key={GOOGLE_TTS_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "input": {"text": script},
        "voice": {
            "languageCode": "ko-KR",
            "name": "ko-KR-Chirp3-HD-Charon",
        },
        "audioConfig": {
            "audioEncoding": "LINEAR16",
            "speakingRate": 1.18,
            "sampleRateHertz": 24000,
        },
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            audio_b64 = resp.json()["audioContent"]
            return base64.b64decode(audio_b64)
        except Exception as e:
            wait = 10 * (attempt + 1)
            log.warning(f"  ⚠️ TTS 실패 (시도 {attempt+1}/3): {e}")
            time.sleep(wait)
    raise RuntimeError("Google Cloud TTS 3회 모두 실패")


def save_voice_as_wav(audio_bytes: bytes, path: Path) -> Path:
    path.write_bytes(audio_bytes)
    return path


# ═════════════════════════════════════════════════════════════════════════════
# 음성 길이 측정
# ═════════════════════════════════════════════════════════════════════════════
def get_audio_duration(audio_path: Path) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(audio_path)
    ], capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except:
        return 5.0


def make_video_segment(img_path: Path, audio_path: Path, output_path: Path):
    duration = get_audio_duration(audio_path) + 0.3
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(img_path),
        "-i", str(audio_path),
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ], capture_output=True)
    log.info(f"    ⏱️ 영상 길이: {duration:.1f}초")


# ═════════════════════════════════════════════════════════════════════════════
# STEP 6: 전체 영상 합성 ✅ v3.4: card1_frame 같이 반환
# ═════════════════════════════════════════════════════════════════════════════
def create_shorts_video(card_scripts: list, title: str) -> tuple:
    """반환: (video_path: str, card1_frame: bytes)"""
    log.info("🎬 쇼츠 영상 합성 중...")

    card1_frame_bytes = None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        segments = []

        # v4.0: 인트로 로고/나레이션 제거. 첫 프레임 = 카드1 후크.

        for i, card_data in enumerate(card_scripts):
            log.info(f"  🎬 카드 {i+1} 세그먼트 생성 중...")
            image_bytes = generate_card_image(
                card_data.get("image_prompt", f"AI coding tech illustration card {i+1}"),
                i + 1
            )
            card_frame = make_card_frame(
                image_bytes,
                card_data.get("title", ""),
                card_data.get("script", "")
            )

            # ✅ 카드1 프레임 저장 → 릴스 썸네일용
            if i == 0:
                card1_frame_bytes = card_frame

            card_img_path = tmpdir / f"card_{i}.png"
            card_img_path.write_bytes(card_frame)
            card_audio_bytes = generate_voice(card_data.get("script", ""))
            card_audio_path = save_voice_as_wav(card_audio_bytes, tmpdir / f"card_{i}_audio.wav")
            card_video = tmpdir / f"card_{i}.mp4"
            make_video_segment(card_img_path, card_audio_path, card_video)
            segments.append(card_video)

        # v4.0: 아웃로 나레이션 제거. 무음 1.5초 블로그 CTA 끝카드로 교체 (TTS 1회 절감).
        log.info("  🎬 끝카드 생성 중 (무음 블로그 CTA)...")
        end_img_path = tmpdir / "end.png"
        end_img_path.write_bytes(make_end_card_frame())
        end_audio_path = make_silent_audio(END_CARD_DURATION, tmpdir / "end_audio.wav")
        end_video = tmpdir / "end.mp4"
        make_video_segment(end_img_path, end_audio_path, end_video)
        segments.append(end_video)

        log.info("  🔗 세그먼트 합치는 중...")
        concat_list = tmpdir / "concat.txt"
        with open(concat_list, "w") as f:
            for seg in segments:
                f.write(f"file '{seg}'\n")

        final_path = f"/tmp/shorts_{int(time.time())}.mp4"
        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            final_path
        ], capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat 실패: {result.stderr}")

        log.info(f"  ✅ 영상 합성 완료: {final_path}")
        return final_path, card1_frame_bytes  # ✅ tuple 반환


# ═════════════════════════════════════════════════════════════════════════════
# STEP 7-1: Cloudinary 영상 업로드
# ═════════════════════════════════════════════════════════════════════════════
def upload_video_to_cloudinary(video_path: str) -> str:
    log.info("☁️  Cloudinary 영상 업로드 중...")
    timestamp = str(int(time.time()))
    public_id = "vibe_school/reels_" + timestamp
    params_to_sign = "public_id=" + public_id + "&timestamp=" + timestamp
    signature = hashlib.sha1(
        (params_to_sign + CLOUDINARY_API_SECRET).encode("utf-8")
    ).hexdigest()
    with open(video_path, "rb") as f:
        resp = requests.post(
            "https://api.cloudinary.com/v1_1/" + CLOUDINARY_CLOUD_NAME + "/video/upload",
            data={
                "public_id": public_id,
                "timestamp": timestamp,
                "api_key": CLOUDINARY_API_KEY,
                "signature": signature,
            },
            files={"file": ("video.mp4", f, "video/mp4")},
            timeout=180,
        )
    resp.raise_for_status()
    url = resp.json().get("secure_url", "")
    log.info(f"  ✅ Cloudinary 영상 업로드 완료: {url[:60]}...")
    return url


# ═════════════════════════════════════════════════════════════════════════════
# STEP 7-2: 인스타그램 릴스 업로드 ✅ v3.4: cover_url 추가
# ═════════════════════════════════════════════════════════════════════════════
def upload_to_instagram_reels(video_url: str, title: str, blog_url: str,
                               cover_url: str = "",
                               reels_caption: str = "",
                               reels_tags: list = None) -> str:
    log.info("📱 인스타그램 릴스 업로드 중...")
    if not INSTAGRAM_TOKEN or not INSTAGRAM_ACCOUNT_ID:
        log.warning("  ⚠️ 인스타그램 토큰/계정 없음 → 릴스 스킵")
        return ""

    base = "https://graph.instagram.com/v25.0"

    # v4.0: 릴스 전용 캡션 + niche 해시태그. #Shorts 절대 금지 (IG 알고리즘 페널티).
    if reels_caption:
        body = reels_caption
    else:
        body = (
            title + "\n\n"
            "전체 가이드는 블로그에서 보세요 ↓\n" + blog_url
        )

    tags = reels_tags or ["#AI개발자", "#바이브코딩스쿨", "#Cursor사용법", "#자동화코딩"]
    # # 누락 방어
    tags = [t if t.startswith("#") else "#" + t for t in tags]
    # IG 정책상 #Shorts 등 무관 플랫폼 태그 자동 제거
    tags = [t for t in tags if t.lower() not in ("#shorts", "#youtubeshorts", "#youtube")]

    caption = body + "\n\n" + " ".join(tags)

    payload = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": True,
        "access_token": INSTAGRAM_TOKEN,
    }
    # ✅ 카드1 이미지를 썸네일로 고정
    if cover_url:
        payload["cover_url"] = cover_url
        log.info(f"  🖼️  릴스 썸네일 지정: {cover_url[:60]}...")

    for attempt in range(3):
        resp = requests.post(
            f"{base}/{INSTAGRAM_ACCOUNT_ID}/media",
            json=payload,
            timeout=30,
        )
        if resp.ok:
            break
        log.warning(f"  ⚠️ 릴스 컨테이너 생성 실패 (시도 {attempt+1}/3): {resp.text[:100]}")
        time.sleep(30)
    resp.raise_for_status()
    container_id = resp.json()["id"]

    log.info("  ⏳ 인스타 영상 처리 대기 중... (30초)")
    time.sleep(30)

    for attempt in range(3):
        resp = requests.post(
            f"{base}/{INSTAGRAM_ACCOUNT_ID}/media_publish",
            json={"creation_id": container_id, "access_token": INSTAGRAM_TOKEN},
            timeout=30,
        )
        if resp.ok:
            break
        time.sleep(30)
    resp.raise_for_status()

    post_id = resp.json()["id"]
    reels_url = f"https://www.instagram.com/reel/{post_id}/"
    log.info(f"  ✅ 인스타 릴스 완료: {reels_url}")
    return reels_url


# ═════════════════════════════════════════════════════════════════════════════
# STEP 7-3: 유튜브 업로드
# ═════════════════════════════════════════════════════════════════════════════
def upload_to_youtube(video_path: str, meta: dict) -> str:
    log.info("📤 유튜브 업로드 중...")
    import google.auth.transport.requests as google_requests
    creds_info = json.loads(GOOGLE_CREDENTIALS)
    creds = Credentials(
        token=creds_info["token"],
        refresh_token=creds_info["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_info["client_id"],
        client_secret=creds_info["client_secret"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    if not creds.valid:
        creds.refresh(google_requests.Request())
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    # v4.0: youtube_tags 우선, 없으면 구버전 tags 사용
    yt_tags = meta.get("youtube_tags") or meta.get("tags", [])
    # 중복 제거하며 광범위 태그 보강
    base_tags = ["바이브코딩", "Shorts", "AI코딩"]
    merged_tags = list(dict.fromkeys(yt_tags + base_tags))

    body = {
        "snippet": {
            "title": meta["youtube_title"],
            "description": meta["youtube_description"],
            "tags": merged_tags,
            "categoryId": "28",
            "defaultLanguage": "ko",
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True, chunksize=1024*1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info(f"  📊 업로드 진행률: {int(status.progress() * 100)}%")
    video_id = response["id"]
    youtube_url = f"https://www.youtube.com/shorts/{video_id}"
    log.info(f"  ✅ 유튜브 업로드 완료: {youtube_url}")
    os.remove(video_path)
    return youtube_url


# ═════════════════════════════════════════════════════════════════════════════
# 메인 함수 ✅ v3.4: 썸네일 Cloudinary 업로드 후 cover_url 전달
# ═════════════════════════════════════════════════════════════════════════════
def post_youtube_shorts(
    title: str,
    content_html: str,
    blog_url: str,
    card_image_urls: list = None,
) -> str:
    try:
        meta = generate_card_scripts(title, content_html, blog_url)
        card_scripts = meta.get("cards", [])

        # ✅ tuple 언패킹
        video_path, card1_frame = create_shorts_video(card_scripts, title)

        # ✅ 카드1 이미지 Cloudinary 업로드 → cover_url 획득
        cover_url = ""
        if card1_frame and CLOUDINARY_CLOUD_NAME:
            try:
                log.info("  🖼️  릴스 썸네일 업로드 중...")
                timestamp = str(int(time.time()))
                public_id = f"vibe_school/thumb_{timestamp}"
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
                    files={"file": ("thumb.png", card1_frame, "image/png")},
                    timeout=60,
                )
                resp.raise_for_status()
                cover_url = resp.json().get("secure_url", "")
                log.info(f"  ✅ 썸네일 업로드 완료: {cover_url[:60]}...")
            except Exception as e:
                log.warning(f"  ⚠️ 썸네일 업로드 실패 (릴스는 계속 진행): {e}")

        reels_url = ""
        try:
            video_public_url = upload_video_to_cloudinary(video_path)
            reels_url = upload_to_instagram_reels(
                video_public_url, title, blog_url,
                cover_url=cover_url,           # 카드1 썸네일
                reels_caption=meta.get("reels_caption", ""),  # v4.0 릴스 전용 캡션
                reels_tags=meta.get("reels_tags"),            # v4.0 niche 해시태그
            )
        except Exception as e:
            log.warning(f"  ⚠️ 인스타 릴스 실패: {e}")

        youtube_url = upload_to_youtube(video_path, meta)

        if reels_url:
            log.info(f"  📱 인스타 릴스: {reels_url}")
        return youtube_url

    except Exception as e:
        log.warning(f"  ⚠️ 유튜브 쇼츠 실패 (블로그는 정상): {e}")
        return ""
