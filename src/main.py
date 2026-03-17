"""
바이브코딩 스쿨 (VIBE CODING School) — Blog Automation v4
──────────────────────────────────────────────────────────
3트랙 자동 포스팅:
  아침 9시 → 📰 뉴스 트랙: 오늘의 AI 코딩 최신 소식
  저녁 9시 → 📚 교육 트랙 OR 🌟 인물 트랙 (3일에 1번)

핵심: 주제를 미리 정하지 않고 AI가 오늘의 웹 트렌드를 보고 스스로 결정
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

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ═════════════════════════════════════════════════════════════════════════════
# 공통 유틸
# ═════════════════════════════════════════════════════════════════════════════
def extract_text(response) -> str:
    """Claude 응답에서 텍스트 안전하게 추출"""
    texts = []
    for block in response.content:
        if hasattr(block, "text") and isinstance(block.text, str) and block.text.strip():
            texts.append(block.text.strip())
    return "\n".join(texts)


def search(query: str, max_tokens: int = 2000) -> str:
    """단일 쿼리 웹서치 후 텍스트 반환"""
    today = datetime.now().strftime("%Y년 %m월 %d일")
    for attempt in range(3):
        try:
            time.sleep(15)  # 호출 전 대기 (rate limit 방지)
            response = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                tool_choice={"type": "auto"},
                messages=[{
                    "role": "user",
                    "content": f"오늘({today}) 기준으로 '{query}'를 검색하고 핵심 내용을 한국어로 요약해줘.",
                }],
            )
            text = extract_text(response)
            return text
        except Exception as e:
            wait = 30 * (attempt + 1)
            log.warning(f"  ⚠️ 검색 실패 '{query}' (시도 {attempt+1}/3): {e}")
            log.warning(f"  ⏳ {wait}초 대기 후 재시도...")
            time.sleep(wait)
    return ""


def call_claude(prompt: str, max_tokens: int = 4000) -> dict:
    """Claude API 호출 + JSON 파싱 (rate limit 재시도 포함)"""
    for attempt in range(3):
        try:
            time.sleep(15)  # 호출 전 대기 (rate limit 방지)
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
            wait = 30 * (attempt + 1)
            log.warning(f"  ⚠️ Claude 호출 실패 (시도 {attempt+1}/3): {e}")
            log.warning(f"  ⏳ {wait}초 대기 후 재시도...")
            time.sleep(wait)
    raise RuntimeError("Claude API 호출 3회 모두 실패")


def get_track() -> str:
    """
    아침(hour < 12) → news
    저녁 중 3일에 1번 → people
    나머지 저녁    → edu
    """
    now = datetime.now()
    if now.hour < 12:
        return "news"
    return "people" if now.timetuple().tm_yday % 3 == 0 else "edu"


# ═════════════════════════════════════════════════════════════════════════════
# 이미지 업로드 — base64 → imgur 외부 URL
# ═════════════════════════════════════════════════════════════════════════════
def upload_image_to_imgur(image_b64: str) -> str:
    """
    base64 이미지를 imgur에 업로드하고 URL 반환 (익명 업로드, 무료).
    실패 시 빈 문자열 반환.
    """
    if not image_b64:
        return ""
    try:
        log.info("☁️  이미지 imgur 업로드 중...")
        resp = requests.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": "Client-ID 546c25a59c58ad7"},
            data={"image": image_b64, "type": "base64"},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            img_url = data["data"]["link"]
            log.info(f"  ✅ imgur 업로드 완료: {img_url}")
            return img_url
        log.warning(f"  ⚠️ imgur 응답 실패: {data}")
        return ""
    except Exception as e:
        log.warning(f"  ⚠️ imgur 업로드 실패 ({e}), placehold 사용")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: AI가 오늘의 주제를 스스로 결정
# ═════════════════════════════════════════════════════════════════════════════
def decide_topic(track: str) -> dict:
    log.info(f"🧠 [{track.upper()}] 오늘의 주제 AI 자동 결정 중...")

    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")

    if track == "news":
        trend1 = search(f"Claude Anthropic AI coding update {year} latest")
        trend2 = search(f"Cursor Windsurf Lovable vibe coding news {year} latest")
        trend3 = search(f"OpenAI Codex Google Gemini Perplexity AI coding {year} latest")
        context = f"[Anthropic/Claude]\n{trend1}\n\n[Cursor/Windsurf/Lovable]\n{trend2}\n\n[기타 AI 도구]\n{trend3}"
        prompt = f"""
오늘({today}) AI 코딩 업계 최신 트렌드 정보입니다:
{context}
위 정보를 바탕으로 오늘 '바이브코딩 스쿨' 블로그의 뉴스 포스트 주제를 결정해줘.
- 오늘 가장 화제가 되는 내용 중심
- 한국 일반인 독자가 관심 가질 주제
- 이미 많이 다뤄진 "vibe coding이란?" 같은 기초 주제 절대 금지
JSON만 출력 (코드블록 없이):
{{
  "topic": "오늘의 구체적인 뉴스 주제 (한 문장)",
  "reason": "이 주제를 선택한 이유",
  "search_queries": ["추가로 검색할 쿼리1", "추가로 검색할 쿼리2"]
}}
"""
    elif track == "people":
        trend = search(f"vibe coding influencer developer twitter X {year} trending")
        prompt = f"""
