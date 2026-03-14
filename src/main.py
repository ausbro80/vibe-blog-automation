"""
바이브코딩 스쿨 (VIBE CODING School) — Blog Automation v3
──────────────────────────────────────────────────────────
3트랙 자동 포스팅:
  아침 9시 → 📰 뉴스 트랙: X/트위터 AI 코딩 최신 소식
  저녁 9시 → 📚 교육 트랙 OR 🌟 인물 트랙 (3일에 1번)
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

# ── 교육 트랙 주제 풀 (50개) ──────────────────────────────────────────────────
EDU_TOPICS = [
    ("Cursor AI 완전 정복",            "Cursor AI 설치 사용법 2026"),
    ("Windsurf IDE 실전 리뷰",         "Windsurf IDE 사용후기 2026"),
    ("Lovable로 웹앱 30분 완성",        "Lovable 웹앱 만들기 2026"),
    ("Claude Code 실전 가이드",        "Claude Code 사용법 실전 2026"),
    ("Replit Agent 앱 배포",           "Replit Agent 앱 배포 방법 2026"),
    ("Bolt.new 솔직 후기",             "Bolt.new 사용후기 장단점 2026"),
    ("v0 by Vercel UI 자동생성",       "v0 Vercel UI 생성 사용법 2026"),
    ("GitHub Copilot 최신 기능",       "GitHub Copilot 업데이트 2026"),
    ("Google Antigravity IDE",        "Google Antigravity IDE 사용법 2026"),
    ("무료 AI 코딩 도구 추천",           "무료 AI 코딩 도구 추천 2026"),
    ("코딩 0% 앱 만들기 첫걸음",         "비개발자 AI 앱 만들기 입문 2026"),
    ("비개발자 첫 앱 출시 후기",          "비개발자 앱 출시 후기 2026"),
    ("직장인 사이드프로젝트 앱",          "직장인 AI 코딩 사이드프로젝트 2026"),
    ("소상공인 주문앱 만들기",           "소상공인 AI 주문앱 제작 2026"),
    ("프리랜서 업무 자동화 앱",          "프리랜서 AI 자동화 앱 2026"),
    ("인스타그램 스케줄러 앱",           "AI 코딩 SNS 자동화 앱 2026"),
    ("가계부 앱 바이브코딩",             "AI 코딩 가계부 앱 만들기 2026"),
    ("할일 관리 앱 만들기",             "AI 코딩 할일앱 제작 2026"),
    ("예약 관리 앱 만들기",             "AI 코딩 예약앱 소상공인 2026"),
    ("AI 챗봇 홈페이지에 붙이기",        "홈페이지 AI 챗봇 연동 2026"),
    ("포트폴리오 사이트 1시간 완성",      "AI 코딩 포트폴리오 사이트 2026"),
    ("쇼핑몰 만들기",                  "AI 코딩 온라인 쇼핑몰 제작 2026"),
    ("앱 배포 완전 가이드",             "바이브코딩 앱 배포 방법 2026"),
    ("로그인 기능 추가하기",             "AI 코딩 앱 로그인 회원가입 2026"),
    ("결제 기능 연동하기",              "AI 코딩 앱 결제 기능 2026"),
    ("바이브코딩 보안 주의사항",          "바이브코딩 앱 보안 취약점 2026"),
    ("AI가 짠 코드 이해하는 법",         "AI 생성 코드 읽는 법 2026"),
    ("오류 메시지 해결하는 법",          "바이브코딩 에러 해결 방법 2026"),
    ("프롬프트 잘 쓰는 법",             "AI 코딩 프롬프트 작성법 2026"),
    ("API 연결하기 쉬운 설명",           "바이브코딩 API 연동 방법 2026"),
    ("반응형 디자인 만들기",             "AI 코딩 모바일 반응형 2026"),
    ("SEO 최적화 사이트 만들기",         "AI 코딩 SEO 사이트 제작 2026"),
    ("Claude Code vs Cursor 비교",    "Claude Code Cursor 비교 2026"),
    ("바이브코딩으로 돈 버는 법",         "AI 코딩 수익화 방법 2026"),
    ("앱스토어 출시 가이드",             "바이브코딩 앱 앱스토어 등록 2026"),
    ("SaaS 창업 바이브코딩",           "비개발자 AI SaaS 창업 2026"),
    ("AI 코딩 유료 vs 무료 플랜",        "AI 코딩 도구 유료 무료 비교 2026"),
    ("한국어 지원 AI 코딩 도구",         "한국어 AI 코딩 도구 추천 2026"),
    ("버전 관리 깃허브 입문",            "AI 코딩 초보 깃허브 사용법 2026"),
    ("데이터베이스 연결하기",            "바이브코딩 데이터베이스 연동 2026"),
    ("다국어 앱 만들기",               "AI 코딩 다국어 앱 제작 2026"),
    ("앱 성능 최적화 팁",              "바이브코딩 앱 속도 최적화 2026"),
    ("설문조사 앱 만들기",              "AI 코딩 설문 앱 제작 2026"),
    ("블로그 자동화 앱",               "AI 코딩 블로그 자동화 2026"),
    ("AI 코딩 실패 사례 교훈",          "바이브코딩 실패 이유 2026"),
    ("비개발자의 시대 전망",             "비개발자 AI 코딩 미래 전망 2026"),
    ("AI 코딩 교육 어디서 배우나",        "바이브코딩 교육 추천 2026"),
    ("개발자와 비개발자 협업법",          "AI 코딩 개발자 비개발자 협업 2026"),
    ("모바일 앱 vs 웹앱 선택",          "바이브코딩 모바일 웹앱 선택 기준 2026"),
    ("AI 코딩 도구 선택 가이드",         "초보자 AI 코딩 도구 선택 방법 2026"),
    ("2026 AI 코딩 트렌드 총정리",      "2026 AI 코딩 트렌드 전망"),
]

# ── 인물 트랙 풀 ──────────────────────────────────────────────────────────────
PEOPLE_TOPICS = [
    ("Andrej Karpathy",   "Andrej Karpathy vibe coding 2026 latest project"),
    ("Pieter Levels",     "Pieter Levels levelsio 2026 new saas project"),
    ("Marc Lou",          "Marc Lou marclou 2026 new app launch"),
    ("Sam Altman",        "Sam Altman OpenAI AI coding 2026"),
    ("Greg Isenberg",     "Greg Isenberg AI startup vibe coding 2026"),
    ("Michael Truell",    "Michael Truell Cursor CEO 2026 update"),
    ("Dario Amodei",      "Dario Amodei Anthropic Claude Code 2026"),
    ("Lex Fridman",       "Lex Fridman AI coding vibe coding 2026"),
    ("Paul Graham",       "Paul Graham YC AI coding startups 2026"),
    ("Linus Ekenstam",    "Linus Ekenstam vibe coding 2026"),
]


def get_track_and_topic() -> dict:
    """
    날짜+시간 기반으로 트랙과 주제 결정
    - 아침(hour < 12) → 무조건 뉴스 트랙
    - 저녁(hour >= 12) → day_of_year % 3 == 0 이면 인물 트랙, 나머지 교육 트랙
    """
    now      = datetime.now()
    doy      = now.timetuple().tm_yday  # 1~365

    if now.hour < 12:
        track = "news"
        log.info("  🗞️  트랙: 뉴스 (최신 AI 코딩 소식)")
        return {"track": track}

    elif doy % 3 == 0:
        track = "people"
        idx   = (doy // 3) % len(PEOPLE_TOPICS)
        name, query = PEOPLE_TOPICS[idx]
        log.info(f"  🌟 트랙: 인물 [{idx+1}/{len(PEOPLE_TOPICS)}]: {name}")
        return {"track": track, "name": name, "query": query}

    else:
        track = "edu"
        # 저녁 교육 트랙: doy * 2 로 분산
        idx   = (doy * 2) % len(EDU_TOPICS)
        title, query = EDU_TOPICS[idx]
        log.info(f"  📚 트랙: 교육 [{idx+1}/{len(EDU_TOPICS)}]: {title}")
        return {"track": track, "title": title, "query": query}


# ═════════════════════════════════════════════════════════════════════════════
# 뉴스 수집 공통
# ═════════════════════════════════════════════════════════════════════════════
def extract_text(response) -> str:
    texts = []
    for block in response.content:
        if hasattr(block, "text") and isinstance(block.text, str) and block.text.strip():
            texts.append(block.text.strip())
    return "\n".join(texts)


def search_news(queries: list) -> list:
    """쿼리 목록으로 뉴스 수집"""
    collected = []
    today = datetime.now().strftime("%Y년 %m월 %d일")
    for q in queries:
        try:
            response = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                tool_choice={"type": "auto"},
                messages=[{
                    "role": "user",
                    "content": (
                        f"오늘({today}) 기준으로 '{q}'를 검색하고 "
                        "핵심 내용 3가지를 한국어로 요약해줘. "
                        "각 항목은 제목과 2~3문장으로 작성해줘."
                    ),
                }],
            )
            text = extract_text(response)
            if text:
                collected.append({"query": q, "summary": text})
                log.info(f"  ✅ '{q}' 수집 완료 ({len(text)}자)")
            time.sleep(5)
        except Exception as e:
            log.warning(f"  ⚠️ '{q}' 실패: {e}")
            time.sleep(3)
    return collected


# ═════════════════════════════════════════════════════════════════════════════
# 트랙별 글 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_news_post() -> dict:
    """📰 뉴스 트랙 — X/트위터 AI 코딩 최신 소식"""
    log.info("📡 뉴스 트랙 — 최신 소식 수집...")
    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")

    queries = [
        f"Claude Code Anthropic 업데이트 {year} 최신",
        f"Cursor Windsurf AI IDE 새기능 {year} 최신",
        f"Google AI Studio Gemini 코딩 업데이트 {year}",
        f"OpenAI Codex Perplexity AI 코딩 {year} 최신",
        f"vibe coding 트위터 화제 {year} 최신",
    ]

    collected = search_news(queries)

    news_text = "\n\n".join(
        f"[{item['query']}]\n{item['summary']}" for item in collected
    ) if collected else f"{year}년 AI 코딩 도구들의 최신 업데이트 내용"

    prompt = f"""
