"""
바이브코딩 스쿨 — YouTube Shorts 자동화
─────────────────────────────────────────
블로그 글 발행 후 자동으로:
  1. 쇼츠 스크립트 생성 (Claude)
  2. 쇼츠용 9:16 이미지 생성 (Gemini Image)
  3. 음성 생성 (Gemini TTS - Charon 시원한 남성)
  4. 이미지 + 음성 합쳐서 영상 제작 (ffmpeg)
  5. 유튜브 자동 업로드 (YouTube Data API)
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

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import anthropic

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS_JSON"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: 쇼츠 스크립트 + 메타데이터 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_shorts_script(title: str, content_html: str, blog_url: str) -> dict:
    log.info("📝 쇼츠 스크립트 생성 중...")

    text = re.sub(r'<[^>]+>', '', content_html)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text[:2000]

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": f"""아래 블로그 글을 유튜브 쇼츠용 나레이션 스크립트로 만들어줘.

블로그 제목: {title}
블로그 내용 요약: {text}
블로그 링크: {blog_url}

조건:
- 총 45~55초 분량 (약 200~250자)
- 훅(3초) → 핵심 내용(35초) → CTA(10초) 구조
- 친근하고 자연스러운 말투 ("~해요", "~거예요")
- 마지막에 반드시 "자세한 내용은 설명란 링크에서 확인하세요!" 포함
- 나레이션 텍스트만 출력 (지문/설명 없이)

나레이션:"""
        }]
    )

    script = response.content[0].text.strip()
    log.info(f"  ✅ 스크립트 생성 완료 ({len(script)}자)")

    meta_response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": f"""유튜브 쇼츠용 메타데이터를 만들어줘.

블로그 제목: {title}

