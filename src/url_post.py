"""
바이브코딩 스쿨 — URL 기반 즉시 포스팅
──────────────────────────────────────────────
텔레그램에서 받은 URL 내용을 읽고 블로그 + 인스타 포스팅
완료 후 텔레그램으로 결과 알림
"""

import os
import sys
import json
import time
import logging
import requests
import anthropic

from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
BLOGGER_BLOG_ID    = os.environ["BLOGGER_BLOG_ID"]
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS_JSON"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
CUSTOM_URL         = os.environ["CUSTOM_URL"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ═════════════════════════════════════════════════════════════
# 텔레그램 알림
# ═════════════════════════════════════════════════════════════
def send_telegram(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.warning(f"텔레그램 알림 실패: {e}")


# ═════════════════════════════════════════════════════════════
# 유틸
# ═════════════════════════════════════════════════════════════
def call_claude(prompt: str, max_tokens: int = 4000) -> dict:
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


# ═════════════════════════════════════════════════════════════
# STEP 1: URL 내용 읽기 + 블로그 글 생성
# ═════════════════════════════════════════════════════════════
def generate_post_from_url(url: str) -> dict:
    log.info(f"🔍 URL 내용 분석 중: {url[:60]}...")
    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")

    # Claude로 URL 내용 읽기 + 블로그 글 생성 한 번에
    prompt = f"""
아래 URL의 내용을 읽고 '바이브코딩 스쿨' 블로그 포스트를 작성해줘.

URL: {url}
오늘 날짜: {today}

## 바이브코딩 스쿨 글쓰기 원칙
- 독자: 코딩 0% 일반인 (직장인, 소상공인, 주부, 학생)
- 어조: 친근한 선생님 ("~해요", "~거예요", "~네요")
- 전문용어 나오면 반드시 쉽게 풀어서 설명
- URL의 핵심 내용을 반드시 본문에 녹여낼 것
- {year}년 현재 기준으로 작성
- 분량: 2000~2500자

## 글 구조
1. 핵심 내용 한 줄 요약으로 시작 (독자 관심 유발)
2. 이게 왜 중요한지 쉽게 설명
3. 핵심 내용 3가지로 정리
4. 독자에게 미치는 영향
5. 마무리 + 행동 유도

## 출력 (JSON만, 코드블록 없이)
{{
  "title_candidates": [
    "클릭률 높은 SEO 제목 1 ({year}년, 구체적)",
    "클릭률 높은 SEO 제목 2 ({year}년, 구체적)",
    "클릭률 높은 SEO 제목 3 ({year}년, 구체적)"
  ],
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "content_html": "완성된 HTML 본문 (h2 h3 p ul li strong 사용)"
}}
"""
    # 웹서치 도구로 URL 내용 읽기
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": prompt}],
    )

    # 텍스트 추출
    raw = ""
    for block in response.content:
        if hasattr(block, "text") and block.text.strip():
            raw = block.text.strip()
            break

    if not raw:
        raise ValueError("URL 내용 읽기 실패")

    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("{"):
                raw = part
                break

    return json.loads(raw.strip())


# ═════════════════════════════════════════════════════════════
# STEP 2: SEO 제목 선택
# ═════════════════════════════════════════════════════════════
def select_best_title(post_data: dict) -> str:
    candidates = "\n".join(
        f"{i+1}. {t}" for i, t in enumerate(post_data["title_candidates"])
    )
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": f"한국 구글 SEO와 클릭률 관점에서 가장 효과적인 제목 1개만 출력 (번호 없이):\n\n{candidates}",
        }],
    )
    return response.content[0].text.strip()


