"""
바이브코딩 스쿨 (VIBE CODING School) — Blog Automation
────────────────────────────────────────────────────────
매일 아침 9시 / 저녁 9시 자동 실행:
1. 날짜 기반 주제 선택 (60개 풀 — 2달치 중복 없음)
2. 최신 뉴스 수집 (Claude 웹서치)
3. 바이브코딩 스쿨 스타일 블로그 글 작성
4. SEO 최적화 제목 선택
5. 글 내용 기반 이미지 프롬프트 생성
6. Gemini 2.5 Flash Image로 썸네일 생성 (무료, 하루 500장)
7. Google Blogger 자동 포스팅
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

# ── 로깅 ─────────────────────────────────────────────────────────────────────
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

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── 주제 풀 (60개 — 날짜 기반 순환, 2달치 중복 없음) ─────────────────────────
TOPICS = [
    # 도구 실전 리뷰
    ("Claude Code 실전 사용법", "Claude Code AI코딩 사용법 장단점 솔직 리뷰"),
    ("Cursor AI 완전 정복", "Cursor AI 설치부터 첫 앱 완성까지 단계별 가이드"),
    ("Windsurf IDE 심층 리뷰", "Windsurf IDE Cursor와 차이점 비교 분석"),
    ("Lovable로 웹앱 만들기", "Lovable 브라우저에서 30분 만에 웹앱 만드는 법"),
    ("Replit Agent 실전 후기", "Replit Agent 브라우저에서 앱 배포 실제 사용기"),
    ("GitHub Copilot 2026 업데이트", "GitHub Copilot 최신 기능 변화와 실전 팁"),
    ("Bolt.new 솔직 후기", "Bolt.new 진짜 쓸만한가 실제 프로젝트로 테스트"),
    ("v0 by Vercel UI 자동생성", "v0 Vercel UI 컴포넌트 자동 생성 실전 가이드"),
    # 초보자 입문
    ("코딩 0% 앱 만들기 첫걸음", "코딩 전혀 몰라도 AI로 앱 만드는 방법 완전 입문"),
    ("비개발자 첫 앱 출시 후기", "비개발자가 바이브코딩으로 첫 앱 출시한 실제 이야기"),
    ("AI 코딩 도구 선택 가이드", "초보자를 위한 AI 코딩 도구 고르는 법 2026 기준"),
    ("직장인 사이드프로젝트 앱 만들기", "퇴근 후 2시간으로 사이드프로젝트 앱 완성하는 법"),
    ("주부가 앱 만든 이야기", "코딩 몰라도 AI 도구로 생활앱 만든 실제 후기"),
    ("프리랜서 업무 자동화 앱", "AI 코딩으로 반복 업무 자동화 앱 만들기"),
    ("소상공인 주문앱 만들기", "카페 사장님이 직접 만든 주문 앱 바이브코딩 후기"),
    # 심화 주제
    ("바이브코딩 보안 주의사항", "바이브코딩으로 만든 앱 보안 취약점 방지 방법"),
    ("AI 코딩 실패 사례 모음", "바이브코딩 이렇게 하면 실패한다 실전 교훈"),
    ("AI가 짠 코드 이해하는 법", "AI가 만든 코드 읽는 법 비개발자도 이해하는 팁"),
    ("앱 배포 완전 가이드", "바이브코딩으로 만든 앱 세상에 공개하는 방법"),
    ("데이터베이스 연결하기", "바이브코딩 앱에 데이터 저장 기능 추가하는 법"),
    # 트렌드 & 뉴스
    ("2026년 AI 코딩 트렌드", "2026년 AI 코딩 도구 시장 최신 동향 총정리"),
    ("Vibe Coding 콜린스 올해의 단어", "콜린스 영어사전 선정 2026 올해의 단어 바이브코딩"),
    ("AI 코딩 도구 시장 규모", "2026년 AI 개발 도구 시장 성장세와 전망"),
    ("구글 Antigravity IDE 등장", "구글이 만든 AI 코딩 도구 Antigravity 첫인상"),
    ("Cursor ARR 2조 돌파 의미", "Cursor 연 매출 2조 돌파가 의미하는 것"),
    # 비교 & 추천
    ("Claude Code vs Cursor 비교", "Claude Code Cursor 2026년 기준 실전 비교"),
    ("무료 AI 코딩 도구 추천", "돈 안 들이고 시작하는 AI 코딩 도구 추천"),
    ("모바일 앱 vs 웹앱 선택", "바이브코딩으로 모바일앱 웹앱 무엇을 만들어야 할까"),
    ("AI 코딩 유료 vs 무료 플랜", "AI 코딩 도구 무료로 충분한가 유료 플랜 비교"),
    ("한국어 지원 AI 코딩 도구", "한국어로 쓸 수 있는 AI 코딩 도구 총정리"),
    # 활용 사례
    ("인스타그램 스케줄러 앱 만들기", "AI 코딩으로 SNS 자동 포스팅 앱 만드는 법"),
    ("가계부 앱 바이브코딩", "바이브코딩으로 나만의 가계부 앱 만들기"),
    ("할일 관리 앱 만들기", "AI 코딩으로 나만의 할일 관리 앱 30분 완성"),
    ("블로그 자동화 앱 만들기", "AI 코딩으로 블로그 자동 포스팅 시스템 구축"),
    ("예약 관리 앱 만들기", "소규모 비즈니스를 위한 예약 관리 앱 바이브코딩"),
    ("AI 챗봇 만들기", "내 홈페이지에 AI 챗봇 붙이는 법 바이브코딩"),
    ("포트폴리오 웹사이트", "바이브코딩으로 1시간 만에 포트폴리오 사이트 완성"),
    ("쇼핑몰 만들기", "AI 코딩으로 간단한 온라인 쇼핑몰 만드는 법"),
    ("설문조사 앱 만들기", "바이브코딩으로 구글폼보다 나은 설문 앱 만들기"),
    # 수익화
    ("바이브코딩으로 돈 버는 법", "AI 코딩 도구로 앱 만들어 수익화하는 현실적인 방법"),
    ("앱스토어 등록 가이드", "바이브코딩 앱 앱스토어에 출시하는 방법"),
    ("SaaS 창업 바이브코딩", "비개발자가 AI 코딩으로 SaaS 서비스 창업한 사례"),
    ("프리랜서 수입 올리기", "AI 코딩 도구로 프리랜서 단가 높이는 방법"),
    ("앱 광고 수익 내기", "바이브코딩 앱에 광고 붙여 수익 만드는 법"),
    # 미래 전망
    ("AI 코딩이 바꾸는 일자리", "AI 코딩 도구가 개발자 직업에 미치는 영향"),
    ("비개발자의 시대", "코딩 몰라도 되는 시대 비개발자가 강자가 되는 법"),
    ("2027년 AI 코딩 예측", "2027년 AI 코딩 도구는 어떻게 변할까"),
    ("AI 코딩 교육 어디서", "바이브코딩 제대로 배우는 무료 유료 교육 추천"),
    ("개발자와 비개발자 협업", "AI 코딩 시대 개발자와 비개발자가 함께 일하는 법"),
    # 기술 팁
    ("프롬프트 잘 쓰는 법", "AI 코딩 도구에 명령 잘 내리는 프롬프트 작성법"),
    ("오류 메시지 해결하는 법", "바이브코딩 중 에러 났을 때 AI에게 물어보는 법"),
    ("버전 관리 입문", "AI 코딩 초보자를 위한 깃허브 기초 사용법"),
    ("API 연결하기", "바이브코딩 앱에 외부 API 연결하는 법 쉽게 설명"),
    ("반응형 디자인 만들기", "AI 코딩으로 모바일에서도 예쁜 앱 만드는 팁"),
    ("로그인 기능 추가하기", "바이브코딩 앱에 회원가입 로그인 기능 넣는 법"),
    ("결제 기능 연동하기", "AI 코딩으로 만든 앱에 결제 기능 붙이는 법"),
    ("SEO 최적화 앱 만들기", "바이브코딩으로 구글 검색에 잘 잡히는 사이트 만들기"),
    ("앱 성능 최적화", "AI가 만든 앱 느릴 때 빠르게 만드는 방법"),
    ("다국어 앱 만들기", "바이브코딩으로 한국어 영어 지원되는 앱 만들기"),
]


def get_todays_topic() -> tuple:
    """날짜 기반으로 오늘의 주제 선택 — 매일 다른 주제, 60일 순환"""
    now = datetime.now()
    # 하루 2회 포스팅: 오전(0~11시)과 오후(12~23시) 다른 주제
    slot = now.timetuple().tm_yday * 2 + (0 if now.hour < 12 else 1)
    idx = slot % len(TOPICS)
    topic_title, search_query = TOPICS[idx]
    log.info(f"  📌 오늘의 주제 [{idx+1}/{len(TOPICS)}]: {topic_title}")
    return topic_title, search_query


# ═════════════════════════════════════════════════════════════════════════════
# 1단계: 최신 뉴스 수집
# ═════════════════════════════════════════════════════════════════════════════
def extract_text(response) -> str:
    """Claude 응답에서 텍스트 안전하게 추출"""
    texts = []
    for block in response.content:
        if hasattr(block, "text") and isinstance(block.text, str) and block.text.strip():
            texts.append(block.text.strip())
    return "\n".join(texts)


def collect_latest_news(topic_title: str, search_query: str) -> dict:
    """오늘의 주제에 맞는 최신 뉴스 수집"""
    log.info("📡 최신 뉴스 수집 시작...")

    today = datetime.now().strftime("%Y년 %m월 %d일")
    year  = datetime.now().year

    queries = [
        f"{search_query} {year} 최신",
        f"vibe coding {topic_title} {year}",
    ]

    collected = []
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
            log.warning(f"  ⚠️ '{q}' 검색 실패: {e}")
            time.sleep(3)

    log.info(f"  ✅ 총 {len(collected)}개 뉴스 수집 완료")
    return {"date": today, "items": collected}


# ═════════════════════════════════════════════════════════════════════════════
# 2단계: 블로그 글 작성
# ═════════════════════════════════════════════════════════════════════════════
def generate_blog_post(topic_title: str, news_data: dict) -> dict:
    """바이브코딩 스쿨 스타일의 교육용 블로그 글 생성"""
    log.info("✍️  블로그 글 작성 시작...")

    year = datetime.now().year

    if news_data["items"]:
        news_summary = "\n\n".join(
            f"[검색: {item['query']}]\n{item['summary']}"
            for item in news_data["items"]
        )
    else:
        news_summary = f"{year}년 기준 AI 코딩 도구 최신 트렌드 관련 내용"

    prompt = f"""