JSON만 출력 (코드블록 없이):
{{
  "youtube_title": "쇼츠 제목 (40자 이내, #Shorts 포함)",
  "youtube_description": "설명 (150자 이내)",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"]
}}"""
        }]
    )

    raw = meta_response.content[0].text.strip()
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("{"):
                raw = part
                break
    meta = json.loads(raw)
    meta["script"] = script
    meta["youtube_description"] = meta["youtube_description"] + f"\n\n🔗 {blog_url}"

    return meta


# ═════════════════════════════════════════════════════════════════════════════
# STEP 2: 쇼츠용 9:16 세로 이미지 생성 (Gemini)
# ═════════════════════════════════════════════════════════════════════════════
def generate_shorts_image(title: str) -> bytes:
    log.info("🖼️  쇼츠용 세로 이미지 생성 중... (9:16)")

    prompt = (
        f"YouTube Shorts vertical thumbnail for: {title}. "
        "Modern flat illustration, vibrant colors, 9:16 vertical portrait format, "
        "no text no letters, professional tech design, bright friendly, "
        "AI coding technology theme"
    )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash-image:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=90)
            resp.raise_for_status()
            data = resp.json()
            for part in data["candidates"][0]["content"]["parts"]:
                if "inlineData" in part:
                    img_bytes = base64.b64decode(part["inlineData"]["data"])
                    log.info(f"  ✅ 쇼츠 이미지 생성 완료 ({len(img_bytes)} bytes)")
                    return img_bytes
        except Exception as e:
            wait = 30 * (attempt + 1)
            log.warning(f"  ⚠️ 이미지 생성 실패 (시도 {attempt+1}/3): {e}")
            time.sleep(wait)

    raise RuntimeError("쇼츠 이미지 생성 3회 모두 실패")


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: Gemini TTS로 음성 생성 (Charon - 시원하고 카리스마 있는 남성)
# ═════════════════════════════════════════════════════════════════════════════
def generate_voice(script: str) -> bytes:
    log.info("🎙️  음성 생성 중... (Gemini TTS - Charon)")

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
                    "prebuiltVoiceConfig": {
                        "voiceName": "Charon"
                    }
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
            audio_bytes = base64.b64decode(audio_b64)
            log.info(f"  ✅ 음성 생성 완료 ({len(audio_bytes)} bytes)")
            return audio_bytes
        except Exception as e:
            wait = 30 * (attempt + 1)
            log.warning(f"  ⚠️ 음성 생성 실패 (시도 {attempt+1}/3): {e}")
            time.sleep(wait)

    raise RuntimeError("음성 생성 3회 모두 실패")


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: 이미지 + 음성 → 쇼츠 영상 합성 (ffmpeg)
# ═════════════════════════════════════════════════════════════════════════════
def create_shorts_video(image_bytes: bytes, audio_bytes: bytes) -> str:
    log.info("🎬 쇼츠 영상 합성 중... (ffmpeg)")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # 이미지 저장
        img_path = tmpdir / "thumbnail.jpg"
        img_path.write_bytes(image_bytes)

        # 음성 저장 (Gemini TTS → LINEAR16 PCM)
        audio_raw_path = tmpdir / "voice.raw"
        audio_raw_path.write_bytes(audio_bytes)

        # raw PCM → WAV 변환
        audio_path = tmpdir / "voice.wav"
        wav_cmd = [
            "ffmpeg", "-y",
            "-f", "s16le",
            "-ar", "24000",
            "-ac", "1",
            "-i", str(audio_raw_path),
            str(audio_path)
        ]
        wav_result = subprocess.run(wav_cmd, capture_output=True, text=True)
        if wav_result.returncode != 0:
            audio_path = audio_raw_path
            log.warning("  ⚠️ WAV 변환 실패, 원본 사용")

        # 출력 영상
        output_path = tmpdir / "shorts.mp4"

        # ffmpeg — 9:16 이미지 + 음성 합치기
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(img_path),
            "-i", str(audio_path),
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "192k",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            "-shortest",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 실패: {result.stderr}")

        final_path = f"/tmp/shorts_{int(time.time())}.mp4"
        shutil.copy(str(output_path), final_path)

        log.info(f"  ✅ 영상 합성 완료: {final_path}")
        return final_path


# ═════════════════════════════════════════════════════════════════════════════
# STEP 5: 유튜브 업로드
# ═════════════════════════════════════════════════════════════════════════════
def upload_to_youtube(video_path: str, shorts_meta: dict) -> str:
    log.info("📤 유튜브 업로드 중...")

    creds_info = json.loads(GOOGLE_CREDENTIALS)
    creds = Credentials(
        token=creds_info["token"],
        refresh_token=creds_info["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_info["client_id"],
        client_secret=creds_info["client_secret"],
    )

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": shorts_meta["youtube_title"],
            "description": shorts_meta["youtube_description"],
            "tags": shorts_meta.get("tags", []) + ["바이브코딩", "Shorts", "AI코딩"],
            "categoryId": "28",
            "defaultLanguage": "ko",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        }
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

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
def post_youtube_shorts(title: str, content_html: str, blog_url: str, card_image_urls: list = None) -> str:
    """
    블로그 포스팅 완료 후 호출.
    title           : 블로그 제목
    content_html    : 블로그 본문 HTML
    blog_url        : 블로그 포스트 URL
    card_image_urls : 인스타 카드 이미지 URL 리스트 (없으면 자체 생성)
    """
    try:
        # 1. 스크립트 + 메타데이터 생성
        shorts_meta = generate_shorts_script(title, content_html, blog_url)

        # 2. 이미지 준비 (인스타 카드 있으면 재활용, 없으면 자체 생성)
        if card_image_urls:
            log.info("🖼️  인스타 카드 이미지 재활용 중...")
            img_resp = requests.get(card_image_urls[0], timeout=30)
            image_bytes = img_resp.content
            log.info(f"  ✅ 카드 이미지 로드 완료 ({len(image_bytes)} bytes)")
        else:
            log.info("🖼️  인스타 카드 없음 → 자체 이미지 생성")
            image_bytes = generate_shorts_image(title)

        # 3. 음성 생성 (Charon)
        audio_bytes = generate_voice(shorts_meta["script"])

        # 4. 영상 합성
        video_path = create_shorts_video(image_bytes, audio_bytes)

        # 5. 유튜브 업로드
        youtube_url = upload_to_youtube(video_path, shorts_meta)

        return youtube_url

    except Exception as e:
        log.warning(f"  ⚠️ 유튜브 쇼츠 실패 (블로그는 정상): {e}")
        return ""
