"""
AI 재테크 스쿨 — Blog Automation v1
──────────────────────────────────────────────────────────
트랙 구성:
  아침 9시 → 📰 뉴스 트랙: AI 재테크/부업 최신 소식
  저녁 9시 → 💰 실전 트랙 / 🛠️ 툴 활용 트랙 (하루씩 번갈아)

주제: AI로 돈 버는 법, 부업, 자동화 수익, 재테크
"""

import os
import sys
import json
import time
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
BLOGGER_BLOG_ID    = "1368192571557546642"
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS_JSON"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

TOOL_LIST = [
    "Claude (Anthropic)",
    "ChatGPT",
    "Perplexity AI",
    "Gemini",
    "Cursor",
    "Midjourney",
    "Notion AI",
    "Canva AI",
]


# ═════════════════════════════════════════════════════════════════════════════
# 공통 유틸
# ═════════════════════════════════════════════════════════════════════════════
def extract_text(response) -> str:
    texts = []
    for block in response.content:
        if hasattr(block, "text") and isinstance(block.text, str) and block.text.strip():
            texts.append(block.text.strip())
    return "\n".join(texts)


def search(query: str, max_tokens: int = 2000) -> str:
    today = datetime.now().strftime("%Y년 %m월 %d일")
    for attempt in range(3):
        try:
            time.sleep(15)
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
            return extract_text(response)
        except Exception as e:
            wait = 30 * (attempt + 1)
            log.warning(f"  ⚠️ 검색 실패 '{query}' (시도 {attempt+1}/3): {e}")
            time.sleep(wait)
    return ""


def call_claude(prompt: str, max_tokens: int = 4000) -> dict:
    for attempt in range(3):
        try:
            time.sleep(15)
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
            time.sleep(wait)
    raise RuntimeError("Claude API 호출 3회 모두 실패")