오늘({today}) vibe coding 관련 화제의 인물 정보입니다:
{trend}
위 정보를 바탕으로 오늘 소개할 인물을 결정해줘.
- Andrej Karpathy, Pieter Levels, Marc Lou, Greg Isenberg, Michael Truell 등 포함 고려
- 최근 활발히 활동 중인 인물 우선
JSON만 출력 (코드블록 없이):
{{
  "topic": "인물 이름과 소개 주제",
  "person_name": "인물 영문 이름",
  "reason": "이 인물을 선택한 이유",
  "search_queries": ["인물 검색 쿼리1", "인물 검색 쿼리2"]
}}
"""
    else:
        trend1 = search(f"vibe coding tutorial beginner question {year}")
        trend2 = search(f"AI coding tool comparison review {year} Korea")
        prompt = f"""
오늘({today}) AI 코딩 관련 검색 트렌드 및 화제 정보입니다:
[튜토리얼/질문 트렌드]
{trend1}
[도구 비교/리뷰 트렌드]
{trend2}
위 정보를 바탕으로 오늘 '바이브코딩 스쿨' 블로그의 교육 포스트 주제를 결정해줘.
- 코딩 0% 초보자가 실제로 궁금해하는 내용
- "vibe coding이란?", "AI 코딩이란?" 같은 기초 입문 주제 절대 금지
JSON만 출력 (코드블록 없이):
{{
  "topic": "오늘의 구체적인 교육 주제 (한 문장)",
  "reason": "이 주제를 선택한 이유",
  "search_queries": ["추가로 검색할 쿼리1", "추가로 검색할 쿼리2"]
}}
"""

    topic_data = call_claude(prompt, max_tokens=500)
    log.info(f"  ✅ 결정된 주제: {topic_data['topic']}")
    log.info(f"  💡 선택 이유: {topic_data['reason']}")
    return topic_data


# ═════════════════════════════════════════════════════════════════════════════
# STEP 2: 심화 뉴스 수집
# ═════════════════════════════════════════════════════════════════════════════
def collect_deep_news(topic_data: dict) -> str:
    log.info("📡 심화 뉴스 수집 중...")
    results = []
    for q in topic_data.get("search_queries", []):
        text = search(q)
        if text:
            results.append(f"[{q}]\n{text}")
    combined = "\n\n".join(results)
    log.info(f"  ✅ 심화 뉴스 수집 완료 ({len(combined)}자)")
    return combined


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: 블로그 글 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_post(track: str, topic_data: dict, deep_news: str) -> dict:
    log.info("✍️  블로그 글 작성 시작...")
    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")
    topic = topic_data["topic"]

    base_rules = f"""
블로그명: 바이브코딩 스쿨 (VIBE CODING School)
오늘 날짜: {today} ({year}년 기준으로만 작성)
오늘 주제: {topic}
## 바이브코딩 스쿨 글쓰기 원칙
- 독자: 코딩 0% 일반인 (직장인, 소상공인, 주부, 학생)
- 어조: 친근한 선생님 ("~해요", "~거예요", "~네요")
- 전문용어 나오면 반드시 쉽게 풀어서 설명
- 수집된 최신 정보 반드시 본문에 녹여낼 것
- {year}년 현재 기준 (다른 연도 절대 금지)
- "vibe coding이란?", "AI 코딩이란?" 같은 기초 설명으로 글 시작 금지
"""

    if track == "news":
        structure = """
## 뉴스 트랙 글 구조
1. 오늘의 핵심 소식 한 줄 요약으로 시작
2. 각 소식별 쉬운 설명 + "이게 왜 중요한가" 한 줄 해설
3. 독자에게 미치는 영향
4. 오늘의 픽: 가장 주목할 소식 1개 강조
5. 마무리 + 내일 예고
분량: 2000~2500자
"""
    elif track == "people":
        name = topic_data.get("person_name", "")
        structure = f"""
## 인물 트랙 글 구조
1. "{name} 알아요?" 흥미로운 도입
2. 이 사람이 누구인지
3. 최근 AI 코딩으로 만든 것들
4. 사용하는 도구와 방법
5. 핵심 교훈 3가지
6. 마무리 (동기부여)
분량: 2000~2500자
"""
    else:
        structure = """
