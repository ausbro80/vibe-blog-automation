"""
바이브코딩 스쿨 — YouTube Shorts 자동화
─────────────────────────────────────────
블로그 글 발행 후 자동으로:
  1. 쇼츠 스크립트 생성 (Claude)
  2. 음성 생성 (Gemini TTS - Orus 남성)
  3. 썸네일 이미지 + 음성 합쳐서 영상 제작 (ffmpeg)
  4. 유튜브 자동 업로드 (YouTube Data API)
"""

import os
import json
import time
import base64
import logging
import tempfile
import subprocess
from pathlib import Path

import anthropic
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS_JSON"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: 쇼츠 스크립트 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_shorts_script(title: str, content_html: str, blog_url: str) -> dict:
    log.info("📝 쇼츠 스크립트 생성 중...")

    # HTML 태그 제거해서 텍스트만 추출
    import re
    text = re.sub(r'<[^>]+>', '', content_html)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text[:2000]  # 앞부분 2000자만 사용

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

    # 유튜브 제목/설명/태그도 생성
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
  "youtube_description": "설명 (블로그 링크 포함, 150자 이내)",
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
# STEP 2: Gemini TTS로 음성 생성 (Orus 남성)
# ═════════════════════════════════════════════════════════════════════════════
def generate_voice(script: str) -> bytes:
    log.info("🎙️  음성 생성 중... (Gemini TTS - Orus)")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash-preview-tts:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{
            "parts": [{"text": script}]
        }],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": "Orus"
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
# STEP 3: 썸네일 이미지 + 음성 → 쇼츠 영상 합성 (ffmpeg)
# ═════════════════════════════════════════════════════════════════════════════
def create_shorts_video(image_url: str, audio_bytes: bytes, title: str) -> str:
    log.info("🎬 쇼츠 영상 합성 중... (ffmpeg)")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # 이미지 다운로드
        img_path = tmpdir / "thumbnail.jpg"
        img_resp = requests.get(image_url, timeout=30)
        img_path.write_bytes(img_resp.content)

        # 음성 저장 (Gemini TTS는 LINEAR16 PCM 포맷으로 반환)
        audio_raw_path = tmpdir / "voice.raw"
        audio_raw_path.write_bytes(audio_bytes)

        # raw PCM → WAV 변환
        audio_path = tmpdir / "voice.wav"
        wav_cmd = [
            "ffmpeg", "-y",
            "-f", "s16le",       # 16bit signed little-endian PCM
            "-ar", "22050",      # 샘플레이트 22050Hz (Gemini TTS 기본값)
            "-ac", "1",          # 모노
            "-i", str(audio_raw_path),
            str(audio_path)
        ]
        wav_result = subprocess.run(wav_cmd, capture_output=True, text=True)
        if wav_result.returncode != 0:
            # raw 변환 실패시 원본 그대로 사용
            audio_path = audio_raw_path
            log.warning(f"  ⚠️ WAV 변환 실패, 원본 사용: {wav_result.stderr[:200]}")

        # 출력 영상 경로
        output_path = tmpdir / "shorts.mp4"

        # ffmpeg로 이미지 + 음성 합치기 (9:16 쇼츠 비율)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(img_path),
            "-i", str(audio_path),
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "192k",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
            "-shortest",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 실패: {result.stderr}")

        # 최종 파일을 /tmp에 복사
        final_path = f"/tmp/shorts_{int(time.time())}.mp4"
        import shutil
        shutil.copy(str(output_path), final_path)

        log.info(f"  ✅ 영상 합성 완료: {final_path}")
        return final_path


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: 유튜브 업로드 (ausbro80 계정)
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
            "categoryId": "28",  # Science & Technology
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
        chunksize=1024 * 1024  # 1MB 청크
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

    # 임시 파일 삭제
    os.remove(video_path)

    return youtube_url


# ═════════════════════════════════════════════════════════════════════════════
# 메인 함수 — main.py에서 호출
# ═════════════════════════════════════════════════════════════════════════════
def post_youtube_shorts(title: str, content_html: str, image_url: str, blog_url: str) -> str:
    """
    블로그 포스팅 완료 후 호출.
    title       : 블로그 제목
    content_html: 블로그 본문 HTML
    image_url   : 썸네일 이미지 URL (imgur)
    blog_url    : 블로그 포스트 URL
    """
    try:
        # 1. 스크립트 생성
        shorts_meta = generate_shorts_script(title, content_html, blog_url)

        # 2. 음성 생성
        audio_bytes = generate_voice(shorts_meta["script"])

        # 3. 영상 합성
        video_path = create_shorts_video(image_url, audio_bytes, title)

        # 4. 유튜브 업로드
        youtube_url = upload_to_youtube(video_path, shorts_meta)

        return youtube_url

    except Exception as e:
        log.warning(f"  ⚠️ 유튜브 쇼츠 실패 (블로그는 정상): {e}")
        return ""