def get_track() -> tuple:
    now = datetime.now()
    if now.hour < 12:
        return "news", None
    if now.timetuple().tm_yday % 2 == 0:
        tool = TOOL_LIST[(now.timetuple().tm_yday // 2) % len(TOOL_LIST)]
        return "tool", tool
    return "practical", None


# ═════════════════════════════════════════════════════════════════════════════
# 이미지 업로드
# ═════════════════════════════════════════════════════════════════════════════
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
        return ""
    except Exception as e:
        log.warning(f"  ⚠️ imgur 업로드 실패 ({e})")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: 오늘의 주제 결정
# ═════════════════════════════════════════════════════════════════════════════
def decide_topic(track: str, tool_name: str = None) -> dict:
    log.info(f"🧠 [{track.upper()}] 오늘의 주제 AI 자동 결정 중...")

    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")

    if track == "news":
        trend1 = search(f"AI 부업 재테크 수익화 최신 트렌드 {year}")
        trend2 = search(f"AI 자동화 블로그 유튜브 수익 {year} 한국")
        trend3 = search(f"직장인 부업 AI 도구 활용 {year} 최신")
        context = f"[AI 부업/재테크 트렌드]\n{trend1}\n\n[AI 자동화 수익]\n{trend2}\n\n[직장인 부업]\n{trend3}"
        prompt = f"""
오늘({today}) AI 재테크/부업 관련 최신 트렌드입니다:
{context}

'AI 재테크 스쿨' 블로그의 뉴스 포스트 주제를 결정해줘.
- 오늘 가장 화제되는 AI 재테크/부업 관련 내용
- 직장인, 주부, 취준생이 관심 가질 주제
- "AI란 무엇인가" 같은 기초 주제 절대 금지
- 실제로 돈이 되는 실용적인 내용

JSON만 출력 (코드블록 없이):
{{
  "topic": "오늘의 구체적인 뉴스 주제 (한 문장)",
  "reason": "이 주제를 선택한 이유",
  "search_queries": ["추가로 검색할 쿼리1", "추가로 검색할 쿼리2"]
}}
"""

    elif track == "tool":
        trend1 = search(f"{tool_name} 부업 수익화 활용법 {year}")
        trend2 = search(f"{tool_name} 재테크 자동화 돈버는법 {year}")
        trend3 = search(f"{tool_name} 초보자 부업 사용법 {year}")
        prompt = f"""
오늘({today}) 다룰 AI 도구: {tool_name}

부업/수익화 관련 정보:
[수익화 활용법]
{trend1}
[재테크/자동화]
{trend2}
[초보자 사용법]
{trend3}

'{tool_name}'을 활용한 부업/재테크 블로그 포스트 주제를 결정해줘.
- {year}년 최신 기준
- 실제로 수익을 낼 수 있는 구체적인 방법
- 코딩 0% 초보자도 따라할 수 있는 내용
- 예: "ChatGPT로 전자책 만들어 월 100만원 버는 법", "Claude로 블로그 자동화해서 부업하기"

JSON만 출력 (코드블록 없이):
{{
  "topic": "오늘의 구체적인 툴 활용 부업 주제 (한 문장)",
  "tool": "{tool_name}",
  "reason": "이 주제를 선택한 이유",
  "search_queries": ["추가로 검색할 쿼리1", "추가로 검색할 쿼리2"]
}}
"""

    else:  # practical
        trend1 = search(f"AI 부업 실전 방법 월수입 {year} 한국")
        trend2 = search(f"직장인 투잡 AI 자동화 수익화 {year}")
        prompt = f"""
오늘({today}) AI 부업/재테크 실전 트렌드입니다:
[AI 부업 실전]
{trend1}
[직장인 투잡]
{trend2}

'AI 재테크 스쿨' 블로그의 실전 가이드 주제를 결정해줘.
- 실제로 따라하면 수익이 나는 구체적인 방법
- 초보자도 바로 시작할 수 있는 내용
- "AI 투자란?" 같은 기초 주제 절대 금지

JSON만 출력 (코드블록 없이):
{{
  "topic": "오늘의 구체적인 실전 주제 (한 문장)",
  "reason": "이 주제를 선택한 이유",
  "search_queries": ["추가로 검색할 쿼리1", "추가로 검색할 쿼리2"]
}}
"""

    topic_data = call_claude(prompt, max_tokens=500)
    log.info(f"  ✅ 결정된 주제: {topic_data['topic']}")
    return topic_data


# ═════════════════════════════════════════════════════════════════════════════
# STEP 2: 심화 정보 수집
# ═════════════════════════════════════════════════════════════════════════════
def collect_deep_research(topic_data: dict) -> str:
    log.info("📡 심화 정보 수집 중...")
    results = []
    for q in topic_data.get("search_queries", []):
        text = search(q)
        if text:
            results.append(f"[{q}]\n{text}")
    combined = "\n\n".join(results)
    log.info(f"  ✅ 정보 수집 완료 ({len(combined)}자)")
    return combined


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: 블로그 글 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_post(track: str, topic_data: dict, deep_research: str) -> dict:
    log.info("✍️  블로그 글 작성 시작...")
    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")
    topic = topic_data["topic"]

    base_rules = f"""
블로그명: AI 재테크 스쿨
오늘 날짜: {today} ({year}년 기준으로만 작성)
오늘 주제: {topic}

## AI 재테크 스쿨 글쓰기 원칙
- 독자: 부업/재테크에 관심 있는 직장인, 주부, 취준생 (20~40대)
- 어조: 친근한 재테크 선배 ("~해요", "~거예요", "~네요")
- 전문용어 나오면 반드시 쉽게 풀어서 설명
- 수집된 최신 정보 반드시 본문에 녹여낼 것
- {year}년 현재 기준 (다른 연도 절대 금지)
- "AI란 무엇인가" 같은 기초 설명으로 글 시작 금지
- 단순 정보 나열 말고 실제로 얼마 벌 수 있는지, 어떻게 시작하는지 구체적으로 작성
- 수집된 정보를 단순 요약하지 말고 한국 직장인/주부 관점의 인사이트와 실전 팁 반드시 추가

## SEO 제목 규칙 (반드시 준수)
- 형식: [핵심 키워드] + [구체적 방법/금액/결과] + [대상 또는 연도]
- 핵심 키워드를 제목 앞부분에 배치
- 숫자 포함 필수 (예: "월 50만원", "3가지 방법", "30분 만에")
- 클릭베이트 절대 금지: "충격!", "대박!", "미쳤다" 같은 표현 금지
- 좋은 예: "Claude로 전자책 만들어 월 50만원 버는 법 - 직장인 부업 가이드 {year}"
- 나쁜 예: "이 방법으로 대박났다! AI 부업 충격 실화"

## 태그 규칙 (반드시 준수)
- 글당 총 3~5개 선택
- 필수 태그 중 1~2개 반드시 포함:
  AI부업, 재테크, 부업, AI자동화, 직장인부업, 수익화, 투잡, 초보자가이드
- 선택 태그는 해당 툴이 글의 핵심 주제일 때만 추가:
  Claude, ChatGPT, Gemini, Perplexity, Canva, Notion
- 이 목록 외의 태그는 절대 생성 금지
"""

    if track == "news":
        structure = """
## 뉴스 트랙 글 구조
1. 오늘의 핵심 소식 한 줄 요약 (돈과 연결해서)
2. 이게 재테크/부업에 어떤 의미인지 쉽게 설명
3. 실제로 어떻게 활용할 수 있는지 구체적 방법
4. 예상 수익 또는 절약 금액 (현실적으로)
5. 지금 바로 시작할 수 있는 첫 번째 액션
6. 마무리 + 다음 글 예고
분량: 2000~2500자
"""
    elif track == "tool":
        tool = topic_data.get("tool", "AI 도구")
        structure = f"""
## 툴 활용 부업 가이드 구조 ({tool} 활용)
1. "이런 분들께 딱!" 공감 도입 (이 방법이 필요한 상황)
2. {tool}로 할 수 있는 부업/수익화 방법 3가지
3. 각 방법별 단계별 시작 가이드 (스크린샷 설명하듯 자세하게)
4. 예상 수익 범위 (현실적으로 - 과장 금지)
5. 초보자가 자주 하는 실수 + 해결법
6. 이번 달 바로 시작하는 액션 플랜
7. 마무리 + 다음 툴 예고
분량: 2500~3000자
"""
    else:
        structure = """
## 실전 부업/재테크 가이드 구조
1. 공감 도입 (이 방법이 필요한 상황)
2. 왜 지금 이 방법인지 (시장 상황, 수요)
3. 단계별 실전 시작 방법 (최대한 구체적으로)
4. 현실적인 수익 예상 (초보/중급/고급 단계별)
5. 주의사항 + 흔한 실수
6. 이번 주 바로 할 수 있는 첫 단계
7. 마무리 + 다음 글 예고
분량: 2500~3000자
"""

    prompt = f"""
{base_rules}

## 수집된 최신 정보
{deep_research if deep_research else f"{topic} 관련 {year}년 최신 정보"}

{structure}

## 출력 (JSON만, 코드블록 없이)
{{
  "title_candidates": [
    "[핵심키워드] + [방법/금액/결과] + [대상 or {year}] 형식의 SEO 제목 1 (클릭베이트 금지)",
    "[핵심키워드] + [방법/금액/결과] + [대상 or {year}] 형식의 SEO 제목 2 (클릭베이트 금지)",
    "[핵심키워드] + [방법/금액/결과] + [대상 or {year}] 형식의 SEO 제목 3 (클릭베이트 금지)",
    "[핵심키워드] + [방법/금액/결과] + [대상 or {year}] 형식의 SEO 제목 4 (클릭베이트 금지)",
    "[핵심키워드] + [방법/금액/결과] + [대상 or {year}] 형식의 SEO 제목 5 (클릭베이트 금지)"
  ],
  "meta_description": "구글 클릭률 높은 메타설명 150자 이내",
  "tags": ["태그1", "태그2", "태그3"],
  "slug": "seo-korean-slug-{year}",
  "content_html": "완성된 HTML 본문 — 아래 스타일 가이드 반드시 적용"
}}

## HTML 스타일 가이드 (content_html에 반드시 적용)
포인트 컬러: #059669 (에메랄드/초록) — AI 재테크 스쿨 브랜드 색상

1. 핵심 요약 박스 (글 상단에 반드시 1개 사용):
<div style="background:#ECFDF5;border-left:4px solid #059669;border-radius:0 8px 8px 0;padding:16px 20px;margin:24px 0"><p style="margin:0 0 6px;font-size:14px;font-weight:700;color:#065F46">💰 핵심 포인트</p><p style="margin:0;font-size:14px;color:#064E3B;line-height:1.7">핵심 내용</p></div>

2. 번호 카드 (단계별/방법별 설명에 사용, 3~5개):
<div style="background:#fff;border:1px solid #A7F3D0;border-radius:12px;padding:16px;display:flex;gap:16px;align-items:flex-start;margin-bottom:12px"><div style="background:#059669;color:#fff;font-size:14px;font-weight:700;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0">1</div><div><p style="margin:0 0 6px;font-size:15px;font-weight:700;color:#064E3B">제목</p><p style="margin:0;font-size:14px;color:#4B5563;line-height:1.6">내용</p></div></div>

3. 수익/팁 강조 박스:
<div style="background:#ECFDF5;border-radius:12px;padding:16px 20px;margin:20px 0"><p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#059669">💡 꿀팁</p><p style="margin:0;font-size:14px;color:#065F46;line-height:1.6">내용. 수익/금액은 <mark style="background:#6EE7B7;color:#065F46;padding:2px 6px;border-radius:4px">이렇게 강조</mark></p></div>

4. h2 섹션 제목:
<h2 style="font-size:18px;font-weight:700;color:#064E3B;margin:32px 0 16px;padding-bottom:8px;border-bottom:2px solid #059669">섹션 제목</h2>

규칙: 모든 섹션에 위 스타일 중 하나 이상 반드시 사용. 일반 텍스트 나열 금지. 수익/금액 수치는 반드시 mark 태그로 강조.
"""
    post_data = call_claude(prompt)
    log.info("  ✅ 블로그 글 생성 완료")
    return post_data


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: SEO 제목 선택 (이중 필터)
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
            "content": f"""다음 제목 후보 중 아래 SEO 규칙에 가장 잘 맞는 제목 1개만 출력해줘 (번호 없이).

## SEO 선택 기준
- 핵심 키워드가 제목 앞부분에 위치할 것
- 숫자 포함 (월 수익, 방법 수, 시간 등)
- "충격!", "대박!", "미쳤다" 같은 클릭베이트 표현 없을 것
- 실제로 검색할 법한 자연스러운 표현
- 부업/재테크 관심자가 클릭하고 싶은 제목

후보:
{candidates}""",
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
                "조건: 밝고 친근한 재테크/돈/AI 일러스트, 텍스트 없음, 16:9.\n"
                "프롬프트만 출력:"
            ),
        }],
    )
    prompt = response.content[0].text.strip()
    log.info(f"  ✅ 프롬프트: {prompt[:60]}...")
    return prompt