당신은 '바이브코딩 스쿨' 블로그 에디터입니다. 오늘 날짜: {today}

## 수집된 최신 소식
{news_text}

## 작성 지침
- 오늘 AI 코딩 업계에서 일어난 일들을 한국 일반인에게 쉽게 전달
- 어조: 친근한 테크 뉴스레터 스타일 ("~됐어요", "~네요")
- 각 소식마다 "이게 왜 중요한가" 한 줄 해설 필수
- 분량: 2000~2500자
- {year}년 기준 (다른 연도 언급 금지)
- 글 제목에 "오늘", "최신", "업데이트" 같은 시의성 키워드 포함

## 출력 (JSON만, 코드블록 없이)
{{
  "title_candidates": [
    "시의성 있는 뉴스 제목 후보 1",
    "시의성 있는 뉴스 제목 후보 2",
    "시의성 있는 뉴스 제목 후보 3",
    "시의성 있는 뉴스 제목 후보 4",
    "시의성 있는 뉴스 제목 후보 5"
  ],
  "meta_description": "메타설명 150자 이내",
  "tags": ["AI코딩뉴스", "바이브코딩", "Claude", "Cursor", "최신업데이트"],
  "slug": "ai-coding-news-{year}-today",
  "content_html": "완성된 HTML 본문"
}}
"""
    return _call_claude(prompt)


def generate_edu_post(title: str, query: str) -> dict:
    """📚 교육 트랙 — 실전 가이드"""
    log.info(f"📡 교육 트랙 — '{title}' 뉴스 수집...")
    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")

    collected = search_news([
        f"{query} 최신",
        f"{query} 실전 후기",
    ])

    news_text = "\n\n".join(
        f"[{item['query']}]\n{item['summary']}" for item in collected
    ) if collected else f"{title} 관련 {year}년 최신 정보"

    prompt = f"""