당신은 '바이브코딩 스쿨(VIBE CODING School)' 블로그의 전문 에디터입니다.
코딩을 전혀 모르는 일반인도 AI 도구로 앱을 만들 수 있도록 돕는 교육 블로그입니다.

오늘 날짜: {news_data['date']}
오늘 주제: {topic_title}

## 수집된 최신 정보
{news_summary}

## 바이브코딩 스쿨 글쓰기 원칙
1. 독자: 코딩 0%의 일반인 (직장인, 소상공인, 학생, 주부 등)
2. 어조: 친근하고 따뜻한 선생님 스타일. "~해요", "~거예요" 말투
3. 전문용어 금지: 반드시 쉬운 말로 풀어서 설명
4. 실용적: 읽고 나면 바로 따라할 수 있는 내용
5. 분량: 2,500~3,000자
6. {year}년 현재 기준 (다른 연도 언급 금지)
7. 수집된 최신 뉴스/정보를 반드시 본문에 녹여낼 것

## 글 구조
1. 공감 도입부: 독자가 겪는 불편함/바람으로 시작
2. 핵심 개념 설명: 오늘 주제를 아주 쉽게 정의
3. 최신 트렌드/뉴스: 수집된 정보 활용
4. 실전 내용: 도구 소개 또는 단계별 방법
5. 주의사항 또는 꿀팁
6. 마무리 + 다음 글 예고