# ═════════════════════════════════════════════════════════════════════════════
# STEP 6: 썸네일 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_thumbnail(image_prompt: str) -> str:
    log.info("🎨 썸네일 생성 중...")
    enhanced = (
        f"{image_prompt}, modern flat illustration, vibrant colors, "
        "16:9 blog thumbnail, no text no letters, "
        "money finance AI theme, bright friendly"
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
                log.info("  ✅ 썸네일 생성 완료")
                return part["inlineData"]["data"]
        raise ValueError("이미지 데이터 없음")
    except Exception as e:
        log.warning(f"  ⚠️ 썸네일 생성 실패 ({e})")
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

    image_url = upload_image_to_imgur(image_b64)
    if not image_url:
        image_url = "https://placehold.co/1200x630/1D9E75/ffffff?text=AI+재테크+스쿨"

    full_html = f"""
<div style="margin-bottom:2rem;">
  <img src="{image_url}" alt="{title}"
       style="width:100%;border-radius:12px;max-height:420px;object-fit:cover;" />
</div>

{post_data['content_html']}

<hr style="margin:3rem 0;border:none;border-top:1px solid #eee;" />
<div style="background:#f0fdf4;padding:1.5rem;border-radius:8px;margin-top:2rem;">
  <p style="margin:0;font-size:0.9rem;color:#555;">
    📌 <strong>AI 재테크 스쿨</strong>은 AI 도구를 활용해서 부업하고 재테크하는 방법을
    매일 업데이트합니다. 구독하고 놓치지 마세요! 🔔
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
    log.info("🚀 AI 재테크 스쿨 자동화 시작")
    log.info(f"   날짜: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    try:
        track, tool_name = get_track()
        log.info(f"  📌 트랙: {track.upper()}" + (f" | 툴: {tool_name}" if tool_name else ""))

        topic_data    = decide_topic(track, tool_name)
        deep_research = collect_deep_research(topic_data)
        post_data     = generate_post(track, topic_data, deep_research)
        best_title    = select_best_title(post_data)

        image_prompt = generate_image_prompt(best_title, post_data)
        image_b64    = generate_thumbnail(image_prompt)

        blog_url = post_to_blogger(best_title, post_data, image_b64)

        log.info("=" * 60)
        log.info("🎉 전체 파이프라인 완료!")
        log.info(f"   트랙: {track.upper()} | 주제: {topic_data['topic']}")
        log.info(f"   블로그 URL: {blog_url}")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"❌ 자동화 실패: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