당신은 '바이브코딩 스쿨' 블로그 에디터입니다. 오늘 날짜: {today}
오늘 주제: {title}

## 수집된 최신 정보
{news_text}

## 작성 지침
- 독자: 코딩 0%의 일반인
- 어조: 친근한 선생님 스타일 ("~해요", "~거예요")
- 전문용어 금지, 읽고 바로 따라할 수 있게
- 수집된 최신 정보를 본문에 반드시 녹여낼 것
- 분량: 2500~3000자
- {year}년 기준

## 글 구조
1. 공감 도입부
2. 핵심 개념 쉬운 설명
3. 최신 트렌드/정보 활용
4. 단계별 실전 방법
5. 꿀팁 또는 주의사항
6. 마무리 + 다음 글 예고

## 출력 (JSON만, 코드블록 없이)
{{
  "title_candidates": [
    "SEO 제목 후보 1 ({year}년 기준)",
    "SEO 제목 후보 2 ({year}년 기준)",
    "SEO 제목 후보 3 ({year}년 기준)",
    "SEO 제목 후보 4 ({year}년 기준)",
    "SEO 제목 후보 5 ({year}년 기준)"
  ],
  "meta_description": "메타설명 150자 이내",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "slug": "seo-friendly-slug",
  "content_html": "완성된 HTML 본문"
}}
"""
    return _call_claude(prompt)


def generate_people_post(name: str, query: str) -> dict:
    """🌟 인물 트랙 — 유명 바이브코더 근황 + 사용 사례"""
    log.info(f"📡 인물 트랙 — '{name}' 정보 수집...")
    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")

    collected = search_news([
        query,
        f"{name} AI coding project {year}",
    ])

    news_text = "\n\n".join(
        f"[{item['query']}]\n{item['summary']}" for item in collected
    ) if collected else f"{name}의 {year}년 최근 활동 정보"

    prompt = f"""