# ═════════════════════════════════════════════════════════════
# STEP 3: 썸네일 생성
# ═════════════════════════════════════════════════════════════
def generate_thumbnail(title: str, tags: list) -> str:
    log.info("🎨 썸네일 생성 중...")
    tags_str = ", ".join(tags)
    try:
        # 프롬프트 생성
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": f"블로그 썸네일용 영문 이미지 프롬프트 50단어 이내. 제목: {title}, 태그: {tags_str}. 밝고 친근한 테크 일러스트, 텍스트 없음, 16:9. 프롬프트만:"
            }],
        )
        img_prompt = response.content[0].text.strip()

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash-image:generateContent?key={GEMINI_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": f"{img_prompt}, modern flat illustration, vibrant colors, 16:9, no text"}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
        resp = requests.post(url, json=payload, timeout=90)
        resp.raise_for_status()
        data = resp.json()
        for part in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                log.info("  ✅ 썸네일 생성 완료")
                return part["inlineData"]["data"]
    except Exception as e:
        log.warning(f"  ⚠️ 썸네일 생성 실패: {e}")
    return ""


# ═════════════════════════════════════════════════════════════
# STEP 4: Blogger 포스팅
# ═════════════════════════════════════════════════════════════
def upload_image_to_imgur(image_b64: str) -> str:
    if not image_b64:
        return ""
    try:
        resp = requests.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": "Client-ID 546c25a59c58ad7"},
            data={"image": image_b64, "type": "base64"},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            return data["data"]["link"]
    except Exception as e:
        log.warning(f"  ⚠️ imgur 업로드 실패: {e}")
    return ""


def post_to_blogger(title: str, post_data: dict, image_b64: str) -> str:
    log.info("📤 Blogger 포스팅 중...")
    image_url = upload_image_to_imgur(image_b64)
    if not image_url:
        image_url = "https://placehold.co/1200x630/6366f1/ffffff?text=Vibe+Coding+School"

    full_html = f"""
<div style="margin-bottom:2rem;">
  <img src="{image_url}" alt="{title}"
       style="width:100%;border-radius:12px;max-height:420px;object-fit:cover;" />
</div>
{post_data['content_html']}
<hr style="margin:3rem 0;border:none;border-top:1px solid #eee;" />
<div style="background:#f0f4ff;padding:1.5rem;border-radius:8px;margin-top:2rem;">
  <p style="margin:0;font-size:0.9rem;color:#555;">
    📌 <strong>바이브코딩 스쿨</strong>은 코딩 몰라도 AI로 앱을 만들 수 있도록
    매일 아침·저녁 최신 내용을 업데이트합니다. 구독하고 놓치지 마세요! 🔔
  </p>
</div>
"""
    creds_info = json.loads(GOOGLE_CREDENTIALS)
    creds = Credentials(
        token=creds_info["token"],
        refresh_token=creds_info["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_info["client_id"],
        client_secret=creds_info["client_secret"],
    )
    service = build("blogger", "v3", credentials=creds)
    result = service.posts().insert(
        blogId=BLOGGER_BLOG_ID,
        body={
            "title": title,
            "content": full_html,
            "labels": post_data.get("tags", []),
        },
        isDraft=False,
    ).execute()
    post_url = result.get("url", "URL 없음")
    log.info(f"  ✅ 포스팅 완료: {post_url}")
    return post_url


# ═════════════════════════════════════════════════════════════
# 메인
# ═════════════════════════════════════════════════════════════
def main():
    log.info("=" * 60)
    log.info(f"🚀 URL 기반 즉시 포스팅 시작")
    log.info(f"   URL: {CUSTOM_URL[:60]}...")
    log.info("=" * 60)

    try:
        # 1. URL 읽고 블로그 글 생성
        post_data  = generate_post_from_url(CUSTOM_URL)
        best_title = select_best_title(post_data)
        log.info(f"  ✅ 제목: {best_title}")

        # 2. 썸네일 생성
        image_b64 = generate_thumbnail(best_title, post_data.get("tags", []))

        # 3. 블로그 포스팅
        blog_url = post_to_blogger(best_title, post_data, image_b64)

        # 4. 인스타 포스팅
        try:
            from instagram import post_instagram
            insta_url = post_instagram(
                blog_title=best_title,
                blog_content_html=post_data["content_html"],
                tags=post_data.get("tags", []),
            )
            log.info(f"  📸 인스타 포스팅 완료: {insta_url}")
        except Exception as e:
            log.warning(f"  ⚠️ 인스타 포스팅 실패: {e}")
            insta_url = None

        # 5. 텔레그램 완료 알림
        msg = f"""✅ 포스팅 완료!

📝 제목: {best_title}

🌐 블로그: {blog_url}"""
        if insta_url:
            msg += f"\n📸 인스타: {insta_url}"
        send_telegram(msg)

        log.info("=" * 60)
        log.info("🎉 완료!")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"❌ 실패: {e}", exc_info=True)
        send_telegram(f"❌ 포스팅 실패했어요!\n\n오류: {str(e)[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
