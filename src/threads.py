"""
바이브코딩 스쿨 — Threads 자동 포스팅
블로그 글 요약 + 이미지 + 링크
"""

import os
import time
import logging
import requests
import anthropic

log = logging.getLogger(__name__)

THREADS_TOKEN      = os.environ.get("THREADS_ACCESS_TOKEN", "")
THREADS_ACCOUNT_ID = os.environ.get("THREADS_ACCOUNT_ID", "")

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def generate_threads_text(blog_title: str, blog_content_html: str, blog_url: str, tags: list) -> str:
    """블로그 글 → 쓰레드용 텍스트 생성"""
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
- 마지막에 블로그 링크 한 줄
- 해시태그 5개 이내
- 총 500자 이내
- 이모지 적절히 활용
- 텍스트만 출력 (다른 설명 없이)

예시 형식:
AI 코딩 도구 가격이 200달러로 올랐어요 😱

하지만 걱정 마세요!
평균 개발자는 월 180달러만 써요
무료~20달러 플랜으로도 충분해요

자세한 내용 👇
{blog_url}

#바이브코딩 #AI코딩 #Claude"""
        }]
    )
    return response.content[0].text.strip()


def post_to_threads(text: str, image_url: str = "") -> str:
    """Threads에 포스팅"""
    if not THREADS_TOKEN or not THREADS_ACCOUNT_ID:
        log.warning("  ⚠️ Threads 토큰/계정 없음 → 스킵")
        return ""

    base = "https://graph.threads.net/v1.0"

    # 1. 미디어 컨테이너 생성
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

    # 2. 게시
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


def post_threads(
    blog_title: str,
    blog_content_html: str,
    blog_url: str,
    tags: list,
    image_url: str = "",
) -> str:
    """main.py에서 호출하는 메인 함수"""
    log.info("🧵 Threads 포스팅 중...")
    try:
        text = generate_threads_text(blog_title, blog_content_html, blog_url, tags)
        log.info(f"  📝 Threads 텍스트 생성 완료 ({len(text)}자)")
        return post_to_threads(text, image_url)
    except Exception as e:
        log.warning(f"  ⚠️ Threads 포스팅 실패: {e}")
        return ""