당신은 '바이브코딩 스쿨' 블로그 에디터입니다. 오늘 날짜: {today}
오늘 소개할 인물: {name}

## 수집된 최신 정보
{news_text}

## 작성 지침
- {name}이 최근 AI 코딩 도구로 무엇을 만들고 있는지 소개
- 독자가 "나도 저렇게 할 수 있겠다"는 영감을 받도록 작성
- 어조: 친근하고 흥미로운 인물 소개 스타일
- 단순 소개가 아닌 "이 사람이 쓰는 도구와 방법" 실용적 내용 포함
- 독자가 따라할 수 있는 팁 2~3가지 포함
- 분량: 2000~2500자
- {year}년 기준

## 글 구조
1. 흥미로운 도입 ("이 사람 알아요?")
2. {name} 소개 (누구인지, 왜 유명한지)
3. 최근 만든 것 / 하는 일
4. 사용하는 AI 코딩 도구와 방법
5. 우리가 배울 점 + 따라할 수 있는 팁
6. 마무리

## 출력 (JSON만, 코드블록 없이)
{{
  "title_candidates": [
    "{name} 관련 흥미로운 제목 후보 1",
    "{name} 관련 흥미로운 제목 후보 2",
    "{name} 관련 흥미로운 제목 후보 3",
    "{name} 관련 흥미로운 제목 후보 4",
    "{name} 관련 흥미로운 제목 후보 5"
  ],
  "meta_description": "메타설명 150자 이내",
  "tags": ["{name}", "바이브코딩", "AI코딩", "인물소개", "사용사례"],
  "slug": "{name.lower().replace(' ', '-')}-vibe-coding-{year}",
  "content_html": "완성된 HTML 본문"
}}
"""
    return _call_claude(prompt)


def _call_claude(prompt: str) -> dict:
    """Claude API 호출 + JSON 파싱"""
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
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


# ═════════════════════════════════════════════════════════════════════════════
# SEO 제목 선택
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
# 이미지 프롬프트 생성
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
# 이미지 생성 (Gemini 2.5 Flash Image — 무료)
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
# Blogger 포스팅
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
    image_src = (
        f"data:image/png;base64,{image_b64}"
        if image_b64
        else "https://placehold.co/1200x630/6366f1/ffffff?text=Vibe+Coding+School"
    )
    full_html = f"""
<div style="margin-bottom:2rem;">
  <img src="{image_src}" alt="{title}"
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
            "customMetaData": json.dumps({
                "description": post_data.get("meta_description", ""),
                "slug": post_data.get("slug", ""),
            }),
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
    log.info("🚀 바이브코딩 스쿨 자동화 시작")
    log.info(f"   날짜: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    try:
        track_info = get_track_and_topic()
        track = track_info["track"]

        # 트랙별 글 생성
        if track == "news":
            post_data = generate_news_post()
        elif track == "people":
            post_data = generate_people_post(track_info["name"], track_info["query"])
        else:  # edu
            post_data = generate_edu_post(track_info["title"], track_info["query"])

        log.info("  ✅ 글 생성 완료")

        # SEO 제목 선택
        best_title = select_best_title(post_data)

        # 이미지 생성
        image_prompt = generate_image_prompt(best_title, post_data)
        image_b64    = generate_thumbnail(image_prompt)

        # 포스팅
        post_url = post_to_blogger(best_title, post_data, image_b64)

        log.info("=" * 60)
        log.info("🎉 전체 파이프라인 완료!")
        log.info(f"   트랙: {track.upper()} | URL: {post_url}")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"❌ 자동화 실패: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
