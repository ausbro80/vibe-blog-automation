"""
Vibe Coding Blog Automation
────────────────────────────
매일 자동으로:
1. 최신 vibe coding 뉴스 수집 (Claude 웹서치 - 견고한 파싱)
2. 교육용 블로그 글 작성 (Claude API)
3. SEO 제목/메타태그 생성
4. 글 내용 기반 이미지 프롬프트 생성 (뉴스 수집 실패와 무관)
5. Gemini imagen-3.0으로 이미지 생성 (무료)
6. Google Blogger 자동 포스팅
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

# ── 로깅 설정 ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── 환경변수 ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
BLOGGER_BLOG_ID    = os.environ["BLOGGER_BLOG_ID"]
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS_JSON"]

# ── 클라이언트 초기화 ─────────────────────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ═════════════════════════════════════════════════════════════════════════════
# 1단계: 최신 뉴스 수집 (견고한 파싱)
# ═════════════════════════════════════════════════════════════════════════════
def extract_text_from_response(response) -> str:
    """Claude 응답에서 텍스트 안전하게 추출 — None 방지"""
    texts = []
    for block in response.content:
        # text 속성이 있고 실제 문자열인 경우만 추가
        if hasattr(block, "text") and isinstance(block.text, str) and block.text.strip():
            texts.append(block.text.strip())
        # tool_result 블록 안의 텍스트도 추출
        elif hasattr(block, "type") and block.type == "tool_result":
            if hasattr(block, "content"):
                for sub in block.content:
                    if hasattr(sub, "text") and isinstance(sub.text, str):
                        texts.append(sub.text.strip())
    return "\n".join(texts)


def collect_latest_news() -> dict:
    """Claude 웹서치로 오늘의 vibe coding 최신 정보 수집"""
    log.info("📡 최신 뉴스 수집 시작...")

    today = datetime.now().strftime("%Y년 %m월 %d일")
    year  = datetime.now().year

    search_topics = [
        f"vibe coding 최신 트렌드 {year}",
        f"Claude Code AI 코딩 도구 {year}",
        f"Cursor Windsurf AI 코딩 도구 비교 {year}",
        f"비개발자 AI 앱 만들기 {year}",
    ]

    collected = []
    for topic in search_topics:
        try:
            response = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                tool_choice={"type": "auto"},
                messages=[{
                    "role": "user",
                    "content": (
                        f"오늘({today}) 기준으로 '{topic}'을 검색하고 "
                        "핵심 내용 3가지를 한국어로 요약해줘. "
                        "반드시 검색 결과를 바탕으로 작성하고, "
                        "각 항목은 제목과 2~3문장으로 구성해줘."
                    ),
                }],
            )

            text = extract_text_from_response(response)

            if text:
                collected.append({"topic": topic, "summary": text})
                log.info(f"  ✅ '{topic}' 수집 완료 ({len(text)}자)")
            else:
                log.warning(f"  ⚠️ '{topic}' 빈 응답")

            time.sleep(5)  # 레이트 리밋 방지 (충분히 여유 있게)

        except Exception as e:
            log.warning(f"  ⚠️ '{topic}' 검색 실패: {e}")
            time.sleep(3)

    log.info(f"  ✅ {len(collected)}개 주제 수집 완료")
    return {"date": today, "items": collected}


# ═════════════════════════════════════════════════════════════════════════════
# 2단계: 블로그 글 작성 (Claude API)
# ═════════════════════════════════════════════════════════════════════════════
def generate_blog_post(news_data: dict) -> dict:
    """수집된 뉴스를 바탕으로 교육용 블로그 글 생성"""
    log.info("✍️  블로그 글 작성 시작...")

    year = datetime.now().year

    if news_data["items"]:
        news_summary = "\n\n".join(
            f"[{item['topic']}]\n{item['summary']}"
            for item in news_data["items"]
        )
        log.info(f"  뉴스 {len(news_data['items'])}개 활용하여 글 작성")
    else:
        news_summary = (
            f"{year}년 현재 AI 코딩 도구 시장은 빠르게 성장하고 있으며, "
            "Claude Code, Cursor, Windsurf, Lovable 등의 도구들이 "
            "비개발자들도 쉽게 앱을 만들 수 있도록 돕고 있습니다."
        )
        log.info("  뉴스 수집 없음 — 기본 내용으로 글 작성")

    prompt = f"""
당신은 비개발자들에게 AI 코딩 도구(vibe coding)를 쉽게 설명하는 전문 블로그 작가입니다.
오늘 날짜는 {news_data['date']}입니다. 반드시 {year}년 기준으로 글을 작성하세요.

## 오늘 수집된 최신 정보
{news_summary}

## 작성 지침
- 독자: 코딩을 전혀 모르지만 AI로 앱/웹사이트 만들고 싶은 일반인
- 어조: 친근하고 쉬운 말투, 전문용어는 반드시 풀어서 설명
- 분량: 2,500~3,000자
- 반드시 {year}년 현재 기준으로 작성 (다른 연도 언급 금지)
- 구조:
  1. 흥미로운 도입부 (독자의 공감 유도)
  2. Vibe Coding이란? (쉬운 정의)
  3. 오늘의 핵심 뉴스/트렌드
  4. 주요 도구 소개 (Claude Code, Cursor, Windsurf, Lovable)
  5. 초보자를 위한 시작 방법 (단계별)
  6. 마무리 + 다음 글 예고

