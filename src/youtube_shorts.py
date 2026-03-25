"""
바이브코딩 스쿨 — YouTube Shorts 자동화 v2
─────────────────────────────────────────
구조:
  [인트로 3초] 로고 + 고정 인사말 음성
  [카드 롤링]  인스타 카드 5장 + 각 카드별 대사 + 하단 자막
  [아웃트로 2초] CTA

사이즈: 1080x1920 (9:16)
카드:   중앙에 1080x1080 배치
자막:   하단 자막 롤링
음성:   Gemini TTS - Charon
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
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS_JSON"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# 고정 인트로 대사
INTRO_SCRIPT = "안녕하세요, 바이브코딩스쿨입니다! 오늘도 좋은 정보 빠르게 가져왔으니 30초만 집중하세요!"
OUTRO_SCRIPT = "자세한 내용은 설명란 링크에서 확인하세요! 구독하고 매일 AI 최신 정보 받아보세요!"

W, H = 1080, 1920  # 쇼츠 사이즈
CARD_SIZE = 1080    # 카드 정방형 사이즈
LOGO_PATH  = os.path.join(os.path.dirname(__file__), "logo.png")   # 아웃트로용
LOGO_PATH2 = os.path.join(os.path.dirname(__file__), "logo2.png")  # 인트로용


# ═════════════════════════════════════════════════════════════════════════════
# 폰트
# ═════════════════════════════════════════════════════════════════════════════
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
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc" if bold else
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    # 폰트 못 찾으면 전체 검색
    import glob
    patterns = ["*Bold*CJK*", "*CJK*Bold*"] if bold else ["*Regular*CJK*", "*CJK*Regular*", "*CJK*.ttc"]
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
# STEP 1: 카드별 대사 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_card_scripts(title: str, content_html: str, blog_url: str, num_cards: int = 5) -> dict:
    log.info("📝 카드별 대사 생성 중...")

    text = re.sub(r'<[^>]+>', '', content_html)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text[:2000]

    cards_format = "\n".join([f'  {{"card": {i+1}, "script": "카드 {i+1} 대사"}}' for i in range(num_cards)])

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""유튜브 쇼츠용 카드별 나레이션을 만들어줘.

블로그 제목: {title}
내용: {text}

카드 {num_cards}장에 맞게 각 카드별 대사를 만들어줘.
- 카드 1: 훅 (궁금증 유발, 15자 이내)
- 카드 2~4: 핵심 내용 각 1가지 (30자 이내)
- 카드 5: 마무리 요약 (20자 이내)
- 친근한 말투 (~해요, ~거예요)
- 각 대사는 해당 카드에서 읽히는 시간 (2~3초) 분량

JSON만 출력 (코드블록 없이):
{{
  "card_scripts": [
{cards_format}
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
    log.info(f"  ✅ 카드별 대사 생성 완료")
    return meta


# ═════════════════════════════════════════════════════════════════════════════
# STEP 2: Gemini TTS 음성 생성
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
    """raw PCM → WAV 변환"""
    raw_path = path.parent / "voice.raw"
    raw_path.write_bytes(audio_bytes)

    wav_cmd = [
        "ffmpeg", "-y",
        "-f", "s16le", "-ar", "24000", "-ac", "1",
        "-i", str(raw_path),
        str(path)
    ]
    result = subprocess.run(wav_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("  ⚠️ WAV 변환 실패, raw 사용")
        return raw_path
    return path


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: 인트로 프레임 생성 (로고 + 배경)
# ═════════════════════════════════════════════════════════════════════════════
def make_intro_frame() -> bytes:
    """1080x1920 인트로 이미지 생성"""
    img = Image.new("RGB", (W, H), color=(10, 10, 20))
    draw = ImageDraw.Draw(img)

    # 배경 그라데이션
    for y in range(H):
        t = y / H
        r = int(30 + (80 - 30) * t)
        g = int(0 + (20 - 0) * t)
        b = int(60 + (120 - 60) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # 인트로 로고 (logo2.png)
    logo_file = LOGO_PATH2 if os.path.exists(LOGO_PATH2) else LOGO_PATH
    if os.path.exists(logo_file):
        try:
            logo = Image.open(logo_file).convert("RGBA")
            logo_w = 800
            ratio = logo_w / logo.width
            logo_h = int(logo.height * ratio)
            logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
            x = (W - logo_w) // 2
            y = (H - logo_h) // 2 - 80
            img.paste(logo, (x, y), logo)
        except Exception as e:
            log.warning(f"  ⚠️ 로고 삽입 실패: {e}")

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3-2: 아웃트로 프레임 생성 (logo.png 사용)
# ═════════════════════════════════════════════════════════════════════════════
def make_outro_frame() -> bytes:
    """1080x1920 아웃트로 이미지 생성 - logo.png 사용"""
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
            x = (W - logo_w) // 2
            y = (H - logo_h) // 2 - 100
            img.paste(logo, (x, y), logo)
        except Exception as e:
            log.warning(f"  ⚠️ 아웃트로 로고 삽입 실패: {e}")

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: 카드 프레임 생성 (1080x1920 - 카드 중앙 + 하단 자막 영역)
# ═════════════════════════════════════════════════════════════════════════════
def make_card_frame(card_image_bytes: bytes, subtitle: str) -> bytes:
    """카드 이미지를 1080x1920 프레임에 배치 + 상단 로고 + 하단 자막"""

    # 배경 (짙은 다크)
    frame = Image.new("RGB", (W, H), color=(8, 8, 16))
    draw = ImageDraw.Draw(frame)

    # 상단 영역 높이
    TOP_H = 160
    # 카드 영역
    CARD_Y = TOP_H
    # 하단 자막 영역
    SUBTITLE_H = 220

    # 상단 바 (반투명 보라)
    top_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    top_draw = ImageDraw.Draw(top_overlay)
    top_draw.rectangle([0, 0, W, TOP_H], fill=(108, 58, 237, 220))
    frame = Image.alpha_composite(frame.convert("RGBA"), top_overlay).convert("RGB")
    draw = ImageDraw.Draw(frame)

    # 상단 로고 (작게)
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo_h = 100
            ratio = logo_h / logo.height
            logo_w = int(logo.width * ratio)
            logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
            lx = (W - logo_w) // 2
            ly = (TOP_H - logo_h) // 2
            frame.paste(logo, (lx, ly), logo)
        except Exception as e:
            # 로고 없으면 텍스트로
            font_brand = load_font(48, bold=True)
            draw.text((W//2, TOP_H//2), "바이브코딩 스쿨", font=font_brand, fill=(255,255,255), anchor="mm")

    draw = ImageDraw.Draw(frame)

    # 카드 이미지 (중앙)
    card_area_h = H - TOP_H - SUBTITLE_H
    try:
        bio = BytesIO(bytes(card_image_bytes))
        bio.seek(0)
        card = Image.open(bio)
        card.load()
        card = card.convert("RGB")
        # 카드 영역에 맞게 리사이즈
        card_size = min(W, card_area_h)
        card = card.resize((card_size, card_size), Image.LANCZOS)
        cx = (W - card_size) // 2
        cy = CARD_Y + (card_area_h - card_size) // 2
        frame.paste(card, (cx, cy))
    except Exception as e:
        log.warning(f"  ⚠️ 카드 이미지 삽입 실패: {e}")

    # 하단 자막 영역
    subtitle_bg_y = H - SUBTITLE_H
    sub_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sub_draw = ImageDraw.Draw(sub_overlay)
    sub_draw.rectangle([0, subtitle_bg_y, W, H], fill=(0, 0, 0, 200))
    frame = Image.alpha_composite(frame.convert("RGBA"), sub_overlay).convert("RGB")
    draw = ImageDraw.Draw(frame)

    # 자막 텍스트
    font = load_font(50, bold=True)
    max_width = W - 80
    words = subtitle.split()
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

    # 자막 중앙 정렬
    total_h = sum([draw.textbbox((0,0), l, font=font)[3] + 10 for l in lines[:3]])
    y = subtitle_bg_y + (SUBTITLE_H - total_h) // 2
    for line in lines[:3]:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        for dx, dy in [(-2,-2),(2,-2),(-2,2),(2,2)]:
            draw.text((x+dx, y+dy), line, font=font, fill=(0,0,0))
        draw.text((x, y), line, font=font, fill=(255, 255, 0))  # 노란색 자막
        y += bbox[3] - bbox[1] + 10

    buf = BytesIO()
    frame.save(buf, format="PNG")
    return buf.getvalue()


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
    """이미지 + 음성 → 영상 (음성 길이에 정확히 맞춤)"""
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
# STEP 5: 전체 영상 합성
# ═════════════════════════════════════════════════════════════════════════════
def create_shorts_video(
    card_image_urls: list,
    card_scripts: list,
    title: str
) -> str:
    log.info("🎬 쇼츠 영상 합성 중...")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        segments = []  # (video_path, audio_path) 리스트

        # ── 인트로 세그먼트 ──
        log.info("  🎬 인트로 생성 중...")
        intro_img_bytes = make_intro_frame()
        intro_img_path = tmpdir / "intro.png"
        intro_img_path.write_bytes(intro_img_bytes)

        intro_audio_bytes = generate_voice(INTRO_SCRIPT)
        intro_audio_path = save_voice_as_wav(intro_audio_bytes, tmpdir / "intro_audio.wav")

        intro_video = tmpdir / "intro.mp4"
        make_video_segment(intro_img_path, intro_audio_path, intro_video)
        segments.append(intro_video)

        # ── 카드 세그먼트들 ──
        for i, (card_url, script_data) in enumerate(zip(card_image_urls, card_scripts)):
            log.info(f"  🎬 카드 {i+1} 세그먼트 생성 중...")

            # 카드 이미지 다운로드
            card_resp = requests.get(card_url, timeout=30, headers={"Accept": "image/png,image/*"})
            bio = BytesIO(card_resp.content)
            bio.seek(0)
            card_frame_bytes = make_card_frame(bio.read(), script_data.get("script", ""))

            card_img_path = tmpdir / f"card_{i}.png"
            card_img_path.write_bytes(card_frame_bytes)

            # 카드 음성
            card_audio_bytes = generate_voice(script_data.get("script", ""))
            card_audio_path = save_voice_as_wav(card_audio_bytes, tmpdir / f"card_{i}_audio.wav")

            card_video = tmpdir / f"card_{i}.mp4"
            make_video_segment(card_img_path, card_audio_path, card_video)
            segments.append(card_video)

        # ── 아웃트로 세그먼트 ──
        log.info("  🎬 아웃트로 생성 중...")
        outro_img_bytes = make_outro_frame()
        outro_img_path = tmpdir / "outro.png"
        outro_img_path.write_bytes(outro_img_bytes)

        outro_audio_bytes = generate_voice(OUTRO_SCRIPT)
        outro_audio_path = save_voice_as_wav(outro_audio_bytes, tmpdir / "outro_audio.wav")

        outro_video = tmpdir / "outro.mp4"
        make_video_segment(outro_img_path, outro_audio_path, outro_video)
        segments.append(outro_video)

        # ── 세그먼트 합치기 ──
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
# STEP 6: 유튜브 업로드
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

    # 토큰 만료 시 자동 갱신
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
    card_image_urls: list = None
) -> str:
    try:
        # 카드 이미지 없으면 스킵
        if not card_image_urls:
            log.warning("  ⚠️ 카드 이미지 없음 → 유튜브 쇼츠 스킵")
            return ""

        # 1. 카드별 대사 생성
        meta = generate_card_scripts(title, content_html, blog_url, len(card_image_urls))
        card_scripts = meta.get("card_scripts", [])

        # 카드 수 맞추기
        while len(card_scripts) < len(card_image_urls):
            card_scripts.append({"card": len(card_scripts)+1, "script": "확인해보세요!"})

        # 2. 영상 합성
        video_path = create_shorts_video(card_image_urls, card_scripts, title)

        # 3. 유튜브 업로드
        youtube_url = upload_to_youtube(video_path, meta)

        return youtube_url

    except Exception as e:
        log.warning(f"  ⚠️ 유튜브 쇼츠 실패 (블로그는 정상): {e}")
        return ""
