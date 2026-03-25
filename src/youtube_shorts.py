"""
바이브코딩 스쿨 — YouTube Shorts 자동화 v3
─────────────────────────────────────────
구조:
  [인트로]  logo2.png + 인사말 음성
  [카드 5장] 카드별 Gemini 이미지 + 텍스트 오버레이 + 음성
  [아웃트로] logo.png + CTA 음성

이미지: 카드별 주제에 맞는 Gemini 생성 이미지 (9:16)
자막: 이미지 위 텍스트 오버레이
음성: Gemini TTS - Charon
"""

import os
import re
import json
import time
import base64
import logging
import tempfile
import subprocess
import shutil
from pathlib import Path
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import anthropic

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
GOOGLE_CREDENTIALS    = os.environ["GOOGLE_CREDENTIALS_JSON"]
INSTAGRAM_TOKEN       = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID  = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY    = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

INTRO_SCRIPT = "안녕하세요, 바이브코딩스쿨입니다! 오늘도 좋은 정보 빠르게 가져왔으니 30초만 집중하세요!"
OUTRO_SCRIPT = "자세한 내용은 설명란 링크에서 확인하세요! 구독하고 매일 AI 최신 정보 받아보세요!"

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
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"""아래 블로그 글을 유튜브 쇼츠용 카드 {num_cards}장으로 만들어줘.

블로그 제목: {title}
블로그 본문:
{text}

## 카드 구성 원칙
- 카드 1: 강한 훅 — 숫자/통계/반전으로 첫 3초 집중시키기
  예) "기업 63%가 이미 AI 코딩 도구 쓰고 있어요"
- 카드 2~4: 블로그 핵심 내용에서 가장 임팩트 있는 정보 3가지
  - 구체적인 수치, 실제 사례, 실용적인 팁 위주로
  - 단순 요약 금지, 독자가 "오 이거 몰랐다" 할 내용으로
- 카드 5: 핵심 요약 한 줄 + 블로그 유도

## 나레이션 원칙
- 각 카드 나레이션은 3~4초 분량 (50~70자)
- 친근하고 빠릿한 말투 (~해요, ~거예요)
- 정보가 구체적이고 실용적이어야 함
- 단순히 "중요해요" 같은 말 금지

## 이미지 프롬프트 원칙
- 각 카드 내용을 시각적으로 표현하는 장면
- 구체적이고 생생한 묘사 (추상적 금지)
- 영문 50단어 이내

JSON만 출력 (코드블록 없이):
{{
  "cards": [
    {{
      "card": 1,
      "title": "제목 10자 이내",
      "script": "구체적이고 임팩트 있는 나레이션 50~70자",
      "image_prompt": "specific vivid English image prompt"
    }}
  ],
  "youtube_title": "쇼츠 제목 40자 이내 #Shorts 포함",
  "youtube_description": "설명 150자 이내",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"]
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
    """Gemini 이미지 위에 제목 + 자막 오버레이"""

    # 이미지 로드 및 1080x1920으로 리사이즈
    bio = BytesIO(bytes(image_bytes))
    bio.seek(0)
    img = Image.open(bio)
    img.load()
    img = img.convert("RGB")
    img = img.resize((W, H), Image.LANCZOS)
    draw = ImageDraw.Draw(img)

    # ── 상단 로고 바 ──
    top_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    top_draw = ImageDraw.Draw(top_overlay)
    top_draw.rectangle([0, 0, W, 130], fill=(0, 0, 0, 160))
    img = Image.alpha_composite(img.convert("RGBA"), top_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # 로고 (상단 작게)
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
            draw.text((W//2, 65), "바이브코딩 스쿨", font=font_brand, fill=(255,255,255), anchor="mm")
    draw = ImageDraw.Draw(img)

    # ── 중앙 제목 (큰 텍스트) ──
    if title:
        font_title = load_font(90, bold=True)
        # 반투명 배경
        title_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        title_draw = ImageDraw.Draw(title_overlay)

        # 제목 줄바꿈
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

        # 제목 배경 박스
        line_h = 100
        box_h = len(lines) * line_h + 40
        box_y = H // 2 - box_h // 2
        title_draw.rectangle([40, box_y - 20, W - 40, box_y + box_h], fill=(0, 0, 0, 150))
        img = Image.alpha_composite(img.convert("RGBA"), title_overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        # 제목 텍스트
        y = box_y + 10
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font_title)
            x = (W - (bbox[2] - bbox[0])) // 2
            # 외곽선
            for dx, dy in [(-3,-3),(3,-3),(-3,3),(3,3)]:
                draw.text((x+dx, y+dy), line, font=font_title, fill=(0,0,0))
            draw.text((x, y), line, font=font_title, fill=(255, 255, 255))
            y += line_h

    # ── 하단 자막 ──
    if subtitle:
        font_sub = load_font(48, bold=True)

        # 하단 반투명 배경
        sub_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sub_draw = ImageDraw.Draw(sub_overlay)
        sub_draw.rectangle([0, H - 340, W, H], fill=(0, 0, 0, 200))
        img = Image.alpha_composite(img.convert("RGBA"), sub_overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        # 자막 줄바꿈
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

        # 자막 그리기 (노란색)
        y = H - 320
        for line in lines[:2]:
            bbox = draw.textbbox((0, 0), line, font=font_sub)
            x = (W - (bbox[2] - bbox[0])) // 2
            for dx, dy in [(-2,-2),(2,-2),(-2,2),(2,2)]:
                draw.text((x+dx, y+dy), line, font=font_sub, fill=(0,0,0))
            draw.text((x, y), line, font=font_sub, fill=(255, 230, 0))
            y += bbox[3] - bbox[1] + 8

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: 인트로/아웃트로 프레임 생성
# ═════════════════════════════════════════════════════════════════════════════
def make_intro_frame() -> bytes:
    """logo2.png 사용 인트로"""
    img = Image.new("RGB", (W, H), color=(10, 10, 20))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(30 + (80 - 30) * t)
        g = int(0 + (20 - 0) * t)
        b = int(60 + (120 - 60) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    logo_file = LOGO_PATH2 if os.path.exists(LOGO_PATH2) else LOGO_PATH
    if os.path.exists(logo_file):
        try:
            logo = Image.open(logo_file).convert("RGBA")
            logo_w = 800
            ratio = logo_w / logo.width
            logo_h = int(logo.height * ratio)
            logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
            img.paste(logo, ((W - logo_w) // 2, (H - logo_h) // 2 - 80), logo)
        except Exception as e:
            log.warning(f"  ⚠️ 인트로 로고 삽입 실패: {e}")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_outro_frame() -> bytes:
    """logo.png 사용 아웃트로"""
    img = Image.new("RGB", (W, H), color=(10, 10, 20))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(30 + (80 - 30) * t)
        g = int(0 + (20 - 0) * t)
        b = int(60 + (120 - 60) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo_w = 700
            ratio = logo_w / logo.width
            logo_h = int(logo.height * ratio)
            logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
            img.paste(logo, ((W - logo_w) // 2, (H - logo_h) // 2 - 100), logo)
        except Exception as e:
            log.warning(f"  ⚠️ 아웃트로 로고 삽입 실패: {e}")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════════════════
# STEP 5: Gemini TTS 음성 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_voice(script: str) -> bytes:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash-preview-tts:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": script}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": "Charon"}
                }
            }
        }
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            audio_b64 = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            return base64.b64decode(audio_b64)
        except Exception as e:
            wait = 30 * (attempt + 1)
            log.warning(f"  ⚠️ 음성 생성 실패 (시도 {attempt+1}/3): {e}")
            time.sleep(wait)
    raise RuntimeError("음성 생성 3회 모두 실패")


def save_voice_as_wav(audio_bytes: bytes, path: Path) -> Path:
    raw_path = path.parent / (path.stem + ".raw")
    raw_path.write_bytes(audio_bytes)
    wav_cmd = ["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
               "-i", str(raw_path), str(path)]
    result = subprocess.run(wav_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return raw_path
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
    """이미지 + 음성 → 영상 (음성 길이에 맞춤)"""
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
# STEP 6: 전체 영상 합성
# ═════════════════════════════════════════════════════════════════════════════
def create_shorts_video(card_scripts: list, title: str) -> str:
    log.info("🎬 쇼츠 영상 합성 중...")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        segments = []

        # ── 인트로 ──
        log.info("  🎬 인트로 생성 중...")
        intro_img_path = tmpdir / "intro.png"
        intro_img_path.write_bytes(make_intro_frame())
        intro_audio_path = save_voice_as_wav(
            generate_voice(INTRO_SCRIPT), tmpdir / "intro_audio.wav"
        )
        intro_video = tmpdir / "intro.mp4"
        make_video_segment(intro_img_path, intro_audio_path, intro_video)
        segments.append(intro_video)

        # ── 카드 5장 ──
        for i, card_data in enumerate(card_scripts):
            log.info(f"  🎬 카드 {i+1} 세그먼트 생성 중...")

            # Gemini 이미지 생성
            image_bytes = generate_card_image(
                card_data.get("image_prompt", f"AI coding tech illustration card {i+1}"),
                i + 1
            )

            # 텍스트 오버레이
            card_frame = make_card_frame(
                image_bytes,
                card_data.get("title", ""),
                card_data.get("script", "")
            )

            card_img_path = tmpdir / f"card_{i}.png"
            card_img_path.write_bytes(card_frame)

            # 음성
            card_audio_path = save_voice_as_wav(
                generate_voice(card_data.get("script", "")),
                tmpdir / f"card_{i}_audio.wav"
            )

            card_video = tmpdir / f"card_{i}.mp4"
            make_video_segment(card_img_path, card_audio_path, card_video)
            segments.append(card_video)

        # ── 아웃트로 ──
        log.info("  🎬 아웃트로 생성 중...")
        outro_img_path = tmpdir / "outro.png"
        outro_img_path.write_bytes(make_outro_frame())
        outro_audio_path = save_voice_as_wav(
            generate_voice(OUTRO_SCRIPT), tmpdir / "outro_audio.wav"
        )
        outro_video = tmpdir / "outro.mp4"
        make_video_segment(outro_img_path, outro_audio_path, outro_video)
        segments.append(outro_video)

        # ── 합치기 ──
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
        return final_path


# ═════════════════════════════════════════════════════════════════════════════
# STEP 7-1: Cloudinary에 영상 업로드 (인스타 릴스용 공개 URL 필요)
# ═════════════════════════════════════════════════════════════════════════════
def upload_video_to_cloudinary(video_path: str) -> str:
    log.info("☁️  Cloudinary 영상 업로드 중...")
    import hashlib

    timestamp = str(int(time.time()))
    public_id = f"vibe_school/reels_{timestamp}"
    params_to_sign = f"public_id={public_id}&resource_type=video&timestamp={timestamp}"
    signature = hashlib.sha1(
        (params_to_sign + CLOUDINARY_API_SECRET).encode()
    ).hexdigest()

    with open(video_path, "rb") as f:
        resp = requests.post(
            f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/video/upload",
            data={
                "public_id": public_id,
                "timestamp": timestamp,
                "api_key": CLOUDINARY_API_KEY,
                "signature": signature,
                "resource_type": "video",
            },
            files={"file": f},
            timeout=120,
        )

    resp.raise_for_status()
    url = resp.json().get("secure_url", "")
    log.info(f"  ✅ Cloudinary 영상 업로드 완료: {url[:60]}...")
    return url


# ═════════════════════════════════════════════════════════════════════════════
# STEP 7-2: 인스타그램 릴스 업로드
# ═════════════════════════════════════════════════════════════════════════════
def upload_to_instagram_reels(video_url: str, title: str, blog_url: str) -> str:
    log.info("📱 인스타그램 릴스 업로드 중...")

    if not INSTAGRAM_TOKEN or not INSTAGRAM_ACCOUNT_ID:
        log.warning("  ⚠️ 인스타그램 토큰/계정 없음 → 릴스 스킵")
        return ""

    base = "https://graph.instagram.com/v25.0"
    caption = title + "\n\n블로그에서 더 보기: " + blog_url + "\n\n#바이브코딩 #AI코딩 #Shorts #바이브코딩스쿨"

    # 1. 미디어 컨테이너 생성
    for attempt in range(3):
        resp = requests.post(
            f"{base}/{INSTAGRAM_ACCOUNT_ID}/media",
            json={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": True,
                "access_token": INSTAGRAM_TOKEN,
            },
            timeout=30,
        )
        if resp.ok:
            break
        log.warning(f"  ⚠️ 릴스 컨테이너 생성 실패 (시도 {attempt+1}/3): {resp.text[:100]}")
        time.sleep(30)
    resp.raise_for_status()
    container_id = resp.json()["id"]
    log.info(f"  📦 릴스 컨테이너 생성 완료: {container_id}")

    # 2. 처리 대기 (인스타가 영상 처리하는 시간)
    log.info("  ⏳ 인스타 영상 처리 대기 중... (30초)")
    time.sleep(30)

    # 3. 게시
    for attempt in range(3):
        resp = requests.post(
            f"{base}/{INSTAGRAM_ACCOUNT_ID}/media_publish",
            json={
                "creation_id": container_id,
                "access_token": INSTAGRAM_TOKEN,
            },
            timeout=30,
        )
        if resp.ok:
            break
        log.warning(f"  ⚠️ 릴스 게시 실패 (시도 {attempt+1}/3): {resp.text[:100]}")
        time.sleep(30)
    resp.raise_for_status()

    post_id = resp.json()["id"]
    reels_url = f"https://www.instagram.com/reel/{post_id}/"
    log.info(f"  ✅ 인스타 릴스 업로드 완료: {reels_url}")
    return reels_url


# ═════════════════════════════════════════════════════════════════════════════
# STEP 7: 유튜브 업로드
# ═════════════════════════════════════════════════════════════════════════════
def upload_to_youtube(video_path: str, meta: dict) -> str:
    log.info("📤 유튜브 업로드 중...")

    import google.auth.transport.requests as google_requests
    from google.oauth2.credentials import Credentials as OAuth2Credentials

    creds_info = json.loads(GOOGLE_CREDENTIALS)
    creds = OAuth2Credentials(
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

    body = {
        "snippet": {
            "title": meta["youtube_title"],
            "description": meta["youtube_description"],
            "tags": meta.get("tags", []) + ["바이브코딩", "Shorts", "AI코딩"],
            "categoryId": "28",
            "defaultLanguage": "ko",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        }
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
# 메인 함수 — main.py에서 호출
# ═════════════════════════════════════════════════════════════════════════════
def post_youtube_shorts(
    title: str,
    content_html: str,
    blog_url: str,
    card_image_urls: list = None  # 더 이상 사용 안 함 (Gemini로 자체 생성)
) -> str:
    try:
        # 1. 카드별 스크립트 + 이미지 프롬프트 생성
        meta = generate_card_scripts(title, content_html, blog_url)
        card_scripts = meta.get("cards", [])

        # 2. 영상 합성
        video_path = create_shorts_video(card_scripts, title)

        # 3. Cloudinary 업로드 (인스타 릴스용)
        reels_url = ""
        try:
            video_public_url = upload_video_to_cloudinary(video_path)

            # 4. 인스타 릴스 업로드
            reels_url = upload_to_instagram_reels(video_public_url, title, blog_url)
        except Exception as e:
            log.warning(f"  ⚠️ 인스타 릴스 실패 (유튜브는 정상): {e}")

        # 5. 유튜브 업로드
        youtube_url = upload_to_youtube(video_path, meta)

        if reels_url:
            log.info(f"  📱 인스타 릴스: {reels_url}")

        return youtube_url

    except Exception as e:
        log.warning(f"  ⚠️ 유튜브 쇼츠 실패 (블로그는 정상): {e}")
        return ""