## 출력 (JSON만, 코드블록 없이)
{{
  "title_candidates": [
    "클릭률 높은 SEO 제목 후보 {year}년 기준 1",
    "클릭률 높은 SEO 제목 후보 {year}년 기준 2",
    "클릭률 높은 SEO 제목 후보 {year}년 기준 3",
    "클릭률 높은 SEO 제목 후보 {year}년 기준 4",
    "클릭률 높은 SEO 제목 후보 {year}년 기준 5"
  ],
  "meta_description": "구글 검색 클릭률 높은 메타설명 150자 이내",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "slug": "seo-friendly-english-slug",
  "content_html": "완성된 HTML 본문 (h2 h3 p ul li strong 사용)"
}}
"""

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

    post_data = json.loads(raw.strip())
    log.info("  ✅ 블로그 글 생성 완료")
    return post_data


# ═════════════════════════════════════════════════════════════════════════════
# 3단계: SEO 제목 선택
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
# 4단계: 글 내용 기반 이미지 프롬프트 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_image_prompt(title: str, post_data: dict) -> str:
    log.info("🖼️  이미지 프롬프트 생성 중... (글 내용 기반)")

    tags = ", ".join(post_data.get("tags", []))
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": (
                f"블로그 썸네일용 이미지 프롬프트를 영문으로 만들어줘.\n"
                f"제목: {title}\n태그: {tags}\n\n"
                "조건: 영문 50단어 이내, 밝고 친근한 테크 일러스트, "
                "사람이 AI 도구로 쉽게 앱 만드는 느낌, 텍스트 없음.\n"
                "프롬프트만 출력:"
            ),
        }],
    )
    prompt = response.content[0].text.strip()
    log.info(f"  ✅ 프롬프트: {prompt[:60]}...")
    return prompt


# ═════════════════════════════════════════════════════════════════════════════
# 5단계: Gemini 2.5 Flash Image 이미지 생성 (무료 — 하루 500장)
# ═════════════════════════════════════════════════════════════════════════════
def generate_thumbnail(image_prompt: str) -> str:
    """
    Gemini 2.5 Flash Image (Nano Banana) — 2026년 무료 이미지 생성 모델
    모델 ID: gemini-2.5-flash-image (무료 500장/일)
    """
    log.info("🎨 썸네일 생성 중... (Gemini 2.5 Flash Image / 무료)")

    enhanced = (
        f"{image_prompt}, modern flat illustration, vibrant colors, "
        "16:9 blog thumbnail format, no text no letters, "
        "professional tech design, bright friendly atmosphere"
    )

    try:
        # Gemini 2.5 Flash Image — generateContent 엔드포인트 사용
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash-image:generateContent?key={GEMINI_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": enhanced}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE", "TEXT"],
            },
        }
        resp = requests.post(url, json=payload, timeout=90)
        resp.raise_for_status()
        data = resp.json()

        for part in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                b64 = part["inlineData"]["data"]
                log.info("  ✅ 이미지 생성 완료 (Gemini 2.5 Flash Image)")
                return b64

        raise ValueError("응답에 이미지 데이터 없음")

    except Exception as e:
        log.warning(f"  ⚠️ 이미지 생성 실패 ({e}), 플레이스홀더 사용")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# 6단계: Google Blogger 포스팅
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
    📌 <strong>바이브코딩 스쿨</strong>은 코딩을 몰라도 AI로 앱을 만들 수 있도록
    매일 아침·저녁 최신 내용을 업데이트합니다. 구독하고 놓치지 마세요! 🔔
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

    result = service.posts().insert(
        blogId=BLOGGER_BLOG_ID, body=body, isDraft=False
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
        # 오늘의 주제 선택 (날짜 기반 순환)
        topic_title, search_query = get_todays_topic()

        # 뉴스 수집
        news_data = collect_latest_news(topic_title, search_query)

        # 글 작성
        post_data = generate_blog_post(topic_title, news_data)

        # SEO 제목 선택
        best_title = select_best_title(post_data)

        # 이미지 프롬프트 생성 (글 내용 기반 — 뉴스 수집 실패와 무관)
        image_prompt = generate_image_prompt(best_title, post_data)

        # 이미지 생성
        image_b64 = generate_thumbnail(image_prompt)

        # 포스팅
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