## 출력 형식 (JSON)
반드시 아래 JSON만 출력하고 마크다운 코드블록 없이:
{{
  "title_candidates": [
    "{year}년 기준 SEO 제목 후보 1",
    "{year}년 기준 SEO 제목 후보 2",
    "{year}년 기준 SEO 제목 후보 3",
    "{year}년 기준 SEO 제목 후보 4",
    "{year}년 기준 SEO 제목 후보 5"
  ],
  "meta_description": "메타 디스크립션 150자 이내",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "slug": "url-friendly-slug-in-english",
  "content_html": "완성된 블로그 글 HTML"
}}
"""

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # JSON 펜스 제거
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                raw = part
                break

    post_data = json.loads(raw.strip())
    log.info("  ✅ 블로그 글 생성 완료")
    return post_data


# ═════════════════════════════════════════════════════════════════════════════
# 3단계: SEO 최적화 제목 선택
# ═════════════════════════════════════════════════════════════════════════════
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
                f"다음 블로그 제목 후보들 중 한국 구글 검색 SEO와 "
                f"클릭률(CTR) 관점에서 가장 효과적인 제목 1개만 골라서 "
                f"그 제목만 출력해줘 (번호 없이):\n\n{candidates}"
            ),
        }],
    )

    title = response.content[0].text.strip()
    log.info(f"  ✅ 선택된 제목: {title}")
    return title


# ═════════════════════════════════════════════════════════════════════════════
# 4단계: 글 내용 기반 이미지 프롬프트 생성 (뉴스 수집과 완전 독립)
# ═════════════════════════════════════════════════════════════════════════════
def generate_image_prompt(title: str, post_data: dict) -> str:
    """완성된 글 제목과 태그를 기반으로 이미지 프롬프트 생성"""
    log.info("🖼️  이미지 프롬프트 생성 중... (글 내용 기반)")

    tags = ", ".join(post_data.get("tags", []))

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": (
                f"블로그 썸네일용 영문 이미지 프롬프트를 만들어줘.\n\n"
                f"제목: {title}\n"
                f"태그: {tags}\n\n"
                "조건:\n"
                "- 영문만, 50단어 이내\n"
                "- 밝고 미래적인 테크 일러스트 스타일\n"
                "- 사람이 AI 도구로 쉽게 앱을 만드는 느낌\n"
                "- 텍스트/글자 포함 금지\n"
                "프롬프트만 출력:"
            ),
        }],
    )

    prompt = response.content[0].text.strip()
    log.info(f"  ✅ 프롬프트 생성: {prompt[:60]}...")
    return prompt


# ═════════════════════════════════════════════════════════════════════════════
# 5단계: 썸네일 이미지 생성 (Gemini imagen-3.0 — 무료)
# ═════════════════════════════════════════════════════════════════════════════
def generate_thumbnail(image_prompt: str) -> str:
    """Gemini imagen-3.0으로 썸네일 이미지 생성"""
    log.info("🎨 썸네일 이미지 생성 중... (Gemini imagen-3.0)")

    enhanced_prompt = (
        f"{image_prompt}, "
        "modern flat illustration, vibrant colors, "
        "16:9 blog thumbnail, no text, no letters, "
        "professional tech design, high quality"
    )

    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"imagen-3.0-generate-002:predict?key={GEMINI_API_KEY}"
        )
        payload = {
            "instances": [{"prompt": enhanced_prompt}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": "16:9",
                "safetyFilterLevel": "block_few",
                "personGeneration": "dont_allow",
            },
        }
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        b64 = data["predictions"][0]["bytesBase64Encoded"]
        log.info("  ✅ 이미지 생성 완료 (imagen-3.0)")
        return b64

    except Exception as e:
        log.warning(f"  ⚠️ 이미지 생성 실패 ({e}), 플레이스홀더 사용")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# 6단계: Google Blogger 포스팅
# ═════════════════════════════════════════════════════════════════════════════
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


# ═════════════════════════════════════════════════════════════════════════════
# 메인 실행
# ═════════════════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 60)
    log.info("🚀 Vibe Coding Blog 자동화 시작")
    log.info(f"   날짜: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    try:
        # 1. 뉴스 수집 (실패해도 계속 진행)
        news_data = collect_latest_news()

        # 2. 블로그 글 작성
        post_data = generate_blog_post(news_data)

        # 3. 최적 제목 선택
        best_title = select_best_title(post_data)

        # 4. 글 내용 기반 이미지 프롬프트 생성 (뉴스 수집과 완전 독립)
        image_prompt = generate_image_prompt(best_title, post_data)

        # 5. 이미지 생성
        image_b64 = generate_thumbnail(image_prompt)

        # 6. 블로그 포스팅
        post_url = post_to_blogger(best_title, post_data, image_b64)

        log.info("=" * 60)
        log.info("🎉 전체 파이프라인 완료!")
        log.info(f"   포스트 URL: {post_url}")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"❌ 자동화 실패: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
