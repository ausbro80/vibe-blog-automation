"""
바이브코딩 스쿨 — Threads 자동 포스팅
블로그 글 요약 + 캐릭터 이미지 + 링크
"""

import os
import time
import base64
import logging
import requests
import anthropic

log = logging.getLogger(__name__)

THREADS_TOKEN      = os.environ.get("THREADS_ACCESS_TOKEN", "")
THREADS_ACCOUNT_ID = os.environ.get("THREADS_ACCOUNT_ID", "")
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY    = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# 캐릭터 이미지 경로
CHAR_DIR = os.path.join(os.path.dirname(__file__), "characters")

# 트랙별 캐릭터 매핑
CHAR_MAP = {
    "news":    "char_surprised.png",   # 뉴스 → 놀라는 버전
    "edu":     "char_reading.png",     # 교육 → 책 읽는 버전
    "tool":    "char_thumbsup.png",    # 툴   → 엄지척 버전
    "default": "char_normal.png",      # 기본 → 일반 버전
}


# ═════════════════════════════════════════════════════════════
# 트랙에 맞는 캐릭터 이미지 선택
# ═════════════════════════════════════════════════════════════
def get_character_image(track: str = "default") -> str:
    """트랙에 맞는 캐릭터 파일명 반환"""
    filename = CHAR_MAP.get(track, CHAR_MAP["default"])
    path = os.path.join(CHAR_DIR, filename)

    # 해당 파일 없으면 기본으로 폴백
    if not os.path.exists(path):
        log.warning(f"  ⚠️ 캐릭터 파일 없음: {filename} → char_normal.png 시도")
        path = os.path.join(CHAR_DIR, "char_normal.png")

    if not os.path.exists(path):
        log.warning(f"  ⚠️ 기본 캐릭터 파일도 없음 → 이미지 없이 포스팅")
        return ""

    return path


# ═════════════════════════════════════════════════════════════
# 캐릭터 이미지 Cloudinary 업로드
# ═════════════════════════════════════════════════════════════
def upload_character_to_cloudinary(image_path: str) -> str:
    """캐릭터 이미지를 Cloudinary에 업로드하고 URL 반환"""
    import hashlib

    log.info(f"  ☁️  캐릭터 이미지 업로드 중...")
    timestamp = str(int(time.time()))
    filename = os.path.basename(image_path).replace(".png", "")
    public_id = f"vibe_school/characters/{filename}"

    params_to_sign = f"public_id={public_id}&timestamp={timestamp}"
    signature = hashlib.sha1(
        (params_to_sign + CLOUDINARY_API_SECRET).encode("utf-8")
    ).hexdigest()

    with open(image_path, "rb") as f:
        resp = requests.post(
            f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload",
            data={
                "public_id": public_id,
                "timestamp": timestamp,
                "api_key": CLOUDINARY_API_KEY,
                "signature": signature,
            },
            files={"file": ("image.png", f, "image/png")},
            timeout=60,
        )

    if not resp.ok:
        log.warning(f"  ⚠️ 캐릭터 업로드 실패: {resp.text[:100]}")
        return ""

    url = resp.json().get("secure_url", "")
    log.info(f"  ✅ 캐릭터 업로드 완료: {url[:60]}...")
    return url


# ═════════════════════════════════════════════════════════════
# Threads 텍스트 생성
# ═════════════════════════════════════════════════════════════
def generate_threads_text(
    blog_title: str,
    blog_content_html: str,
    blog_url: str,
    tags: list
) -> str:
    import re
    text = re.sub(r'<[^>]+>', '', blog_content_html)
    text = re.sub(r'\s+', ' ', text).strip()[:2000]

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": f"""아래 블로그 글을 Threads 포스팅용으로 만들어줘.

블로그 제목: {blog_title}
블로그 내용: {text}
블로그 링크: {blog_url}

## 규칙
- 3~5줄 핵심 요약 (친근한 말투 ~해요)
- 말하듯이 자연스럽게 (문어체 금지)
- 마지막에 블로그 링크 한 줄
- 해시태그 5개 이내
- 총 300자 이내
- 이모지 적절히 활용
- 텍스트만 출력 (다른 설명 없이)

예시:
AI 코딩 도구 가격이 200달러로 올랐어요 😱

근데 걱정 마세요!
평균 개발자는 월 180달러만 써요
무료~20달러 플랜으로도 충분해요

자세한 내용 👇
{blog_url}

#바이브코딩 #AI코딩 #Claude"""
        }]
    )
    return response.content[0].text.strip()


# ═════════════════════════════════════════════════════════════
# Threads 포스팅
# ═════════════════════════════════════════════════════════════
def post_to_threads(text: str, image_url: str = "") -> str:
    if not THREADS_TOKEN or not THREADS_ACCOUNT_ID:
        log.warning("  ⚠️ Threads 토큰/계정 없음 → 스킵")
        return ""

    base = "https://graph.threads.net/v1.0"

    # 미디어 컨테이너 생성
    body = {
        "text": text,
        "access_token": THREADS_TOKEN,
    }
    if image_url:
        body["media_type"] = "IMAGE"
        body["image_url"] = image_url
    else:
        body["media_type"] = "TEXT"

    for attempt in range(3):
        resp = requests.post(
            f"{base}/{THREADS_ACCOUNT_ID}/threads",
            json=body,
            timeout=30,
        )
        if resp.ok:
            break
        log.warning(f"  ⚠️ Threads 컨테이너 생성 실패 (시도 {attempt+1}/3): {resp.text[:100]}")
        time.sleep(15)
    resp.raise_for_status()
    container_id = resp.json()["id"]

    # 게시
    time.sleep(5)
    for attempt in range(3):
        resp = requests.post(
            f"{base}/{THREADS_ACCOUNT_ID}/threads_publish",
            json={
                "creation_id": container_id,
                "access_token": THREADS_TOKEN,
            },
            timeout=30,
        )
        if resp.ok:
            break
        log.warning(f"  ⚠️ Threads 게시 실패 (시도 {attempt+1}/3): {resp.text[:100]}")
        time.sleep(15)
    resp.raise_for_status()

    post_id = resp.json()["id"]
    threads_url = f"https://www.threads.net/t/{post_id}"
    log.info(f"  ✅ Threads 포스팅 완료: {threads_url}")
    return threads_url


# ═════════════════════════════════════════════════════════════
# 메인 함수 — main.py에서 호출
# ═════════════════════════════════════════════════════════════
def post_threads(
    blog_title: str,
    blog_content_html: str,
    blog_url: str,
    tags: list,
    track: str = "default",
    image_url: str = "",
) -> str:
    log.info("🧵 Threads 포스팅 중...")
    try:
        # 1. 텍스트 생성
        text = generate_threads_text(blog_title, blog_content_html, blog_url, tags)
        log.info(f"  📝 Threads 텍스트 생성 완료 ({len(text)}자)")

        # 2. 캐릭터 이미지 선택 + 업로드
        char_path = get_character_image(track)
        char_url = ""
        if char_path:
            char_url = upload_character_to_cloudinary(char_path)

        # 캐릭터 없으면 블로그 썸네일 사용
        final_image_url = char_url or image_url

        # 3. 포스팅
        return post_to_threads(text, final_image_url)

    except Exception as e:
        log.warning(f"  ⚠️ Threads 포스팅 실패: {e}")
        return ""
