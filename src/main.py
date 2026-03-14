"""
Vibe Coding Blog Automation
────────────────────────────
매일 자동으로:
1. 최신 vibe coding 뉴스 수집 (Claude 웹서치)
2. 교육용 블로그 글 작성 (Claude API)
3. SEO 제목/메타태그 생성
4. 썸네일 이미지 생성 (Gemini REST API - 무료)
5. Google Blogger 자동 포스팅
"""

import os
import sys
import json
import time
import base64
import logging
from datetime import datetime

import anthropic
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ── 로깅 설정 ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── 환경변수 ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
BLOGGER_BLOG_ID    = os.environ["BLOGGER_BLOG_ID"]
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS_JSON"]

# ── 클라이언트 초기화 ────────────────────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ═══════════════════════════════════════════════════════════════════════════════
# 1단계: 최신 뉴스 수집
# ═══════════════════════════════════════════════════════════════════════════════
def collect_latest_news() -> dict:
    """Claude 웹서치로 오늘의 vibe coding 최신 정보 수집"""
    log.info("📡 최신 뉴스 수집 시작...")

    today = datetime.now().strftime("%Y년 %m월 %d일")
    year  = datetime.now().year  # 자동으로 현재 연도 사용

    search_topics = [
        f"vibe coding 최신 트렌드 {year}",
        f"Claude Code AI 코딩 도구 업데이트 {year}",
        f"Cursor Windsurf AI IDE 비교 {year}",
        f"AI 코딩 도구 초보자 입문 {year}",
    ]

    collected = []
    for topic in search_topics:
        try:
            response = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{
                    "role": "user",
                    "content": (
                        f"오늘({today}) 기준으로 '{topic}'에 대한 최신 정보를 검색해줘. "
                        "핵심 내용 3가지를 한국어로 요약해줘. "
                        "각 항목은 제목과 2~3문장 설명으로 구성해줘."
                    ),
                }],
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            if text.strip():
                collected.append({"topic": topic, "summary": text})
            time.sleep(3)  # API 레이트 리밋 방지
        except Exception as e:
            log.warning(f"  ⚠️ '{topic}' 검색 실패: {e}")

    log.info(f"  ✅ {len(collected)}개 주제 수집 완료")
    return {"date": today, "items": collected}


# ═══════════════════════════════════════════════════════════════════════════════
# 2단계: 블로그 글 작성 (Claude API)
# ═══════════════════════════════════════════════════════════════════════════════
def generate_blog_post(news_data: dict) -> dict:
    """수집된 뉴스를 바탕으로 교육용 블로그 글 생성"""
    log.info("✍️  블로그 글 작성 시작...")

    year = datetime.now().year

    news_summary = "\n\n".join(
        f"[{item['topic']}]\n{item['summary']}" for item in news_data["items"]
    ) if news_data["items"] else f"{year}년 최신 AI 코딩 트렌드 정보"

    prompt = f"""
당신은 비개발자들에게 AI 코딩 도구(vibe coding)를 쉽게 설명하는 전문 블로그 작가입니다.
오늘 날짜는 {news_data['date']}입니다. 반드시 {year}년 기준으로 글을 작성하세요.

## 오늘 수집된 최신 정보
{news_summary}

## 작성 지침
- 독자: 코딩을 전혀 모르지만 AI로 앱/웹사이트 만들고 싶은 일반인
- 어조: 친근하고 쉬운 말투, 전문용어는 반드시 풀어서 설명
- 분량: 2,500~3,000자
- 반드시 {year}년 현재 기준으로 작성 (과거 연도 언급 금지)
- 구조:
  1. 흥미로운 도입부 (독자의 공감 유도)
  2. Vibe Coding이란? (쉬운 정의)
  3. 오늘의 핵심 뉴스/트렌드 (최신 정보 활용)
  4. 주요 도구 소개 (Claude Code, Cursor, Windsurf 등)
  5. 초보자를 위한 시작 방법 (단계별)
  6. 마무리 + 다음 글 예고

## 출력 형식 (JSON)
반드시 아래 JSON만 출력하고 다른 텍스트 없이:
{{
  "title_candidates": [
    "{year}년 기준 SEO 최적화된 제목 후보 5개 (클릭률 높은 형태로)",
    "예: 코딩 몰라도 앱 만드는 법? Vibe Coding 완전 정복",
    "예: {year}년 AI 코딩 도구 TOP 3 — 비개발자도 하루 만에 앱 완성",
    "예: ChatGPT로 앱 만들기? 이제 Claude Code가 대세인 이유",
    "예: 직장인이 퇴근 후 2시간으로 앱 만든 실제 후기"
  ],
  "meta_description": "검색엔진 클릭률 높은 메타 디스크립션 (150자 이내)",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "slug": "url-friendly-slug-in-english",
  "content_html": "완성된 블로그 글 HTML (h2, h3, p, ul, li, strong 태그 사용)",
  "image_prompt": "Gemini로 생성할 썸네일 이미지 프롬프트 (영문, 블로그 주제에 맞는 미래적/친근한 이미지)"
}}
"""

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    post_data = json.loads(raw)
    log.info("  ✅ 블로그 글 생성 완료")
    return post_data