## 교육 트랙 글 구조
1. 공감 도입
2. 핵심 개념 쉽게 설명
3. 최신 트렌드 활용
4. 단계별 실전 방법
5. 꿀팁 또는 주의사항
6. 마무리 + 다음 글 예고
분량: 2500~3000자
"""

    prompt = f"""
{base_rules}
## 수집된 최신 정보
{deep_news if deep_news else f"{topic} 관련 {year}년 최신 정보"}
{structure}
## 출력 (JSON만, 코드블록 없이)
{{
  "title_candidates": [
    "클릭률 높은 SEO 제목 1 ({year}년, 구체적)",
    "클릭률 높은 SEO 제목 2 ({year}년, 구체적)",
    "클릭률 높은 SEO 제목 3 ({year}년, 구체적)",
    "클릭률 높은 SEO 제목 4 ({year}년, 구체적)",
    "클릭률 높은 SEO 제목 5 ({year}년, 구체적)"
  ],
  "meta_description": "구글 클릭률 높은 메타설명 150자 이내",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "slug": "seo-english-slug-{year}",
  "content_html": "완성된 HTML 본문 (h2 h3 p ul li strong 사용)"
}}
"""
    post_data = call_claude(prompt)
    log.info("  ✅ 블로그 글 생성 완료")
    return post_data


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: SEO 제목 선택
# ═════════════════════════════════════════════════════════════════════════════
def select_best_title(post_data: dict) -> str:
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
                f"다음 제목 후보 중 한국 구글 SEO와 클릭률 관점에서 "
                f"가장 효과적인 제목 1개만 출력해줘 (번호 없이):\n\n{candidates}"
            ),
        }],
    )
    title = response.content[0].text.strip()
    log.info(f"  ✅ 선택된 제목: {title}")
    return title


# ═════════════════════════════════════════════════════════════════════════════
# STEP 5: 이미지 프롬프트 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_image_prompt(title: str, post_data: dict) -> str:
    log.info("🖼️  이미지 프롬프트 생성 중...")
    tags = ", ".join(post_data.get("tags", []))
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": (
                f"블로그 썸네일용 영문 이미지 프롬프트 50단어 이내로 만들어줘.\n"
                f"제목: {title}\n태그: {tags}\n\n"
                "조건: 밝고 친근한 테크 일러스트, 텍스트 없음, 16:9.\n"
                "프롬프트만 출력:"
            ),
        }],
    )
    prompt = response.content[0].text.strip()
    log.info(f"  ✅ 프롬프트: {prompt[:60]}...")
    return prompt


# ═════════════════════════════════════════════════════════════════════════════
# STEP 6: 이미지 생성 (Gemini 2.5 Flash Image)
# ═════════════════════════════════════════════════════════════════════════════
def generate_thumbnail(image_prompt: str) -> str:
    log.info("🎨 썸네일 생성 중... (Gemini 2.5 Flash Image / 무료)")
    enhanced = (
        f"{image_prompt}, modern flat illustration, vibrant colors, "
        "16:9 blog thumbnail, no text no letters, "
        "professional tech design, bright friendly"
    )
    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash-image:generateContent?key={GEMINI_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": enhanced}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
        resp = requests.post(url, json=payload, timeout=90)
        resp.raise_for_status()
        data = resp.json()
        for part in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                log.info("  ✅ 이미지 생성 완료")
                return part["inlineData"]["data"]
        raise ValueError("이미지 데이터 없음")
    except Exception as e:
        log.warning(f"  ⚠️ 이미지 생성 실패 ({e}), 플레이스홀더 사용")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# STEP 7: Blogger 포스팅
# ═════════════════════════════════════════════════════════════════════════════
def get_blogger_service():
    creds_info = json.loads(GOOGLE_CREDENTIALS)
    creds = Credentials(
        token=creds_info["token"],
        refresh_token=creds_info["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_info["client_id"],
        client_secret=creds_info["client_secret"],
    )
    return build("blogger", "v3", credentials=creds)


def post_to_blogger(title: str, post_data: dict, image_b64: str) -> str:
    log.info("📤 Blogger 포스팅 중...")

    # ── 이미지 URL 결정 ──────────────────────────────────────────
    # 1순위: Blogger 앨범에 업로드한 외부 URL (대표 이미지 자동 인식됨)
    # 2순위: placehold.co 대체 이미지
    image_url = upload_image_to_imgur(image_b64)
    if not image_url:
        image_url = "https://placehold.co/1200x630/6366f1/ffffff?text=Vibe+Coding+School"
        log.info("  ℹ️  placehold 이미지 사용")

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
    service = get_blogger_service()
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


# ═════════════════════════════════════════════════════════════════════════════
# 메인
# ═════════════════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 60)
    log.info("🚀 바이브코딩 스쿨 자동화 시작 (v4 — AI 주제 자동 결정)")
    log.info(f"   날짜: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    try:
        track = get_track()
        log.info(f"  📌 트랙: {track.upper()}")

        topic_data = decide_topic(track)
        deep_news  = collect_deep_news(topic_data)
        post_data  = generate_post(track, topic_data, deep_news)
        best_title = select_best_title(post_data)

        image_prompt = generate_image_prompt(best_title, post_data)
        image_b64    = generate_thumbnail(image_prompt)

        post_url = post_to_blogger(best_title, post_data, image_b64)

        log.info("=" * 60)
        log.info("🎉 전체 파이프라인 완료!")
        log.info(f"   트랙: {track.upper()} | 주제: {topic_data['topic']}")
        log.info(f"   URL: {post_url}")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"❌ 자동화 실패: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