# ═══════════════════════════════════════════════════════════════════════════════
# 3단계: SEO 최적화 제목 선택
# ═══════════════════════════════════════════════════════════════════════════════
def select_best_title(post_data: dict) -> str:
    """후보 제목 중 SEO/CTR 관점에서 최적 제목 선택"""
    log.info("🔍 SEO 제목 최적화...")

    candidates = "\n".join(
        f"{i+1}. {t}" for i, t in enumerate(post_data["title_candidates"])
    )

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": (
                f"다음 블로그 제목 후보들 중 한국 구글 검색 SEO와 클릭률(CTR) 관점에서 "
                f"가장 효과적인 제목 1개만 골라서 그 제목만 출력해줘 (번호 없이):\n\n{candidates}"
            ),
        }],
    )

    title = response.content[0].text.strip()
    log.info(f"  ✅ 선택된 제목: {title}")
    return title


# ═══════════════════════════════════════════════════════════════════════════════
# 4단계: 썸네일 이미지 생성 (Gemini REST API — 무료)
# ═══════════════════════════════════════════════════════════════════════════════
def generate_thumbnail(image_prompt: str) -> str:
    """Gemini REST API로 썸네일 이미지 생성 (무료, 하루 500장)"""
    log.info("🎨 썸네일 이미지 생성 중... (Gemini / 무료)")

    enhanced_prompt = (
        f"{image_prompt}. "
        "Modern flat illustration style, vibrant colors, "
        "blog thumbnail 16:9 format, no text overlay, "
        "professional clean design, tech aesthetic, high quality"
    )

    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash-exp:generateContent?key={GEMINI_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": enhanced_prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        for part in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                b64 = part["inlineData"]["data"]
                log.info("  ✅ 이미지 생성 완료 (Gemini 무료)")
                return b64

        raise ValueError("이미지 데이터 없음")

    except Exception as e:
        log.warning(f"  ⚠️ 이미지 생성 실패 ({e}), 플레이스홀더 사용")
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# 5단계: Google Blogger 포스팅
# ═══════════════════════════════════════════════════════════════════════════════
def get_blogger_service():
    """Google Blogger API 서비스 객체 생성"""
    creds_info = json.loads(GOOGLE_CREDENTIALS)
    creds = Credentials(
        token=creds_info["token"],
        refresh_token=creds_info["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_info["client_id"],
        client_secret=creds_info["client_secret"],
    )
    return build("blogger", "v3", credentials=creds)


def build_image_src(b64_image: str) -> str:
    """이미지 data URI 생성 (없으면 플레이스홀더)"""
    if not b64_image:
        return "https://placehold.co/1200x630/6366f1/ffffff?text=Vibe+Coding+School"
    return f"data:image/png;base64,{b64_image}"


def post_to_blogger(title: str, post_data: dict, image_data: str) -> str:
    """완성된 글을 Google Blogger에 포스팅"""
    log.info("📤 Blogger 포스팅 중...")

    image_src = build_image_src(image_data)

    full_html = f"""
<div style="margin-bottom:2rem;">
  <img src="{image_src}" alt="{title}"
       style="width:100%;border-radius:12px;max-height:420px;object-fit:cover;" />
</div>

{post_data['content_html']}

<hr style="margin:3rem 0;" />
<div style="background:#f0f4ff;padding:1.5rem;border-radius:8px;margin-top:2rem;">
  <p style="margin:0;font-size:0.9rem;color:#555;">
    📌 <strong>이 글이 도움이 됐나요?</strong>
    구독하면 매일 아침·저녁 최신 AI 코딩 트렌드를 받아볼 수 있어요!
  </p>
</div>
"""

    service = get_blogger_service()
    body = {
        "title": title,
        "content": full_html,
        "labels": post_data.get("tags", []),
        "customMetaData": json.dumps({
            "description": post_data.get("meta_description", ""),
            "slug": post_data.get("slug", ""),
        }),
    }

    result = (
        service.posts()
        .insert(blogId=BLOGGER_BLOG_ID, body=body, isDraft=False)
        .execute()
    )

    post_url = result.get("url", "URL 없음")
    log.info(f"  ✅ 포스팅 완료: {post_url}")
    return post_url


# ═══════════════════════════════════════════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 60)
    log.info("🚀 Vibe Coding Blog 자동화 시작")
    log.info(f"   날짜: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    try:
        news_data  = collect_latest_news()
        post_data  = generate_blog_post(news_data)
        best_title = select_best_title(post_data)
        image_b64  = generate_thumbnail(post_data.get("image_prompt", ""))
        post_url   = post_to_blogger(best_title, post_data, image_b64)

        log.info("=" * 60)
        log.info("🎉 전체 파이프라인 완료!")
        log.info(f"   포스트 URL: {post_url}")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"❌ 자동화 실패: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
